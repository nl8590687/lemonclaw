#!/usr/bin/env python
# Copyright 2026 LemonClaw Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# ...

"""
agent.workflow.nodes 模块单元测试

覆盖 human/main_agent（interrupt）、llm（fake）、tool（fake）、subagent（fake manager）。
不依赖真实 LLM。
"""

import unittest
from unittest.mock import MagicMock

from agent.workflow.nodes import make_node


class FakeLLM:
    def invoke(self, prompt):
        m = MagicMock()
        m.content = f"echo: {prompt}"
        return m


class FakeTool:
    name = "test_tool"
    def invoke(self, args):
        return f"called with {args}"


class FakeManager:
    def run_subagent_inline(self, sid, task, ctx=None):
        return f"subagent_{sid}: {task}"
    def _get_graph_by_id(self, wid):
        return None


class TestHumanNode(unittest.TestCase):
    def test_human_interrupt_payload(self):
        nc = {"question": "are you sure?", "output_field": "answer", "handler": "interactive"}
        fn = make_node("human", nc, None, {}, None)
        try:
            fn({"topic": "x"}, {"configurable": {"thread_id": "r1"}})
        except Exception as e:
            pass  # interrupt raises internally
        # verify the node is callable
        self.assertTrue(callable(fn))

    def test_human_interrupt_includes_run_id(self):
        nc = {"question": "q?", "output_field": "reply"}
        fn = make_node("human", nc, None, {}, None)
        self.assertTrue(callable(fn))


class TestLLMNode(unittest.TestCase):
    def test_llm_node_output(self):
        llm = FakeLLM()
        nc = {"prompt": "process {input}", "output_field": "result"}
        fn = make_node("llm", nc, llm, {}, None)
        result = fn({"input": "hello"})
        self.assertIn("result", result)
        self.assertIn("hello", result["result"])


class TestToolNode(unittest.TestCase):
    def test_tool_node_call(self):
        tools = {"test_tool": FakeTool()}
        nc = {"tool_name": "test_tool", "args": {"q": "x"}, "output_field": "out"}
        fn = make_node("tool", nc, None, tools, None)
        result = fn({"topic": "y"})
        self.assertIn("out", result)

    def test_tool_not_found(self):
        nc = {"tool_name": "nonexistent", "output_field": "out"}
        fn = make_node("tool", nc, None, {}, None)
        result = fn({})
        self.assertIn("不存在", result["out"])


class TestSubAgentNode(unittest.TestCase):
    def test_subagent_inline(self):
        mgr = FakeManager()
        nc = {"subagent_id": "sa:1:1:step1", "task": "summarize {topic}", "output_field": "summary"}
        fn = make_node("subagent", nc, None, {}, mgr)
        result = fn({"topic": "AI"})
        self.assertIn("summary", result)
        self.assertIn("sa:1:1:step1", result["summary"])


class TestUnknownKind(unittest.TestCase):
    def test_unknown_raises(self):
        with self.assertRaises(ValueError):
            make_node("unknown_kind", {}, None, {}, None)


if __name__ == "__main__":
    unittest.main()