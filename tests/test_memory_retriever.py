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
retriever 单元测试（分词、TF-IDF 相似度、MemorySearcher 加权）

纯函数测试，不依赖 LLM、不写库。
"""

import unittest
from datetime import datetime, timedelta

from agent.memory.retriever import ChineseTokenizer, MemorySearcher, TFIDFRetriever
from dao.memory import MemoryChunk


class TestChineseTokenizer(unittest.TestCase):
    def test_tokenize_chinese_and_english(self):
        tok = ChineseTokenizer()
        tokens = tok.tokenize("SQLite 数据库连接")
        self.assertIn("sqlite", tokens)
        # jieba 可用时，「数据库」应作为一个词
        if tok.available:
            self.assertIn("数据库", tokens)

    def test_empty(self):
        self.assertEqual(ChineseTokenizer().tokenize(""), [])


class TestTFIDFRetriever(unittest.TestCase):
    def test_search_ranks_relevant_doc_first(self):
        r = TFIDFRetriever()
        r.add_document("项目使用 sqlite 管理数据库连接", {"tag": "db"})
        r.add_document("cron 模块负责定时任务调度", {"tag": "cron"})
        res = r.search("数据库连接", top_k=2)
        self.assertGreaterEqual(len(res), 1)
        self.assertEqual(res[0][2]["tag"], "db")

    def test_empty_retriever(self):
        self.assertEqual(TFIDFRetriever().search("x"), [])

    def test_no_match_returns_empty(self):
        r = TFIDFRetriever()
        r.add_document("数据库", {})
        self.assertEqual(r.search("xyzxyz"), [])


class TestMemorySearcher(unittest.TestCase):
    def _mk(self, cid: int, title: str, content: str, importance: int = 5, days_ago: int = 0):
        return MemoryChunk(
            id=cid, chunk_type="fact", title=title, content=content,
            created_at=datetime.now() - timedelta(days=days_ago),
            importance=importance, keywords=[],
        )

    def test_search_returns_chunks_with_scores(self):
        s = MemorySearcher()
        s.add_chunk(self._mk(1, "数据库", "sqlite 数据库连接管理", importance=8))
        s.add_chunk(self._mk(2, "定时任务", "cron 定时调度", importance=5))
        res = s.search("数据库", top_k=2)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0][0].title, "数据库")
        self.assertGreater(res[0][1], 0)

    def test_importance_and_time_weighting(self):
        # 同样内容，重要性高且更近的得分更高
        s = MemorySearcher()
        s.add_chunk(self._mk(1, "a", "数据库连接", importance=9, days_ago=1))
        s.add_chunk(self._mk(2, "b", "数据库连接", importance=1, days_ago=100))
        res = s.search("数据库", top_k=2)
        self.assertEqual(res[0][0].title, "a")  # 重要性高 + 近期

    def test_clear(self):
        s = MemorySearcher()
        s.add_chunk(self._mk(1, "a", "数据库"))
        self.assertEqual(len(s.search("数据库")), 1)
        s.clear()
        self.assertEqual(len(s.search("数据库")), 0)


if __name__ == "__main__":
    unittest.main()
