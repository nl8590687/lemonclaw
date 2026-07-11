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
持久化记忆数据模型与 DAO

存储在全局唯一的 sqlite 数据库 ``.lemonclaw/lemonclaw.db`` 中，共 4 张表：
- ``memory_sessions``  会话（短期记忆载体）
- ``memory_messages``  原始对话消息（短期记忆）
- ``memory_chunks``    长期记忆块
- ``core_memory``      核心记忆（KV）

全部通过 ``dao.db.get_connection`` 共享同一个连接，禁止再创建第二个 db 文件。
"""

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from dao.db import get_connection


# ============ 模型 ============

@dataclass
class MemorySession:
    """会话数据模型"""
    id: int | None
    start_time: datetime
    end_time: datetime | None = None
    summary: str | None = None
    token_count: int = 0
    is_archived: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "summary": self.summary,
            "token_count": self.token_count,
            "is_archived": self.is_archived,
        }


@dataclass
class MemoryMessage:
    """原始对话消息模型"""
    id: int | None
    session_id: int
    role: str            # "human" | "ai" | "tool" | "system"
    content: str
    timestamp: datetime
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_call_id: str | None = None   # 工具调用 ID，/resume 重建 tool_calls 链路用
    token_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "tool_call_id": self.tool_call_id,
            "token_count": self.token_count,
        }


@dataclass
class MemoryChunk:
    """长期记忆块模型"""
    id: int | None
    chunk_type: str      # "summary" | "fact" | "decision" | "skill" | "issue"
    title: str
    content: str
    created_at: datetime
    keywords: list[str] = field(default_factory=list)
    source_session_id: int | None = None
    importance: int = 5  # 1-10
    access_count: int = 0
    last_access: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "chunk_type": self.chunk_type,
            "title": self.title,
            "content": self.content,
            "keywords": self.keywords,
            "source_session_id": self.source_session_id,
            "importance": self.importance,
            "access_count": self.access_count,
            "last_access": self.last_access.isoformat() if self.last_access else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class CoreMemory:
    """核心记忆（KV）模型"""
    memory_type: str     # "fact" | "preference" | "project" | "persona" | "skill"
    key: str
    value: str
    created_at: datetime
    updated_at: datetime
    description: str | None = None
    is_user_edited: bool = False
    id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "memory_type": self.memory_type,
            "key": self.key,
            "value": self.value,
            "description": self.description,
            "is_user_edited": self.is_user_edited,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ============ Schema ============

_TABLE_DDL_SESSIONS = """
CREATE TABLE IF NOT EXISTS memory_sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time   TIMESTAMP NOT NULL,
    end_time     TIMESTAMP,
    summary      TEXT,
    token_count  INTEGER NOT NULL DEFAULT 0,
    is_archived  INTEGER NOT NULL DEFAULT 0
)
"""

_TABLE_DDL_MESSAGES = """
CREATE TABLE IF NOT EXISTS memory_messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   INTEGER NOT NULL,
    role         TEXT NOT NULL,
    content      TEXT NOT NULL,
    tool_name    TEXT,
    tool_args    TEXT,
    tool_call_id TEXT,
    timestamp    TIMESTAMP NOT NULL,
    token_count  INTEGER,
    FOREIGN KEY (session_id) REFERENCES memory_sessions(id) ON DELETE CASCADE
)
"""

_TABLE_DDL_CHUNKS = """
CREATE TABLE IF NOT EXISTS memory_chunks (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_type         TEXT NOT NULL,
    title              TEXT NOT NULL,
    content            TEXT NOT NULL,
    keywords           TEXT,
    source_session_id  INTEGER,
    importance         INTEGER NOT NULL DEFAULT 5,
    access_count       INTEGER NOT NULL DEFAULT 0,
    last_access        TIMESTAMP,
    created_at         TIMESTAMP NOT NULL,
    embedding          BLOB,
    FOREIGN KEY (source_session_id) REFERENCES memory_sessions(id) ON DELETE SET NULL
)
"""

_TABLE_DDL_CORE = """
CREATE TABLE IF NOT EXISTS core_memory (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_type    TEXT NOT NULL,
    key            TEXT NOT NULL,
    value          TEXT NOT NULL,
    description    TEXT,
    is_user_edited INTEGER NOT NULL DEFAULT 0,
    created_at     TIMESTAMP NOT NULL,
    updated_at     TIMESTAMP NOT NULL,
    UNIQUE(memory_type, key)
)
"""

_INDEX_DDL_LIST = [
    "CREATE INDEX IF NOT EXISTS idx_memory_sessions_start ON memory_sessions(start_time DESC)",
    "CREATE INDEX IF NOT EXISTS idx_memory_messages_session ON memory_messages(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_memory_chunks_type ON memory_chunks(chunk_type)",
    "CREATE INDEX IF NOT EXISTS idx_memory_chunks_importance ON memory_chunks(importance DESC)",
    "CREATE INDEX IF NOT EXISTS idx_core_memory_type_key ON core_memory(memory_type, key)",
]


def ensure_memory_schema() -> None:
    """确保 4 张记忆表与索引存在（幂等）。"""
    with get_connection() as conn:
        conn.execute(_TABLE_DDL_SESSIONS)
        conn.execute(_TABLE_DDL_MESSAGES)
        conn.execute(_TABLE_DDL_CHUNKS)
        conn.execute(_TABLE_DDL_CORE)
        for idx in _INDEX_DDL_LIST:
            conn.execute(idx)


# ============ 行 -> 模型 ============

def _row_to_session(row: sqlite3.Row) -> MemorySession:
    return MemorySession(
        id=row["id"],
        start_time=row["start_time"],
        end_time=row["end_time"],
        summary=row["summary"],
        token_count=row["token_count"],
        is_archived=bool(row["is_archived"]),
    )


def _row_to_message(row: sqlite3.Row) -> MemoryMessage:
    tool_args_raw = row["tool_args"]
    try:
        tool_args = json.loads(tool_args_raw) if tool_args_raw else None
    except (TypeError, ValueError):
        tool_args = None
    return MemoryMessage(
        id=row["id"],
        session_id=row["session_id"],
        role=row["role"],
        content=row["content"],
        timestamp=row["timestamp"],
        tool_name=row["tool_name"],
        tool_args=tool_args,
        tool_call_id=row["tool_call_id"],
        token_count=row["token_count"],
    )


def _row_to_chunk(row: sqlite3.Row) -> MemoryChunk:
    keywords_raw = row["keywords"]
    try:
        keywords = json.loads(keywords_raw) if keywords_raw else []
    except (TypeError, ValueError):
        keywords = []
    return MemoryChunk(
        id=row["id"],
        chunk_type=row["chunk_type"],
        title=row["title"],
        content=row["content"],
        keywords=keywords,
        source_session_id=row["source_session_id"],
        importance=row["importance"],
        access_count=row["access_count"],
        last_access=row["last_access"],
        created_at=row["created_at"],
    )


def _row_to_core(row: sqlite3.Row) -> CoreMemory:
    return CoreMemory(
        id=row["id"],
        memory_type=row["memory_type"],
        key=row["key"],
        value=row["value"],
        description=row["description"],
        is_user_edited=bool(row["is_user_edited"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ============ DAO ============

class MemorySessionDAO:
    """会话存储 SQL CRUD"""

    def __init__(self):
        ensure_memory_schema()

    def create(self, start_time: datetime | None = None) -> int:
        """创建新会话，返回 session_id"""
        start_time = start_time or datetime.now()
        sql = "INSERT INTO memory_sessions (start_time) VALUES (?)"
        with get_connection() as conn:
            cursor = conn.execute(sql, (start_time,))
            return cursor.lastrowid

    def end_session(self, session_id: int, summary: str | None, token_count: int) -> bool:
        """结束会话：写入 end_time / summary / token_count"""
        sql = """
        UPDATE memory_sessions
           SET end_time = ?,
               summary = ?,
               token_count = ?
         WHERE id = ?
        """
        with get_connection() as conn:
            cursor = conn.execute(sql, (datetime.now(), summary, token_count, session_id))
            return cursor.rowcount > 0

    def mark_archived(self, session_id: int) -> bool:
        """标记会话已归档到长期记忆"""
        sql = "UPDATE memory_sessions SET is_archived = 1 WHERE id = ?"
        with get_connection() as conn:
            cursor = conn.execute(sql, (session_id,))
            return cursor.rowcount > 0

    def reopen(self, session_id: int) -> bool:
        """重开会话（/resume 原地续写）：清空 end_time、is_archived 置 0"""
        sql = "UPDATE memory_sessions SET end_time = NULL, is_archived = 0 WHERE id = ?"
        with get_connection() as conn:
            cursor = conn.execute(sql, (session_id,))
            return cursor.rowcount > 0

    def get(self, session_id: int) -> MemorySession | None:
        """按 id 获取单个会话"""
        sql = "SELECT * FROM memory_sessions WHERE id = ?"
        with get_connection() as conn:
            row = conn.execute(sql, (session_id,)).fetchone()
            return _row_to_session(row) if row else None

    def list_recent(self, limit: int = 10) -> list[MemorySession]:
        """列出最近的会话（按 start_time 倒序）"""
        sql = "SELECT * FROM memory_sessions ORDER BY start_time DESC LIMIT ?"
        with get_connection() as conn:
            rows = conn.execute(sql, (limit,)).fetchall()
            return [_row_to_session(r) for r in rows]

    def recent_archived(self, exclude_id: int | None = None) -> MemorySession | None:
        """最近一次已结束（is_archived=1）会话，可排除指定 id；供 /resume 无参数使用"""
        if exclude_id is not None:
            sql = ("SELECT * FROM memory_sessions WHERE is_archived = 1 AND id != ? "
                   "ORDER BY end_time DESC LIMIT 1")
            params: tuple = (exclude_id,)
        else:
            sql = ("SELECT * FROM memory_sessions WHERE is_archived = 1 "
                   "ORDER BY end_time DESC LIMIT 1")
            params = ()
        with get_connection() as conn:
            row = conn.execute(sql, params).fetchone()
            return _row_to_session(row) if row else None


class MemoryMessageDAO:
    """原始消息存储 SQL CRUD"""

    def __init__(self):
        ensure_memory_schema()

    def add(self, msg: MemoryMessage) -> int:
        """添加一条消息，返回消息 id"""
        sql = """
        INSERT INTO memory_messages
            (session_id, role, content, tool_name, tool_args, tool_call_id, timestamp, token_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            msg.session_id,
            msg.role,
            msg.content,
            msg.tool_name,
            json.dumps(msg.tool_args, ensure_ascii=False) if msg.tool_args else None,
            msg.tool_call_id,
            msg.timestamp or datetime.now(),
            msg.token_count,
        )
        with get_connection() as conn:
            cursor = conn.execute(sql, params)
            return cursor.lastrowid

    def list_by_session(self, session_id: int) -> list[MemoryMessage]:
        """获取会话的全部消息（按 id 升序）"""
        sql = "SELECT * FROM memory_messages WHERE session_id = ? ORDER BY id ASC"
        with get_connection() as conn:
            rows = conn.execute(sql, (session_id,)).fetchall()
            return [_row_to_message(r) for r in rows]


class MemoryChunkDAO:
    """长期记忆块存储 SQL CRUD"""

    def __init__(self):
        ensure_memory_schema()

    def add(self, chunk: MemoryChunk) -> int:
        """添加记忆块，返回 chunk id"""
        sql = """
        INSERT INTO memory_chunks
            (chunk_type, title, content, keywords, source_session_id,
             importance, access_count, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 0, ?)
        """
        params = (
            chunk.chunk_type,
            chunk.title,
            chunk.content,
            json.dumps(chunk.keywords, ensure_ascii=False) if chunk.keywords else None,
            chunk.source_session_id,
            chunk.importance,
            chunk.created_at or datetime.now(),
        )
        with get_connection() as conn:
            cursor = conn.execute(sql, params)
            return cursor.lastrowid

    def get(self, chunk_id: int) -> MemoryChunk | None:
        """按 id 获取单个记忆块"""
        sql = "SELECT * FROM memory_chunks WHERE id = ?"
        with get_connection() as conn:
            row = conn.execute(sql, (chunk_id,)).fetchone()
            return _row_to_chunk(row) if row else None

    def list_all(self, limit: int = 100) -> list[MemoryChunk]:
        """列出记忆块（按重要性倒序、创建时间倒序）"""
        sql = "SELECT * FROM memory_chunks ORDER BY importance DESC, created_at DESC LIMIT ?"
        with get_connection() as conn:
            rows = conn.execute(sql, (limit,)).fetchall()
            return [_row_to_chunk(r) for r in rows]

    def update_access(self, chunk_id: int, now: datetime | None = None) -> bool:
        """更新访问计数与最后访问时间"""
        sql = "UPDATE memory_chunks SET access_count = access_count + 1, last_access = ? WHERE id = ?"
        with get_connection() as conn:
            cursor = conn.execute(sql, (now or datetime.now(), chunk_id))
            return cursor.rowcount > 0

    def delete(self, chunk_id: int) -> bool:
        """删除记忆块"""
        sql = "DELETE FROM memory_chunks WHERE id = ?"
        with get_connection() as conn:
            cursor = conn.execute(sql, (chunk_id,))
            return cursor.rowcount > 0


class CoreMemoryDAO:
    """核心记忆（KV）存储 SQL CRUD"""

    def __init__(self):
        ensure_memory_schema()

    def upsert(self, mem: CoreMemory) -> bool:
        """插入或更新核心记忆（按 (memory_type, key) 去重）"""
        now = datetime.now()
        sql = """
        INSERT INTO core_memory
            (memory_type, key, value, description, is_user_edited, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(memory_type, key)
        DO UPDATE SET value = ?, description = ?, is_user_edited = ?, updated_at = ?
        """
        params = (
            mem.memory_type, mem.key, mem.value, mem.description,
            1 if mem.is_user_edited else 0, mem.created_at or now, mem.updated_at or now,
            mem.value, mem.description, 1 if mem.is_user_edited else 0, now,
        )
        with get_connection() as conn:
            conn.execute(sql, params)
            return True

    def get(self, memory_type: str, key: str) -> CoreMemory | None:
        """按 (type, key) 获取单条核心记忆"""
        sql = "SELECT * FROM core_memory WHERE memory_type = ? AND key = ?"
        with get_connection() as conn:
            row = conn.execute(sql, (memory_type, key)).fetchone()
            return _row_to_core(row) if row else None

    def delete(self, memory_type: str, key: str) -> bool:
        """删除单条核心记忆"""
        sql = "DELETE FROM core_memory WHERE memory_type = ? AND key = ?"
        with get_connection() as conn:
            cursor = conn.execute(sql, (memory_type, key))
            return cursor.rowcount > 0

    def list_all(self, memory_type: str | None = None) -> list[CoreMemory]:
        """列出核心记忆（可选按类型过滤，按 memory_type, key 排序）"""
        with get_connection() as conn:
            if memory_type:
                rows = conn.execute(
                    "SELECT * FROM core_memory WHERE memory_type = ? ORDER BY key",
                    (memory_type,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM core_memory ORDER BY memory_type, key"
                ).fetchall()
            return [_row_to_core(r) for r in rows]
