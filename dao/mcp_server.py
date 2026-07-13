#!/usr/bin/env python
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
MCP 服务端（Model Context Protocol）数据模型与 DAO

存储在全局唯一的 sqlite 数据库 ``.lemonclaw/lemonclaw.db`` 中，
表名为 ``mcp_servers``。

服务端定义的唯一来源是 ``.lemonclaw/mcp.json``（顶层以 ``server_id`` 为 key）；
本表镜像定义列 + 持有 DB 管理状态（``enabled``）+ 运行时统计/缓存。
对齐 ``dao/cron_task.py`` 与 ``dao/skill.py`` 的模式。
"""

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from dao.db import get_connection


# ============ 模型 ============

@dataclass
class MCPServer:
    """MCP 服务端数据模型（配置镜像 + 协商缓存 + 状态/统计）"""
    server_id: str                                    # 用户别名（主键，同时作工具名前缀）
    url: str                                           # streamable HTTP 端点
    headers: dict[str, str] = field(default_factory=dict)  # 额外请求头（含认证密钥，JSON 存储）
    enabled: bool = True                              # 启用状态（DB 管理状态，跨重启保留；不在 mcp.json）
    auto_connect: bool = True                         # 启动时是否自动连接（来自 mcp.json，文件同步列）
    # ---- 协商缓存（连接成功后同步）----
    protocol_version: str = ""                        # 协商的协议版本
    server_info: dict[str, Any] = field(default_factory=dict)  # serverInfo（name/version）
    tools_cache: list[dict[str, Any]] = field(default_factory=list)  # 已发现工具列表
    tool_count: int = 0                               # 工具数（冗余，便于 SQL 直查）
    # ---- 状态/统计 ----
    status: str = "disconnected"                      # disconnected/connecting/connected/error
    last_error: str | None = None                     # 最近一次连接/调用错误
    access_count: int = 0                             # 工具调用累计次数
    last_access: datetime | None = None               # 最近一次工具调用时间
    last_connected_at: datetime | None = None         # 最近一次连接成功时间
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "server_id": self.server_id,
            "url": self.url,
            "headers": self.headers,
            "enabled": self.enabled,
            "auto_connect": self.auto_connect,
            "protocol_version": self.protocol_version,
            "server_info": self.server_info,
            "tools_cache": self.tools_cache,
            "tool_count": self.tool_count,
            "status": self.status,
            "last_error": self.last_error,
            "access_count": self.access_count,
            "last_access": self.last_access.isoformat() if self.last_access else None,
            "last_connected_at": self.last_connected_at.isoformat() if self.last_connected_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ============ Schema ============

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS mcp_servers (
    server_id        TEXT PRIMARY KEY,
    url              TEXT NOT NULL,
    headers          TEXT NOT NULL DEFAULT '{}',
    enabled          INTEGER NOT NULL DEFAULT 1,
    auto_connect     INTEGER NOT NULL DEFAULT 1,
    protocol_version TEXT NOT NULL DEFAULT '',
    server_info      TEXT NOT NULL DEFAULT '{}',
    tools_cache      TEXT NOT NULL DEFAULT '[]',
    tool_count       INTEGER NOT NULL DEFAULT 0,
    status           TEXT NOT NULL DEFAULT 'disconnected',
    last_error       TEXT,
    access_count     INTEGER NOT NULL DEFAULT 0,
    last_access      TIMESTAMP,
    last_connected_at TIMESTAMP,
    created_at       TIMESTAMP NOT NULL,
    updated_at       TIMESTAMP NOT NULL
)
"""

_INDEX_DDL = "CREATE INDEX IF NOT EXISTS idx_mcp_enabled ON mcp_servers(enabled)"


def ensure_mcp_schema() -> None:
    """确保 mcp_servers 表与索引存在（幂等）。"""
    with get_connection() as conn:
        conn.execute(_TABLE_DDL)
        conn.execute(_INDEX_DDL)


# ============ 辅助 ============

def _loads_json(raw: Any, default: Any) -> Any:
    """安全 JSON 解析：字符串 -> 对象；解析失败/非字符串 -> default。"""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return default
    if isinstance(raw, (dict, list)):
        return raw
    return default


def _row_to_server(row: sqlite3.Row) -> MCPServer:
    """sqlite3.Row -> MCPServer"""
    return MCPServer(
        server_id=row["server_id"],
        url=row["url"],
        headers=_loads_json(row["headers"], {}) or {},
        enabled=bool(row["enabled"]),
        auto_connect=bool(row["auto_connect"]),
        protocol_version=row["protocol_version"] or "",
        server_info=_loads_json(row["server_info"], {}) or {},
        tools_cache=_loads_json(row["tools_cache"], []) or [],
        tool_count=row["tool_count"],
        status=row["status"],
        last_error=row["last_error"],
        access_count=row["access_count"],
        last_access=row["last_access"],
        last_connected_at=row["last_connected_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ============ DAO ============

class MCPServerDAO:
    """MCP 服务端 SQL CRUD 操作"""

    def __init__(self):
        ensure_mcp_schema()

    # ---- 文件同步（mcp.json -> DB，对齐 Skills upsert_metadata）----

    def upsert_metadata(self, server: MCPServer) -> bool:
        """upsert 定义列（server_id/url/headers/auto_connect），保留 enabled/统计/缓存。

        使用 INSERT ... ON CONFLICT(server_id) DO UPDATE SET 仅覆盖定义列，
        显式不更新 enabled/access_count/last_access/缓存列。
        """
        sql = """
        INSERT INTO mcp_servers (server_id, url, headers, auto_connect, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(server_id) DO UPDATE SET
            url = excluded.url,
            headers = excluded.headers,
            auto_connect = excluded.auto_connect,
            updated_at = excluded.updated_at
        """
        now = datetime.now()
        params = (
            server.server_id,
            server.url,
            json.dumps(server.headers or {}, ensure_ascii=False),
            1 if server.auto_connect else 0,
            now,
            now,
        )
        with get_connection() as conn:
            conn.execute(sql, params)
        return True

    def delete_missing(self, existing_ids: set[str]) -> int:
        """删除 mcp.json 已不存在的服务端（server_id 不在 existing_ids 中的行）。"""
        with get_connection() as conn:
            if not existing_ids:
                cursor = conn.execute("DELETE FROM mcp_servers")
                return cursor.rowcount
            placeholders = ",".join("?" for _ in existing_ids)
            cursor = conn.execute(
                f"DELETE FROM mcp_servers WHERE server_id NOT IN ({placeholders})",
                tuple(existing_ids),
            )
            return cursor.rowcount

    # ---- 管理 / 运行时写 ----

    def set_enabled(self, server_id: str, enabled: bool) -> bool:
        """启用/禁用，未命中返回 False。"""
        with get_connection() as conn:
            cursor = conn.execute(
                "UPDATE mcp_servers SET enabled = ?, updated_at = ? WHERE server_id = ?",
                (1 if enabled else 0, datetime.now(), server_id),
            )
            return cursor.rowcount > 0

    def sync_after_connect(self, server_id: str, protocol_version: str,
                           server_info: dict, tools_cache: list, tool_count: int,
                           status: str, last_connected_at: datetime) -> bool:
        """连接成功后同步协商缓存列 + 状态（不触碰 enabled/统计）。"""
        sql = """
        UPDATE mcp_servers
           SET protocol_version = ?,
               server_info = ?,
               tools_cache = ?,
               tool_count = ?,
               status = ?,
               last_connected_at = ?,
               updated_at = ?
         WHERE server_id = ?
        """
        params = (
            protocol_version,
            json.dumps(server_info or {}, ensure_ascii=False),
            json.dumps(tools_cache or [], ensure_ascii=False),
            tool_count,
            status,
            last_connected_at,
            datetime.now(),
            server_id,
        )
        with get_connection() as conn:
            cursor = conn.execute(sql, params)
            return cursor.rowcount > 0

    def set_status(self, server_id: str, status: str, last_error: str | None = None) -> bool:
        """仅更新运行时状态与错误。"""
        with get_connection() as conn:
            cursor = conn.execute(
                "UPDATE mcp_servers SET status = ?, last_error = ?, updated_at = ? WHERE server_id = ?",
                (status, last_error, datetime.now(), server_id),
            )
            return cursor.rowcount > 0

    def increment_access(self, server_id: str, now: datetime) -> bool:
        """access_count += 1，last_access = now。"""
        with get_connection() as conn:
            cursor = conn.execute(
                "UPDATE mcp_servers SET access_count = access_count + 1, last_access = ?, updated_at = ? "
                "WHERE server_id = ?",
                (now, datetime.now(), server_id),
            )
            return cursor.rowcount > 0

    def delete(self, server_id: str) -> bool:
        """删除服务端。"""
        with get_connection() as conn:
            cursor = conn.execute("DELETE FROM mcp_servers WHERE server_id = ?", (server_id,))
            return cursor.rowcount > 0

    # ---- 读 ----

    def get(self, server_id: str) -> MCPServer | None:
        """按 ID 获取单个服务端。"""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM mcp_servers WHERE server_id = ?", (server_id,)
            ).fetchone()
            return _row_to_server(row) if row else None

    def list_all(self, include_disabled: bool = True) -> list[MCPServer]:
        """列出所有服务端（默认包含禁用）。"""
        with get_connection() as conn:
            if include_disabled:
                rows = conn.execute(
                    "SELECT * FROM mcp_servers ORDER BY created_at ASC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM mcp_servers WHERE enabled = 1 ORDER BY created_at ASC"
                ).fetchall()
            return [_row_to_server(r) for r in rows]

    def list_auto_connect(self) -> list[MCPServer]:
        """返回 enabled=1 且 auto_connect=1 的服务端（供启动连接）。"""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM mcp_servers WHERE enabled = 1 AND auto_connect = 1 ORDER BY created_at ASC"
            ).fetchall()
            return [_row_to_server(r) for r in rows]
