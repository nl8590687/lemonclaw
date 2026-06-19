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
定时任务（Cron Task）数据模型与 DAO

存储在全局唯一的 sqlite 数据库 ``.lemonclaw/lemonclaw.db`` 中，
表名为 ``cron_tasks``。
"""

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from dao.db import get_connection


# ============ 模型 ============

@dataclass
class CronTask:
    """定时任务数据模型"""
    task_id: str
    prompt: str
    cron_expression: str
    prompt_original: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    last_run_at: datetime | None = None
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "prompt": self.prompt,
            "prompt_original": self.prompt_original,
            "cron_expression": self.cron_expression,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "enabled": self.enabled,
            "metadata": self.metadata,
        }


# ============ DAO ============

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS cron_tasks (
    task_id          TEXT PRIMARY KEY,
    prompt           TEXT NOT NULL,
    prompt_original  TEXT,
    cron_expression  TEXT NOT NULL,
    created_at       TIMESTAMP NOT NULL,
    updated_at       TIMESTAMP NOT NULL,
    last_run_at      TIMESTAMP,
    enabled          INTEGER NOT NULL DEFAULT 1,
    metadata         TEXT NOT NULL DEFAULT '{}'
)
"""

_INDEX_DDL = "CREATE INDEX IF NOT EXISTS idx_cron_enabled ON cron_tasks(enabled)"


def ensure_schema() -> None:
    """确保 cron_tasks 表与索引存在"""
    with get_connection() as conn:
        conn.execute(_TABLE_DDL)
        conn.execute(_INDEX_DDL)


def _row_to_task(row: sqlite3.Row) -> CronTask:
    """sqlite3.Row -> CronTask"""
    metadata_raw = row["metadata"] or "{}"
    try:
        metadata = json.loads(metadata_raw) if isinstance(metadata_raw, str) else dict(metadata_raw)
    except (TypeError, ValueError):
        metadata = {}
    return CronTask(
        task_id=row["task_id"],
        prompt=row["prompt"],
        prompt_original=row["prompt_original"] or "",
        cron_expression=row["cron_expression"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_run_at=row["last_run_at"],
        enabled=bool(row["enabled"]),
        metadata=metadata,
    )


class CronTaskDAO:
    """定时任务 SQL CRUD 操作"""

    def __init__(self):
        ensure_schema()

    # ---- 写 ----

    def insert(self, task: CronTask) -> bool:
        """插入新任务，主键冲突返回 False"""
        sql = """
        INSERT INTO cron_tasks (
            task_id, prompt, prompt_original, cron_expression,
            created_at, updated_at, last_run_at, enabled, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            task.task_id,
            task.prompt,
            task.prompt_original or task.prompt,
            task.cron_expression,
            task.created_at,
            task.updated_at,
            task.last_run_at,
            1 if task.enabled else 0,
            json.dumps(task.metadata or {}, ensure_ascii=False),
        )
        try:
            with get_connection() as conn:
                conn.execute(sql, params)
            return True
        except sqlite3.IntegrityError:
            return False

    def update(self, task: CronTask) -> bool:
        """更新已有任务，未命中返回 False"""
        sql = """
        UPDATE cron_tasks
           SET prompt = ?,
               prompt_original = ?,
               cron_expression = ?,
               updated_at = ?,
               last_run_at = ?,
               enabled = ?,
               metadata = ?
         WHERE task_id = ?
        """
        params = (
            task.prompt,
            task.prompt_original or task.prompt,
            task.cron_expression,
            task.updated_at,
            task.last_run_at,
            1 if task.enabled else 0,
            json.dumps(task.metadata or {}, ensure_ascii=False),
            task.task_id,
        )
        with get_connection() as conn:
            cursor = conn.execute(sql, params)
            return cursor.rowcount > 0

    def update_last_run(self, task_id: str, last_run_at: datetime) -> bool:
        """仅更新最后执行时间"""
        sql = """
        UPDATE cron_tasks
           SET last_run_at = ?,
               updated_at = ?
         WHERE task_id = ?
        """
        with get_connection() as conn:
            cursor = conn.execute(sql, (last_run_at, datetime.now(), task_id))
            return cursor.rowcount > 0

    def delete(self, task_id: str) -> bool:
        """删除任务"""
        with get_connection() as conn:
            cursor = conn.execute("DELETE FROM cron_tasks WHERE task_id = ?", (task_id,))
            return cursor.rowcount > 0

    # ---- 读 ----

    def get(self, task_id: str) -> CronTask | None:
        """按 ID 获取单个任务"""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM cron_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            return _row_to_task(row) if row else None

    def list_all(self, include_disabled: bool = True) -> list[CronTask]:
        """列出所有任务（默认包含禁用）"""
        with get_connection() as conn:
            if include_disabled:
                rows = conn.execute(
                    "SELECT * FROM cron_tasks ORDER BY created_at DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM cron_tasks WHERE enabled = 1 ORDER BY created_at DESC"
                ).fetchall()
            return [_row_to_task(r) for r in rows]