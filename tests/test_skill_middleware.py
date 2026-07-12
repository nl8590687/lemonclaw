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
agent.memory.middleware 扩展（技能）单元测试

覆盖：skill_manager=None 向后兼容；摘要+活跃全文注入与顺序；P2-7 缓存语义
（记忆 _ctx 按 query 缓存，技能摘要/活跃全文每轮现算）；enable/disable 即时反映。
用 mock SkillManager + MemoryManager，不依赖 LLM 与 db。
"""

import unittest
from unittest.mock import MagicMock

from langchain_core.messages import HumanMessage

from agent.memory.middleware import MemoryMiddleware


class _FakeRequest:
    def __init__(self, messages):
        self.messages = messages
        self.overridden = None

    def override(self, system_message=None):
        self.overridden = system_message
        return self


def _run(mw, query: str):
    req = _FakeRequest([HumanMessage(content=query)])
    mw.wrap_model_call(req, lambda r: r)
    return req.overridden.content


class TestBackwardCompat(unittest.TestCase):
    def test_skill_manager_none_acts_as_memory_only(self):
        mm = MagicMock()
        mm.build_context.return_value = "MEM"
        mw = MemoryMiddleware(mm, "BASE")  # 无 skill_manager
        content = _run(mw, "q")
        self.assertEqual(content, "BASE\n\nMEM")

    def test_no_managers_just_base(self):
        mw = MemoryMiddleware(None, "BASE")
        content = _run(mw, "q")
        self.assertEqual(content, "BASE")


class TestInjectionOrder(unittest.TestCase):
    def test_summary_and_active_injected_in_order(self):
        mm = MagicMock(); mm.build_context.return_value = "MEM"
        sm = MagicMock()
        sm.get_skill_summary_text.return_value = "SUMMARY"
        sm.build_active_section.return_value = "ACTIVE"
        mw = MemoryMiddleware(mm, "BASE", skill_manager=sm)
        content = _run(mw, "q")
        self.assertIn("BASE", content)
        self.assertIn("SUMMARY", content)
        self.assertIn("ACTIVE", content)
        self.assertIn("MEM", content)
        # 顺序：BASE < SUMMARY < ACTIVE < MEM
        self.assertLess(content.index("SUMMARY"), content.index("ACTIVE"))
        self.assertLess(content.index("ACTIVE"), content.index("MEM"))


class TestCacheSemantics(unittest.TestCase):
    def test_active_section_fresh_each_turn(self):
        # P2-7：同一 query 下 load_skill 后下一轮 build_active_section 返回新值，不被缓存
        mm = MagicMock(); mm.build_context.return_value = ""
        sm = MagicMock()
        sm.get_skill_summary_text.return_value = ""
        sm.build_active_section.side_effect = ["OLD", "NEW"]
        mw = MemoryMiddleware(mm, "BASE", skill_manager=sm)
        self.assertIn("OLD", _run(mw, "q"))
        content2 = _run(mw, "q")
        self.assertIn("NEW", content2)
        self.assertNotIn("OLD", content2)

    def test_summary_fresh_each_turn(self):
        # P1-3：enable/disable 后下一轮摘要现取新值
        mm = MagicMock(); mm.build_context.return_value = ""
        sm = MagicMock()
        sm.get_skill_summary_text.side_effect = ["BEFORE", "AFTER"]
        sm.build_active_section.return_value = ""
        mw = MemoryMiddleware(mm, "BASE", skill_manager=sm)
        self.assertIn("BEFORE", _run(mw, "q"))
        self.assertIn("AFTER", _run(mw, "q"))

    def test_memory_ctx_cached_per_query(self):
        # 记忆上下文按 query 缓存：同一 query 多轮只调一次 build_context
        mm = MagicMock(); mm.build_context.return_value = "MEM"
        sm = MagicMock()
        sm.get_skill_summary_text.return_value = ""
        sm.build_active_section.return_value = ""
        mw = MemoryMiddleware(mm, "BASE", skill_manager=sm)
        _run(mw, "q")
        _run(mw, "q")  # 同 query
        self.assertEqual(mm.build_context.call_count, 1)
        _run(mw, "q2")  # 新 query
        self.assertEqual(mm.build_context.call_count, 2)


if __name__ == "__main__":
    unittest.main()
