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
LemonClaw 数据访问层

整个项目只允许使用一个 sqlite 数据库文件 ``.lemonclaw/lemonclaw.db``，
所有 DAO 通过 ``dao.db.get_connection`` 共享该连接。
"""

from dao.db import get_connection, get_db_path, execute, query_one, query_all
from dao.cron_task import CronTask, CronTaskDAO, ensure_schema as ensure_cron_schema
from dao.memory import (
    MemorySession, MemoryMessage, MemoryChunk, CoreMemory,
    MemorySessionDAO, MemoryMessageDAO, MemoryChunkDAO, CoreMemoryDAO,
    ensure_memory_schema,
)
from dao.skill import Skill, SkillDAO, ensure_schema as ensure_skill_schema

__all__ = [
    "get_connection",
    "get_db_path",
    "execute",
    "query_one",
    "query_all",
    "CronTask",
    "CronTaskDAO",
    "ensure_cron_schema",
    "MemorySession",
    "MemoryMessage",
    "MemoryChunk",
    "CoreMemory",
    "MemorySessionDAO",
    "MemoryMessageDAO",
    "MemoryChunkDAO",
    "CoreMemoryDAO",
    "ensure_memory_schema",
    "Skill",
    "SkillDAO",
    "ensure_skill_schema",
]