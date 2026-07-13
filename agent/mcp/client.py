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
MCP Streamable HTTP 同步传输客户端

``MCPConnection`` 封装单个 MCP 服务端的连接生命周期：
initialize 握手 -> 捕获 ``Mcp-Session-Id`` -> notifications/initialized ->
tools/list 发现 -> tools/call 调用 -> DELETE 终止。全程同步（``httpx.Client``）。

响应按 ``Content-Type`` 分流：``application/json`` 直解析；
``text/event-stream`` 按 SSE 规范逐行解析，按 JSON-RPC ``id`` 匹配本次请求的响应。
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# 协议版本（MCP Streamable HTTP，2025-03-26）
_PROTOCOL_VERSION = "2025-03-26"
_CLIENT_VERSION = "1.0.0"
_CLIENT_NAME = "lemonclaw"


@dataclass
class ToolInfo:
    """远程工具元信息（来自 tools/list）"""
    name: str                                # 远程工具名
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)


def _extract_text(content: list[dict]) -> str:
    """从 content 块列表中拼接 text 类型内容。"""
    parts = []
    for blk in content or []:
        if isinstance(blk, dict) and blk.get("type") == "text":
            parts.append(blk.get("text", ""))
    return "\n".join(parts)


class MCPConnection:
    """单个 MCP 服务端的 Streamable HTTP 同步连接（httpx.Client）。

    职责：initialize 握手 -> 捕获 Mcp-Session-Id -> notifications/initialized ->
    tools/list 发现 -> tools/call 调用 -> DELETE 终止。全程同步。
    """

    def __init__(self, server_id: str, url: str, headers: dict[str, str],
                 connect_timeout: int, call_timeout: int, result_max_chars: int,
                 transport: httpx.BaseTransport | None = None):
        self.server_id = server_id
        self.url = url
        self.headers = headers or {}                  # 含认证密钥，原样发出，不经替换
        self.connect_timeout = connect_timeout
        self.call_timeout = call_timeout
        self.result_max_chars = result_max_chars
        self.transport = transport                     # 测试注入（httpx.MockTransport）；生产为 None
        self.client: httpx.Client | None = None
        self.session_id: str | None = None            # Mcp-Session-Id
        self.protocol_version: str = ""
        self.server_info: dict[str, Any] = {}
        self.tools: list[ToolInfo] = []               # 已发现工具
        self.status: str = "disconnected"             # connecting/connected/error/disconnected
        self.last_error: str | None = None
        self._next_rpc_id = 1

    # ============ 连接 ============

    def connect(self) -> tuple[bool, str]:
        """initialize + notifications/initialized + tools/list。

        成功 -> (True, "")；失败 -> (False, err_msg)，status=error。
        """
        self.status = "connecting"
        self.last_error = None
        try:
            self.client = httpx.Client(timeout=self.connect_timeout, transport=self.transport)
            # 1. initialize
            resp = self._post_request({
                "jsonrpc": "2.0", "id": self._alloc_id(), "method": "initialize",
                "params": {
                    "protocolVersion": _PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": _CLIENT_NAME, "version": _CLIENT_VERSION},
                },
            }, timeout=self.connect_timeout)
            result = resp.get("result", {}) or {}
            self.protocol_version = result.get("protocolVersion", "") or ""
            self.server_info = result.get("serverInfo", {}) or {}
            # 2. notifications/initialized（无 id，无响应）
            self._post_notification({"jsonrpc": "2.0", "method": "notifications/initialized"})
            # 3. tools/list
            resp2 = self._post_request({
                "jsonrpc": "2.0", "id": self._alloc_id(), "method": "tools/list", "params": {},
            }, timeout=self.connect_timeout)
            tools = (resp2.get("result", {}) or {}).get("tools", []) or []
            self.tools = [
                ToolInfo(
                    name=t.get("name", ""),
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}) or {},
                )
                for t in tools if isinstance(t, dict) and t.get("name")
            ]
            self.status = "connected"
            logger.info(f"MCP 服务 {self.server_id} 已连接：协议 {self.protocol_version}，"
                        f"发现 {len(self.tools)} 个工具")
            return True, ""
        except Exception as e:
            self.status = "error"
            self.last_error = str(e)
            logger.warning(f"MCP 服务 {self.server_id} 连接失败: {e}")
            if self.client is not None:
                try:
                    self.client.close()
                except Exception:
                    pass
                self.client = None
            return False, str(e)

    def disconnect(self) -> None:
        """有 session_id 则 DELETE 终止，关闭 client；status=disconnected。"""
        if self.client is None:
            self.status = "disconnected"
            return
        if self.session_id:
            try:
                self.client.delete(
                    self.url,
                    headers=self._request_headers(),
                    timeout=self.connect_timeout,
                )
            except Exception as e:
                logger.debug(f"MCP 服务 {self.server_id} DELETE 终止失败（忽略）: {e}")
        try:
            self.client.close()
        except Exception:
            pass
        self.client = None
        self.session_id = None
        self.status = "disconnected"

    # ============ 调用 ============

    def call_tool(self, name: str, arguments: dict) -> str:
        """tools/call，格式化结果（截断、isError 处理）；失败返回 ❌ 字符串。"""
        if self.status != "connected" or self.client is None:
            return f"❌ MCP 服务 {self.server_id} 未连接，请执行 /mcp reconnect {self.server_id}"
        try:
            resp = self._post_request({
                "jsonrpc": "2.0", "id": self._alloc_id(), "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            }, timeout=self.call_timeout)
            err = resp.get("error")
            if err:
                return f"❌ MCP 工具 {name} 返回错误: {err.get('message', str(err))}"
            result = resp.get("result", {}) or {}
            return self._format_result(result, name)
        except httpx.TimeoutException:
            return f"❌ MCP 工具调用超时（{self.call_timeout}s）：{name}"
        except Exception as e:
            self.last_error = str(e)
            return f"❌ MCP 工具调用失败: {e}"

    def list_tools(self) -> list[ToolInfo]:
        """返回已缓存工具列表（连接时发现，不重复请求）。"""
        return self.tools

    # ============ 内部 ============

    def _alloc_id(self) -> int:
        rid = self._next_rpc_id
        self._next_rpc_id += 1
        return rid

    def _request_headers(self) -> dict[str, str]:
        """组装请求头：self.headers（含密钥，原样）+ 协议约定头。headers 不经任何替换。"""
        h = dict(self.headers or {})
        h["Content-Type"] = "application/json"
        h["Accept"] = "application/json, text/event-stream"
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        return h

    def _post_request(self, payload: dict, timeout: int | None = None) -> dict:
        """发送 JSON-RPC 请求（有 id），回传 session_id 头，按 Content-Type 解析（JSON 或 SSE），
        按 id 匹配返回响应 dict（含 result/error）。"""
        if self.client is None:
            raise RuntimeError("httpx.Client 未初始化")
        to = timeout if timeout is not None else self.call_timeout
        with self.client.stream(
            "POST", self.url, headers=self._request_headers(), json=payload, timeout=to,
        ) as resp:
            sid = resp.headers.get("mcp-session-id")
            if sid:
                self.session_id = sid
            if resp.status_code >= 400:
                body = resp.read().decode("utf-8", errors="replace")[:500]
                raise RuntimeError(f"HTTP {resp.status_code}: {body}")
            return self._parse_response(resp, payload.get("id"))

    def _post_notification(self, payload: dict, timeout: int | None = None) -> None:
        """发送 JSON-RPC 通知（无 id，无响应）。服务端通常回 202，忽略响应体。"""
        if self.client is None:
            return
        to = timeout if timeout is not None else self.connect_timeout
        try:
            resp = self.client.post(
                self.url, headers=self._request_headers(), json=payload, timeout=to,
            )
            if resp.status_code >= 400:
                logger.debug(f"MCP 服务 {self.server_id} 通知 {payload.get('method')} "
                             f"返回 {resp.status_code}（忽略）")
        except Exception as e:
            logger.debug(f"MCP 服务 {self.server_id} 通知 {payload.get('method')} 失败（忽略）: {e}")

    def _parse_response(self, resp: httpx.Response, expected_id: int | None) -> dict:
        """application/json -> resp.json()；text/event-stream -> SSE 逐行解析按 id 匹配。"""
        ctype = resp.headers.get("content-type", "")
        if "text/event-stream" in ctype:
            data_lines: list[str] = []
            for line in resp.iter_lines():
                if line is None:
                    continue
                if line == "":
                    # 空行结束一个 event
                    if data_lines:
                        payload_str = "\n".join(data_lines)
                        try:
                            msg = json.loads(payload_str)
                            if expected_id is not None and msg.get("id") == expected_id:
                                return msg
                        except (json.JSONDecodeError, ValueError):
                            pass
                        data_lines = []
                    continue
                if line.startswith("data:"):
                    data_lines.append(line[len("data:"):].lstrip(" "))
                # 忽略 event: / id: / retry: / 注释行
            raise RuntimeError("SSE 流未返回匹配响应（id 未匹配）")
        # JSON 响应
        resp.read()
        return resp.json()

    def _format_result(self, result: dict, tool_name: str) -> str:
        """格式化 tools/call 结果：isError / content 块 / 非 text 占位 / 截断。"""
        if result.get("isError"):
            text = _extract_text(result.get("content", []))
            return f"❌ MCP 工具 {tool_name} 返回错误: {text}"
        parts: list[str] = []
        for blk in result.get("content", []) or []:
            if not isinstance(blk, dict):
                continue
            t = blk.get("type")
            if t == "text":
                parts.append(blk.get("text", ""))
            elif t == "image":
                parts.append(f"[image: {blk.get('mimeType', '?')}]")
            elif t == "audio":
                parts.append(f"[audio: {blk.get('mimeType', '?')}]")
            elif t == "resource":
                res = blk.get("resource", {}) or {}
                parts.append(f"[resource: {res.get('uri', '?')}]")
            else:
                parts.append(f"[{t}]")
        text = "\n".join(p for p in parts if p)
        if len(text) > self.result_max_chars:
            half = self.result_max_chars // 2
            text = text[:half] + "\n\n[... MCP 结果较长，已截断 ...]\n\n" + text[-half:]
        return text
