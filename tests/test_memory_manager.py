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
MemoryManager 单元测试（P2：会话生命周期、消息映射/去重、reconstruct、reopen）

不依赖真实 LLM；用独立临时 db，不污染 .lemonclaw/lemonclaw.db。
"""

import os
import tempfile
import unittest
from pathlib import Path

import agent.memory as _am
import dao.db as _db
from agent.memory.manager import MemoryManager
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage


class _TempDbTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        _db._global_db_path = Path(self._tmpdir) / "t.db"
        _am._global_memory_manager = None
        self.mgr = MemoryManager()

    def tearDown(self):
        _db._global_db_path = None


class TestSessionLifecycle(_TempDbTestCase):
    def test_session_start_creates_session(self):
        sid = self.mgr.on_session_start()
        self.assertIsNotNone(sid)
        self.assertEqual(self.mgr.current_session_id, sid)

    def test_session_end_archives_and_clears(self):
        sid = self.mgr.on_session_start()
        self.mgr.on_session_end()
        self.assertIsNone(self.mgr.current_session_id)
        s = self.mgr.session_dao.get(sid)
        self.assertTrue(s.is_archived)
        self.assertIsNotNone(s.end_time)

    def test_recent_session_id_excludes_current(self):
        a = self.mgr.on_session_start()
        self.mgr.on_session_end()
        b = self.mgr.on_session_start()
        self.assertEqual(self.mgr.recent_session_id(), a)  # 当前 b，返回 a
        self.mgr.on_session_end()
        self.assertEqual(self.mgr.recent_session_id(), b)  # 无当前，返回最近归档 b

    def test_reopen_resets_state(self):
        sid = self.mgr.on_session_start()
        self.mgr.on_session_end()
        self.assertTrue(self.mgr.reopen_session(sid))
        self.assertEqual(self.mgr.current_session_id, sid)
        s = self.mgr.session_dao.get(sid)
        self.assertFalse(s.is_archived)
        self.assertIsNone(s.end_time)


class TestOnMessagesDedup(_TempDbTestCase):
    def test_dedup_by_message_id(self):
        sid = self.mgr.on_session_start()
        self.mgr.on_messages([HumanMessage(content="你好", id="u1"),
                              AIMessage(content="嗨", id="a1")])
        self.mgr.on_messages([HumanMessage(content="你好", id="u1"),
                              AIMessage(content="嗨", id="a1"),
                              HumanMessage(content="天气", id="u2")])
        msgs = self.mgr.load_session_messages(sid)
        self.assertEqual(len(msgs), 3)
        self.assertEqual([m.content for m in msgs], ["你好", "嗨", "天气"])

    def test_system_message_not_persisted(self):
        sid = self.mgr.on_session_start()
        self.mgr.on_messages([SystemMessage(content="sys"), HumanMessage(content="hi", id="u1")])
        msgs = self.mgr.load_session_messages(sid)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].role, "human")

    def test_ai_tool_call_mapping(self):
        sid = self.mgr.on_session_start()
        self.mgr.on_messages([
            HumanMessage(content="查天气", id="u1"),
            AIMessage(content="", tool_calls=[{
                "id": "tc1", "name": "weather", "args": {"city": "北京"}, "type": "tool_call"
            }], id="a1"),
            ToolMessage(content="晴", tool_call_id="tc1", name="weather", id="t1"),
        ])
        msgs = self.mgr.load_session_messages(sid)
        ai = [m for m in msgs if m.role == "ai"][0]
        self.assertEqual(ai.tool_name, "weather")
        self.assertEqual(ai.tool_args, {"city": "北京"})
        self.assertEqual(ai.tool_call_id, "tc1")
        tool = [m for m in msgs if m.role == "tool"][0]
        self.assertEqual(tool.tool_call_id, "tc1")
        self.assertEqual(tool.tool_name, "weather")


class TestReconstruct(_TempDbTestCase):
    def test_reconstruct_roundtrip(self):
        sid = self.mgr.on_session_start()
        self.mgr.on_messages([
            HumanMessage(content="hi", id="u1"),
            AIMessage(content="hello", id="a1"),
        ])
        rec = self.mgr.reconstruct_messages(sid)
        self.assertEqual(len(rec), 2)
        self.assertIsInstance(rec[0], HumanMessage)
        self.assertIsInstance(rec[1], AIMessage)
        self.assertEqual(rec[0].content, "hi")

    def test_reconstruct_tool_calls_chain(self):
        sid = self.mgr.on_session_start()
        self.mgr.on_messages([
            HumanMessage(content="查", id="u1"),
            AIMessage(content="", tool_calls=[{
                "id": "tc1", "name": "w", "args": {"q": 1}, "type": "tool_call"
            }], id="a1"),
            ToolMessage(content="r", tool_call_id="tc1", name="w", id="t1"),
        ])
        rec = self.mgr.reconstruct_messages(sid)
        ai = [m for m in rec if isinstance(m, AIMessage) and m.tool_calls][0]
        self.assertEqual(ai.tool_calls[0]["id"], "tc1")
        tool = [m for m in rec if isinstance(m, ToolMessage)][0]
        self.assertEqual(tool.tool_call_id, "tc1")

    def test_reopen_no_duplicate_on_replay(self):
        # 原地续写：回放历史 + 新消息，历史不重复写入
        sid = self.mgr.on_session_start()
        self.mgr.on_messages([HumanMessage(content="hi", id="u1"),
                              AIMessage(content="yo", id="a1")])
        self.mgr.on_session_end()
        self.mgr.reopen_session(sid)
        rec = self.mgr.reconstruct_messages(sid)
        self.mgr.on_messages(rec + [HumanMessage(content="again", id="u2")])
        msgs = self.mgr.load_session_messages(sid)
        self.assertEqual(len(msgs), 3)  # 2 历史 + 1 新


class TestBuildContext(_TempDbTestCase):
    def test_empty_returns_empty(self):
        self.assertEqual(self.mgr.build_context("x"), "")

    def test_core_memory_injected(self):
        self.mgr.remember("lang", "中文", memory_type="preference")
        ctx = self.mgr.build_context("x")
        self.assertIn("核心记忆", ctx)
        self.assertIn("lang: 中文", ctx)

    def test_chunks_injected_when_query_matches(self):
        self.mgr.add_chunk("fact", "数据库连接", "sqlite 数据库连接管理", importance=8)
        ctx = self.mgr.build_context("数据库")
        self.assertIn("相关历史记忆", ctx)
        self.assertIn("数据库连接", ctx)

    def test_tiny_budget_returns_empty(self):
        self.mgr.remember("lang", "中文", memory_type="preference")
        self.assertEqual(self.mgr.build_context("x", max_tokens=1), "")

    def test_large_budget_injects(self):
        self.mgr.remember("lang", "中文", memory_type="preference")
        ctx = self.mgr.build_context("x", max_tokens=1000)
        self.assertIn("核心记忆", ctx)


class _FakeRequest:
    def __init__(self, messages, system_message=None):
        self.messages = messages
        self.system_message = system_message

    def override(self, **kw):
        return _FakeRequest(self.messages, kw.get("system_message", self.system_message))


class _FakeMgr:
    def __init__(self, ctx="CTX"):
        self.ctx = ctx
        self.calls = 0

    def build_context(self, query):
        self.calls += 1
        return self.ctx


class TestMemoryMiddleware(unittest.TestCase):
    def test_override_system_message(self):
        from agent.memory.middleware import MemoryMiddleware
        mw = MemoryMiddleware(_FakeMgr("记忆上下文"), "BASE_PROMPT")
        req = _FakeRequest([HumanMessage(content="你好", id="u1")])
        captured = {}

        def handler(r):
            captured["sm"] = r.system_message
            return "ok"

        self.assertEqual(mw.wrap_model_call(req, handler), "ok")
        self.assertIn("BASE_PROMPT", captured["sm"].content)
        self.assertIn("记忆上下文", captured["sm"].content)

    def test_query_cache(self):
        from agent.memory.middleware import MemoryMiddleware
        mgr = _FakeMgr("CTX")
        mw = MemoryMiddleware(mgr, "BASE")
        ok = lambda r: "ok"
        mw.wrap_model_call(_FakeRequest([HumanMessage(content="你好", id="u1")]), ok)
        mw.wrap_model_call(_FakeRequest([HumanMessage(content="你好", id="u2")]), ok)
        self.assertEqual(mgr.calls, 1)  # 同 query 命中缓存
        mw.wrap_model_call(_FakeRequest([HumanMessage(content="天气", id="u3")]), ok)
        self.assertEqual(mgr.calls, 2)  # 不同 query 重建

    def test_none_memory_manager(self):
        from agent.memory.middleware import MemoryMiddleware
        mw = MemoryMiddleware(None, "BASE")
        captured = {}
        mw.wrap_model_call(_FakeRequest([HumanMessage(content="你好", id="u1")]),
                           lambda r: captured.__setitem__("sm", r.system_message))
        self.assertEqual(captured["sm"].content, "BASE")  # 无 ctx，仅 BASE


class TestSessionEndFast(_TempDbTestCase):
    """on_session_end(fast=True)：程序退出路径，跳过 LLM、不重载索引"""

    def setUp(self):
        super().setUp()
        os.environ["MEMORY_AUTO_ARCHIVE"] = "true"
        import config.config as _cc
        _cc._global_config = None

    def test_fast_path_skips_llm_and_writes_simple_chunks(self):
        sid = self.mgr.on_session_start()
        self.mgr.on_messages([
            HumanMessage(content="查天气", id="u1"),
            AIMessage(content="", tool_calls=[{
                "id": "tc1", "name": "weather", "args": {}, "type": "tool_call"
            }], id="a1"),
            ToolMessage(content="晴", tool_call_id="tc1", name="weather", id="t1"),
        ])
        # 若 fast 路径误触 LLM 版方法则抛错
        def boom_sum(self, messages):
            raise AssertionError("LLM summary 不应被调用")
        def boom_chk(self, messages):
            raise AssertionError("LLM chunks 不应被调用")
        self.mgr.extractor.extract_session_summary = boom_sum.__get__(self.mgr.extractor)
        self.mgr.extractor.extract_chunks = boom_chk.__get__(self.mgr.extractor)

        self.mgr.on_session_end(self.mgr.reconstruct_messages(sid), fast=True)

        s = self.mgr.session_dao.get(sid)
        self.assertTrue(s.is_archived)
        self.assertIsNotNone(s.summary)  # 统计版摘要
        chunks = self.mgr.list_chunks()
        self.assertTrue(any(c.title == "使用了工具: weather" for c in chunks))
        self.assertTrue(any(c.chunk_type == "summary" for c in chunks))


if __name__ == "__main__":
    unittest.main()
