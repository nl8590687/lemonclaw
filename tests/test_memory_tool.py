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
记忆工具单元测试（recall_memory / remember / forget / list_memory / add_memory_chunk）
"""

import tempfile
import unittest
from pathlib import Path

import agent.memory as _am
import dao.db as _db
from agent.memory import get_memory_manager
from agent.tools.memory_tool import create_memory_tools


class _TempDbTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        _db._global_db_path = Path(self._tmpdir) / "t.db"
        _am._global_memory_manager = None
        self.mgr = get_memory_manager()
        self.tools = {t.name: t for t in create_memory_tools(self.mgr)}

    def tearDown(self):
        _db._global_db_path = None


class TestMemoryTools(_TempDbTestCase):
    def test_tool_names(self):
        self.assertEqual(
            sorted(self.tools),
            ["add_memory_chunk", "forget", "list_memory", "recall_memory", "remember"],
        )

    def test_remember_list_forget(self):
        self.assertIn("已记住", self.tools["remember"].invoke(
            {"key": "lang", "value": "中文", "memory_type": "preference"}))
        self.assertIn("lang: 中文", self.tools["list_memory"].invoke({}))
        self.assertIn("已删除", self.tools["forget"].invoke(
            {"memory_type": "preference", "key": "lang"}))
        self.assertEqual(self.tools["list_memory"].invoke({}), "当前没有核心记忆")

    def test_add_chunk_and_recall(self):
        self.tools["add_memory_chunk"].invoke({
            "chunk_type": "fact", "title": "数据库连接",
            "content": "项目使用 sqlite 单库管理",
            "keywords": "数据库,sqlite", "importance": 8,
        })
        result = self.tools["recall_memory"].invoke({"query": "数据库"})
        self.assertIn("数据库连接", result)

    def test_recall_no_match(self):
        result = self.tools["recall_memory"].invoke({"query": "不存在的词xyz"})
        self.assertIn("未找到", result)


if __name__ == "__main__":
    unittest.main()
