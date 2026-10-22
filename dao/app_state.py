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
应用运行时状态 KV 存储

存储在全局唯一的 sqlite 数据库 ``.lemonclaw/lemonclaw.db`` 中，
表名为 ``app_state``。用于保存需要跨重启保留的轻量状态，
例如自动绑定的飞书用户 ``open_id``。
"""

from dao.db import get_connection


_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS app_state (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL
)
"""

_schema_ready = False


def ensure_schema() -> None:
    """确保 app_state 表存在（幂等）"""
    global _schema_ready
    if _schema_ready:
        return
    with get_connection() as conn:
        conn.execute(_TABLE_DDL)
    _schema_ready = True


def get_state(key: str) -> str | None:
    """读取状态值；不存在返回 None"""
    ensure_schema()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM app_state WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else None


def set_state(key: str, value: str) -> None:
    """写入/覆盖状态值"""
    ensure_schema()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO app_state (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (key, value),
        )


def get_or_set_state(key: str, value: str) -> str:
    """原子地读取或写入：已有值返回已有值，否则写入 value 并返回"""
    ensure_schema()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO app_state (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO NOTHING
            """,
            (key, value),
        )
        row = conn.execute(
            "SELECT value FROM app_state WHERE key = ?", (key,)
        ).fetchone()
    return row["value"]


def delete_state(key: str) -> None:
    """删除状态值"""
    ensure_schema()
    with get_connection() as conn:
        conn.execute("DELETE FROM app_state WHERE key = ?", (key,))
