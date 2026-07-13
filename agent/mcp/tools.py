# Copyright 2026 LemonClaw Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
MCP 工具层：将 MCP 远程工具包装为 LangChain ``BaseTool``

- ``_json_schema_to_pydantic``：MCP 工具 ``inputSchema``（JSON Schema）-> Pydantic 模型
- ``_sanitize_tool_name``：远程工具名 -> 合法 LangChain 工具名片段
- ``MCPToolWrapper``：单个远程工具的 LangChain 适配器，``_run`` 经 ``MCPManager.call_tool`` 调用
- ``create_mcp_tools``：工厂，``manager`` 为 None 时返回空列表
"""

import logging
import re
from typing import Any, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, create_model

logger = logging.getLogger(__name__)

_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}

_DESC_MAX = 1024


def _json_type_to_python(t: str | None) -> Any:
    """JSON Schema type -> Python 类型；未知/缺失 -> Any。"""
    if isinstance(t, list):
        # type 联合（如 ["string","null"]）取首个非 null
        for sub in t:
            if sub != "null":
                return _TYPE_MAP.get(sub, Any)
        return Any
    return _TYPE_MAP.get(t, Any) if t else Any


def _json_schema_to_pydantic(schema: dict | None, name: str) -> Type[BaseModel]:
    """JSON Schema -> Pydantic 模型（``pydantic.create_model``）。

    见 Spec §4.7；转换异常退化为单字段 ``arguments: dict`` 模型，保证工具仍可注册。
    """
    try:
        schema = schema or {}
        props = schema.get("properties", {}) or {}
        required = set(schema.get("required", []) or [])
        fields: dict[str, Any] = {}
        for prop_name, prop_schema in props.items():
            if not isinstance(prop_schema, dict):
                fields[prop_name] = (Any, Field(default=None))
                continue
            py_type = _json_type_to_python(prop_schema.get("type"))
            desc = prop_schema.get("description", "") or ""
            if prop_name in required:
                fields[prop_name] = (py_type, Field(..., description=desc))
            else:
                fields[prop_name] = (py_type, Field(default=None, description=desc))
        # extra=allow：LLM 传入 schema 外字段时透传给 MCP 服务端，由服务端裁决
        return create_model(_safe_model_name(name), __config__=ConfigDict(extra="allow"), **fields)
    except Exception as e:
        logger.warning(f"JSON Schema -> Pydantic 转换失败（{name}），退化为 arguments: dict 模型: {e}")
        return create_model(
            _safe_model_name(name),
            __config__=ConfigDict(extra="allow"),
            arguments=(dict, Field(default_factory=dict, description="工具参数（JSON 对象）")),
        )


def _safe_model_name(raw: str) -> str:
    """Pydantic 模型名须合法标识符。"""
    name = re.sub(r"[^a-zA-Z0-9_]", "_", raw or "MCPArgs")
    if name and name[0].isdigit():
        name = "_" + name
    return name or "MCPArgs"


def _sanitize_tool_name(raw: str) -> str:
    """远程工具名 -> 合法 LangChain 工具名片段（[a-zA-Z0-9_]）。"""
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", raw or "")
    if len(sanitized) > 64:
        sanitized = sanitized[:64]
    return sanitized or "tool"


class MCPToolWrapper(BaseTool):
    """单个 MCP 远程工具的 LangChain 适配器。

    ``_run`` 经 ``MCPManager.call_tool`` 调用（统计 access_count），而非直连 connection。
    """

    name: str
    description: str
    args_schema: Type[BaseModel]
    _connection: Any = PrivateAttr()
    _remote_name: str = PrivateAttr()
    _manager: Any = PrivateAttr()

    def __init__(self, connection: Any, manager: Any, remote_name: str,
                 description: str, args_schema: Type[BaseModel], tool_name: str):
        super().__init__(name=tool_name, description=description, args_schema=args_schema)
        self._connection = connection
        self._manager = manager
        self._remote_name = remote_name

    def _run(self, *args, **kwargs) -> str:
        try:
            arguments = self._extract_arguments(kwargs)
            return self._manager.call_tool(self._connection.server_id, self._remote_name, arguments)
        except Exception as e:
            return f"❌ MCP 工具调用失败: {e}"

    @staticmethod
    def _extract_arguments(kwargs: dict) -> dict:
        """从 _run kwargs 提取 arguments dict。

        - 正常 schema：kwargs 即字段值；
        - 退化 schema（单 arguments: dict 字段）：取 arguments。
        """
        if len(kwargs) == 1 and "arguments" in kwargs and isinstance(kwargs["arguments"], dict):
            return kwargs["arguments"]
        return {k: v for k, v in dict(kwargs).items() if v is not None} or {}


def create_mcp_tools(manager: Any | None) -> list:
    """创建 MCP 工具集；manager 为 None 时返回空列表。"""
    if manager is None:
        return []
    return manager.get_langchain_tools()
