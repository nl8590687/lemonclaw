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
SQLite 全局持久化基础工具

整个项目全局只能使用一个 sqlite 数据库文件 ``.lemonclaw/lemonclaw.db``。
所有 DAO 模块都通过 ``get_connection()`` 获取连接，禁止再创建第二个 db 文件。
"""

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


# 默认路径常量
_DEFAULT_DB_DIR = ".lemonclaw"
_DEFAULT_DB_FILENAME = "lemonclaw.db"

_db_lock = threading.RLock()
_global_db_path: Path | None = None


def get_db_path() -> Path:
    """
    获取全局唯一 sqlite 数据库文件路径。

    路径固定为 ``<cwd>/.lemonclaw/lemonclaw.db``。
    如果目录不存在会自动创建。

    Returns:
        数据库文件路径
    """
    global _global_db_path
    if _global_db_path is None:
        with _db_lock:
            if _global_db_path is None:
                lemon_dir = Path.cwd() / _DEFAULT_DB_DIR
                lemon_dir.mkdir(parents=True, exist_ok=True)
                _global_db_path = lemon_dir / _DEFAULT_DB_FILENAME
    return _global_db_path


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """
    获取全局 sqlite 数据库连接（context manager）。

    - 自动开启 WAL 模式以支持多线程读写
    - 行工厂为 ``sqlite3.Row``
    - 退出 ``with`` 时如果未抛异常则 commit，否则 rollback
    - ``check_same_thread=False`` 允许跨线程使用（调度器线程与主线程都可能访问）

    示例::

        with get_connection() as conn:
            conn.execute("SELECT 1")

    Yields:
        sqlite3.Connection
    """
    conn = sqlite3.connect(
        get_db_path(),
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        check_same_thread=False,
        timeout=30.0,
    )
    conn.row_factory = sqlite3.Row
    try:
        # 每次连接都设置 PRAGMA（journal_mode 是持久化设置，重复设置无害）
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def execute(sql: str, params: tuple | list | dict = ()) -> int:
    """
    执行一条 SQL（INSERT/UPDATE/DELETE/DDL），返回受影响的行数。
    """
    with get_connection() as conn:
        cursor = conn.execute(sql, params)
        return cursor.rowcount


def query_one(sql: str, params: tuple | list | dict = ()) -> sqlite3.Row | None:
    """
    查询单行，返回 ``sqlite3.Row`` 或 ``None``。
    """
    with get_connection() as conn:
        cursor = conn.execute(sql, params)
        return cursor.fetchone()


def query_all(sql: str, params: tuple | list | dict = ()) -> list[sqlite3.Row]:
    """
    查询多行，返回 ``sqlite3.Row`` 列表。
    """
    with get_connection() as conn:
        cursor = conn.execute(sql, params)
        return cursor.fetchall()