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
技能（Skill）数据模型与 DAO

存储在全局唯一的 sqlite 数据库 ``.lemonclaw/lemonclaw.db`` 中，表名为 ``skills``。
仅缓存元数据 + 承载管理状态（enabled / 访问统计）；技能全文（SKILL.md）不入库，
以文件系统为唯一来源。活跃集（_active）为内存 LRU，不入库。
"""

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from dao.db import get_connection


# ============ 模型 ============

@dataclass
class Skill:
    """技能数据模型（元数据 + 管理状态）"""
    name: str                                            # 技能名（frontmatter name，主键）
    version: str = ""                                    # 版本（文件系统同步）
    description: str = ""                                # 描述（文件系统同步）
    tags: list[str] = field(default_factory=list)        # 标签（文件系统同步，JSON 存储）
    emoji: str | None = None                             # emoji（文件系统同步，可空）
    dir_path: str = ""                                   # 技能包目录绝对路径（文件系统同步）
    required_envs: list[str] = field(default_factory=list)  # 所需环境变量（文件系统同步，JSON 存储）
    primary_env: str | None = None                       # 主环境变量（文件系统同步，可空）
    enabled: bool = True                                 # 启用状态（用户可改，管理状态）
    access_count: int = 0                                # 加载次数（运行时统计）
    last_access: datetime | None = None                  # 最近加载时间（运行时统计）
    synced_at: datetime = field(default_factory=datetime.now)  # 最近与文件系统同步时间

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "tags": self.tags,
            "emoji": self.emoji,
            "dir_path": self.dir_path,
            "required_envs": self.required_envs,
            "primary_env": self.primary_env,
            "enabled": self.enabled,
            "access_count": self.access_count,
            "last_access": self.last_access.isoformat() if self.last_access else None,
            "synced_at": self.synced_at.isoformat() if self.synced_at else None,
        }


# ============ DAO ============

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS skills (
    name          TEXT PRIMARY KEY,
    version       TEXT NOT NULL DEFAULT '',
    description   TEXT NOT NULL DEFAULT '',
    tags          TEXT NOT NULL DEFAULT '[]',
    emoji         TEXT,
    dir_path      TEXT NOT NULL,
    required_envs TEXT NOT NULL DEFAULT '[]',
    primary_env   TEXT,
    enabled       INTEGER NOT NULL DEFAULT 1,
    access_count  INTEGER NOT NULL DEFAULT 0,
    last_access   TIMESTAMP,
    synced_at     TIMESTAMP NOT NULL
)
"""

_INDEX_DDL = "CREATE INDEX IF NOT EXISTS idx_skills_enabled ON skills(enabled)"


def ensure_schema() -> None:
    """确保 skills 表与索引存在"""
    with get_connection() as conn:
        conn.execute(_TABLE_DDL)
        conn.execute(_INDEX_DDL)


def _row_to_skill(row: sqlite3.Row) -> Skill:
    """sqlite3.Row -> Skill"""
    tags_raw = row["tags"] or "[]"
    try:
        tags = json.loads(tags_raw) if isinstance(tags_raw, str) else list(tags_raw)
    except (TypeError, ValueError):
        tags = []
    req_raw = row["required_envs"] or "[]"
    try:
        required_envs = json.loads(req_raw) if isinstance(req_raw, str) else list(req_raw)
    except (TypeError, ValueError):
        required_envs = []
    return Skill(
        name=row["name"],
        version=row["version"] or "",
        description=row["description"] or "",
        tags=tags,
        emoji=row["emoji"],
        dir_path=row["dir_path"] or "",
        required_envs=required_envs,
        primary_env=row["primary_env"],
        enabled=bool(row["enabled"]),
        access_count=row["access_count"],
        last_access=row["last_access"],
        synced_at=row["synced_at"],
    )


class SkillDAO:
    """技能 SQL CRUD 操作"""

    def __init__(self):
        ensure_schema()

    # ---- 同步（文件系统 -> DB）----

    def upsert_metadata(self, skill: Skill) -> bool:
        """同步单条元数据（仅更新文件系统列，保留 enabled/access_count/last_access）。
        使用 INSERT ... ON CONFLICT(name) DO UPDATE SET。"""
        sql = """
        INSERT INTO skills (name, version, description, tags, emoji, dir_path,
                            required_envs, primary_env, enabled, access_count, last_access, synced_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0, NULL, ?)
        ON CONFLICT(name) DO UPDATE SET
            version=excluded.version,
            description=excluded.description,
            tags=excluded.tags,
            emoji=excluded.emoji,
            dir_path=excluded.dir_path,
            required_envs=excluded.required_envs,
            primary_env=excluded.primary_env,
            synced_at=excluded.synced_at
        """
        params = (
            skill.name,
            skill.version,
            skill.description,
            json.dumps(skill.tags or [], ensure_ascii=False),
            skill.emoji,
            skill.dir_path,
            json.dumps(skill.required_envs or [], ensure_ascii=False),
            skill.primary_env,
            skill.synced_at,
        )
        with get_connection() as conn:
            conn.execute(sql, params)
        return True

    def delete_missing(self, existing_names: set[str]) -> int:
        """删除文件系统已不存在的技能（name 不在 existing_names 中的行）"""
        with get_connection() as conn:
            if not existing_names:
                cursor = conn.execute("DELETE FROM skills")
                return cursor.rowcount
            placeholders = ",".join("?" * len(existing_names))
            sql = f"DELETE FROM skills WHERE name NOT IN ({placeholders})"
            cursor = conn.execute(sql, tuple(existing_names))
            return cursor.rowcount

    # ---- 管理状态 ----

    def set_enabled(self, name: str, enabled: bool) -> bool:
        """启用/禁用技能，未命中返回 False"""
        with get_connection() as conn:
            cursor = conn.execute(
                "UPDATE skills SET enabled = ? WHERE name = ?",
                (1 if enabled else 0, name),
            )
            return cursor.rowcount > 0

    def increment_access(self, name: str, now: datetime) -> bool:
        """access_count += 1，last_access = now"""
        with get_connection() as conn:
            cursor = conn.execute(
                "UPDATE skills SET access_count = access_count + 1, last_access = ? WHERE name = ?",
                (now, name),
            )
            return cursor.rowcount > 0

    # ---- 读 ----

    def get(self, name: str) -> Skill | None:
        """按 name 获取单个技能"""
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM skills WHERE name = ?", (name,)).fetchone()
            return _row_to_skill(row) if row else None

    def list_all(self, include_disabled: bool = True) -> list[Skill]:
        """列出所有技能（默认包含禁用）"""
        with get_connection() as conn:
            if include_disabled:
                rows = conn.execute("SELECT * FROM skills ORDER BY name").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM skills WHERE enabled = 1 ORDER BY name"
                ).fetchall()
            return [_row_to_skill(r) for r in rows]

    def get_enabled_set(self) -> set[str]:
        """返回所有 enabled=1 的技能名集合（供摘要过滤用）"""
        with get_connection() as conn:
            rows = conn.execute("SELECT name FROM skills WHERE enabled = 1").fetchall()
            return {r["name"] for r in rows}
