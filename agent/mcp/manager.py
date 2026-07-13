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
MCP 业务门面 ``MCPManager``

- 服务端 CRUD（持久化到 ``.lemonclaw/mcp.json`` + ``mcp_servers`` 表）
- 连接池（``_connections``：server_id -> ``MCPConnection``）
- 工具收集（``get_langchain_tools``：每远程工具 -> ``MCPToolWrapper``）
- 热重载（``reload``：重读 mcp.json + 重连 enabled）
- 工具调用（``call_tool``：供 ``/mcp call`` 与 ``MCPToolWrapper`` 调用，递增 access_count）

mcp.json 为服务端定义的唯一来源；DB 镜像定义 + 持有 ``enabled``/统计/缓存（对齐 Skills）。
"""

import json
import logging
import re
from datetime import datetime
from typing import Any

from config import get_global_config
from dao.db import get_db_path
from dao.mcp_server import MCPServer, MCPServerDAO, ensure_mcp_schema

from agent.mcp.client import MCPConnection, ToolInfo

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _valid_id(sid: str) -> bool:
    return bool(isinstance(sid, str) and _ID_RE.match(sid))


def _valid_url(url: str) -> bool:
    return isinstance(url, str) and (url.startswith("http://") or url.startswith("https://"))


def _detect_dup_keys(pairs):
    """json object_pairs_hook：检测重复 key 并告警（last-wins）。"""
    seen = set()
    dups = []
    for k, _ in pairs:
        if k in seen:
            dups.append(k)
        seen.add(k)
    if dups:
        logger.warning(f"mcp.json 检测到重复 key（按 last-wins）: {dups}")
    return dict(pairs)


class MCPManager:
    """MCP 业务门面：服务端 CRUD + 连接池 + 工具收集 + 热重载。"""

    GLOBAL_TOOL_HARD_CAP = 200

    def __init__(self):
        ensure_mcp_schema()
        cfg = get_global_config()
        self.connect_timeout: int = cfg.MCP_CONNECT_TIMEOUT
        self.call_timeout: int = cfg.MCP_CALL_TIMEOUT
        self.max_tools: int = cfg.MCP_MAX_TOOLS
        self.result_max_chars: int = cfg.MCP_RESULT_MAX_CHARS
        self.dao = MCPServerDAO()
        self.config_path = get_db_path().parent / "mcp.json"   # .lemonclaw/mcp.json（固定路径）
        self._connections: dict[str, MCPConnection] = {}
        self._sync_from_file()          # mcp.json -> DB（upsert + delete_missing）
        self._auto_connect_all()

    # ============ 配置文件（mcp.json 为唯一来源）============

    def _load_mcp_json(self) -> dict[str, dict]:
        """读 mcp.json（顶层对象，key 为 server_id）；文件不存在/格式错误返回 {}。"""
        if not self.config_path.exists():
            return {}
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f, object_pairs_hook=_detect_dup_keys)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"mcp.json 解析失败，视为无配置: {e}")
            return {}
        if not isinstance(data, dict):
            logger.warning("mcp.json 顶层非对象，视为无配置")
            return {}
        # 仅保留值为对象的条目
        return {k: v for k, v in data.items() if isinstance(v, dict)}

    def _save_mcp_json(self, servers: dict[str, dict]) -> None:
        """回写 mcp.json（json.dump, ensure_ascii=False, indent=2）。"""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(servers, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.warning(f"回写 mcp.json 失败: {e}")

    def _sync_from_file(self) -> None:
        """读 mcp.json -> upsert 每个服务端定义到 DB（保留 enabled/统计）
        -> delete_missing（移除已从文件删除的服务端）。"""
        servers = self._load_mcp_json()
        ids: set[str] = set()
        for sid, cfg in servers.items():
            if not _valid_id(sid):
                logger.warning(f"mcp.json 非法 server_id 跳过: {sid!r}")
                continue
            url = cfg.get("url", "")
            if not _valid_url(url):
                logger.warning(f"mcp.json {sid} 非法 url 跳过: {url!r}")
                continue
            headers = cfg.get("headers", {}) or {}
            if not isinstance(headers, dict):
                logger.warning(f"mcp.json {sid} headers 非对象跳过")
                continue
            auto_connect = bool(cfg.get("auto_connect", True))
            server = MCPServer(server_id=sid, url=url, headers=headers, auto_connect=auto_connect)
            try:
                self.dao.upsert_metadata(server)
            except Exception as e:
                logger.warning(f"upsert mcp server {sid} 失败: {e}")
            ids.add(sid)
        try:
            self.dao.delete_missing(ids)
        except Exception as e:
            logger.warning(f"delete_missing 失败: {e}")

    # ============ 启动 ============

    def _auto_connect_all(self) -> None:
        """连接所有 enabled=1 且 auto_connect=1 的服务端；逐个 try/except，失败仅记状态。"""
        for server in self.dao.list_auto_connect():
            try:
                self.connect(server.server_id)
            except Exception as e:
                logger.warning(f"自动连接 {server.server_id} 异常: {e}")

    def _build_connection(self, server: MCPServer) -> MCPConnection:
        """据 MCPServer 配置构造 MCPConnection。"""
        return MCPConnection(
            server.server_id, server.url, server.headers,
            self.connect_timeout, self.call_timeout, self.result_max_chars,
        )

    # ============ 连接管理 ============

    def connect(self, server_id: str) -> tuple[bool, str]:
        """连接单个服务端（已连接先 disconnect）；成功后同步 DB 缓存。"""
        server = self.dao.get(server_id)
        if server is None:
            return False, f"MCP 服务 {server_id} 不存在"
        if server_id in self._connections:
            try:
                self._connections[server_id].disconnect()
            except Exception:
                pass
        conn = self._build_connection(server)
        self.dao.set_status(server_id, "connecting", None)
        self._connections[server_id] = conn
        ok, err = conn.connect()
        if ok:
            tools_cache = [
                {"name": t.name, "description": t.description, "inputSchema": t.input_schema}
                for t in conn.tools
            ]
            self.dao.sync_after_connect(
                server_id, conn.protocol_version, conn.server_info,
                tools_cache, len(conn.tools), "connected", datetime.now(),
            )
        else:
            self.dao.set_status(server_id, "error", err)
        return ok, err

    def disconnect(self, server_id: str) -> None:
        """断开并从 _connections 移除；状态落库。"""
        conn = self._connections.pop(server_id, None)
        if conn is not None:
            try:
                conn.disconnect()
            except Exception as e:
                logger.debug(f"断开 {server_id} 异常（忽略）: {e}")
        try:
            self.dao.set_status(server_id, "disconnected", None)
        except Exception:
            pass

    def reconnect(self, server_id: str) -> tuple[bool, str]:
        """disconnect + connect。"""
        self.disconnect(server_id)
        return self.connect(server_id)

    def reload(self) -> None:
        """热重载：_sync_from_file（重读 mcp.json，含密钥 -> upsert DB + delete_missing）
        -> 移除已删服务端的 _connections -> 重连所有 enabled -> 同步 DB。
        不重建 agent（由 AgentService.reload_mcp_tools 负责）。密钥在 mcp.json，无需重载 .env。"""
        self._sync_from_file()
        all_ids = {s.server_id for s in self.dao.list_all()}
        for sid in list(self._connections.keys()):
            if sid not in all_ids:
                self._connections[sid].disconnect()
                del self._connections[sid]
        for server in self.dao.list_all(include_disabled=False):
            try:
                self.connect(server.server_id)
            except Exception as e:
                logger.warning(f"reload 重连 {server.server_id} 异常: {e}")

    # ============ 服务端 CRUD ============

    def add_server(self, server_id: str, url: str, headers: dict) -> tuple[bool, str]:
        """校验 -> 追加到 mcp.json（_save_mcp_json 回写）-> _sync_from_file 同步 DB
        -> connect -> 返回 (ok, msg)。注册成功即使连接失败也返回 True。"""
        if not _valid_id(server_id):
            return False, f"非法 server_id（须匹配 ^[a-zA-Z0-9_-]+$）: {server_id}"
        if not _valid_url(url):
            return False, f"非法 url（须 http:// 或 https://）: {url}"
        if not isinstance(headers, dict):
            return False, "headers 须为 JSON 对象"
        existing = self._load_mcp_json()
        if server_id in existing or self.dao.get(server_id) is not None:
            return False, f"MCP 服务 {server_id} 已存在"
        existing[server_id] = {"url": url, "headers": headers, "auto_connect": True}
        self._save_mcp_json(existing)
        self._sync_from_file()
        ok, err = self.connect(server_id)
        tool_count = len(self._connections.get(server_id, None).tools) if server_id in self._connections else 0
        if ok:
            return True, f"已连接，发现 {tool_count} 个工具"
        return True, f"已注册但连接失败: {err}"

    def remove_server(self, server_id: str) -> bool:
        """disconnect -> 从 mcp.json 移除（回写）-> _sync_from_file -> delete_missing 删 DB 行。"""
        if self.dao.get(server_id) is None and server_id not in self._load_mcp_json():
            return False
        self.disconnect(server_id)
        existing = self._load_mcp_json()
        if server_id in existing:
            del existing[server_id]
            self._save_mcp_json(existing)
        self._sync_from_file()   # delete_missing 删 DB 行
        return True

    def enable_server(self, server_id: str) -> tuple[bool, str]:
        """set_enabled(True) -> connect。"""
        if not self.dao.set_enabled(server_id, True):
            return False, f"MCP 服务 {server_id} 不存在"
        ok, err = self.connect(server_id)
        if ok:
            return True, "已启用并连接"
        return True, f"已启用，但连接失败: {err}"

    def disable_server(self, server_id: str) -> tuple[bool, str]:
        """disconnect -> set_enabled(False)。"""
        self.disconnect(server_id)
        if not self.dao.set_enabled(server_id, False):
            return False, f"MCP 服务 {server_id} 不存在"
        return True, "已禁用"

    # ============ 工具 ============

    def get_langchain_tools(self) -> list:
        """收集所有 status=connected 服务端的工具，包装为 MCPToolWrapper 列表。

        单服务端超 max_tools 截断并 log；全局超 GLOBAL_TOOL_HARD_CAP 停止收集。
        """
        from agent.mcp.tools import MCPToolWrapper, _json_schema_to_pydantic, _sanitize_tool_name

        tools: list = []
        used_names: set[str] = set()
        total = 0
        for server_id, conn in self._connections.items():
            if conn.status != "connected":
                continue
            remote_tools = conn.list_tools()
            if len(remote_tools) > self.max_tools:
                logger.warning(
                    f"MCP 服务 {server_id} 暴露 {len(remote_tools)} 个工具，超上限 {self.max_tools}，"
                    f"仅注册前 {self.max_tools} 个"
                )
                remote_tools = remote_tools[: self.max_tools]
            for t in remote_tools:
                base = f"mcp__{server_id}__{_sanitize_tool_name(t.name)}"
                tool_name = base
                i = 2
                while tool_name in used_names:
                    tool_name = f"{base}_{i}"
                    i += 1
                used_names.add(tool_name)
                desc = f"[MCP/{server_id}] {t.description}"[:1024]
                schema = _json_schema_to_pydantic(t.input_schema, f"{server_id}_{t.name}")
                tools.append(MCPToolWrapper(conn, self, t.name, desc, schema, tool_name))
                total += 1
                if total >= self.GLOBAL_TOOL_HARD_CAP:
                    logger.warning(f"全局 MCP 工具数达硬上限 {self.GLOBAL_TOOL_HARD_CAP}，停止收集")
                    return tools
        return tools

    def list_tools(self, server_id: str) -> list[ToolInfo]:
        """返回某服务端的工具列表（来自连接缓存或 DB tools_cache）。"""
        conn = self._connections.get(server_id)
        if conn and conn.tools:
            return conn.tools
        server = self.dao.get(server_id)
        if server and server.tools_cache:
            return [
                ToolInfo(
                    name=t.get("name", ""),
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}) or {},
                )
                for t in server.tools_cache if isinstance(t, dict)
            ]
        return []

    def call_tool(self, server_id: str, tool_name: str, arguments: dict) -> str:
        """供 /mcp call 与 MCPToolWrapper 调用；调用成功递增 access_count。"""
        conn = self._connections.get(server_id)
        if conn is None or conn.status != "connected":
            return f"❌ MCP 服务 {server_id} 未连接，请执行 /mcp reconnect {server_id}"
        result = conn.call_tool(tool_name, arguments or {})
        if not result.startswith("❌"):
            try:
                self.dao.increment_access(server_id, datetime.now())
            except Exception:
                pass
        return result

    # ============ 查询 ============

    def list_servers(self) -> list[MCPServer]:
        """返回 DB 全部服务端。"""
        return self.dao.list_all()

    def get_server(self, server_id: str) -> MCPServer | None:
        return self.dao.get(server_id)

    def tools_changed(self) -> bool:
        """上次收集后工具集是否变化（供 reload 优化，P2）。v1 恒返回 True（总是重建）。"""
        return True
