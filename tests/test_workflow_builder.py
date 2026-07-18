#!/usr/bin/env python
# Copyright 2026 LemonClaw Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# ...

"""
agent.workflow.builder 模块单元测试

覆盖 normalize_state_schema / normalize_node_config / normalize_edges / compile。
用 human 节点（无需 LLM）+ MemorySaver 编译验证。
"""

import unittest
from langgraph.checkpoint.memory import MemorySaver
from agent.workflow.builder import WorkflowBuilder
from dao.workflow import Workflow


class FakeLLM:
    def invoke(self, prompt):
        from unittest.mock import MagicMock
        m = MagicMock()
        m.content = "ok"
        return m


class FakeManager:
    _subagents = {}
    def _get_graph_by_id(self, wid): return None


class MockDAO:
    pass


class TestNormalizeStateSchema(unittest.TestCase):
    def setUp(self):
        self.builder = WorkflowBuilder(FakeLLM(), {}, MemorySaver(), FakeManager())

    def test_list_passthrough(self):
        result = self.builder._normalize_state_schema([{"name": "x", "type": "str"}])
        self.assertEqual(len(result), 1)

    def test_dict_format(self):
        result = self.builder._normalize_state_schema({"x": "str", "y": "int"})
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["type"], "str")

    def test_json_schema_format(self):
        result = self.builder._normalize_state_schema({
            "type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "integer"}},
            "required": ["a"]})
        self.assertEqual(len(result), 2)

    def test_empty(self):
        self.assertEqual(self.builder._normalize_state_schema(None), [])


class TestNormalizeNodeConfig(unittest.TestCase):
    def setUp(self):
        self.builder = WorkflowBuilder(FakeLLM(), {}, MemorySaver(), FakeManager())

    def test_nested_config(self):
        nd = {"name": "n1", "kind": "llm", "config": {"prompt": "hi", "output_field": "r"}}
        nc = self.builder._normalize_node_config(nd)
        self.assertEqual(nc["prompt"], "hi")

    def test_flat_config(self):
        nd = {"name": "n1", "kind": "llm", "prompt": "hi", "output_key": "r"}
        nc = self.builder._normalize_node_config(nd)
        self.assertEqual(nc["prompt"], "hi")
        self.assertEqual(nc["output_field"], "r")  # aliased from output_key


class TestNormalizeEdges(unittest.TestCase):
    def setUp(self):
        self.builder = WorkflowBuilder(FakeLLM(), {}, MemorySaver(), FakeManager())

    def test_empty_edges_auto_start_end(self):
        nodes = [{"name": "a"}, {"name": "b"}]
        edges = self.builder._normalize_edges([], nodes)
        self.assertEqual(edges[0]["src"], "START")
        self.assertEqual(edges[-1]["dst"], "END")

    def test_existing_start_preserved(self):
        nodes = [{"name": "a"}]
        edges = self.builder._normalize_edges([{"src": "START", "dst": "a"}], nodes)
        self.assertEqual(len(edges), 2)  # START preserved + auto END
        self.assertEqual(edges[0]["src"], "START")


class TestCompile(unittest.TestCase):
    def test_compile_human_node(self):
        """用 human 节点（无 LLM）验证编译通过。"""
        wf = Workflow(workflow_id="test", name="t", version=1, spec={
            "state_schema": [{"name": "answer", "type": "str"}],
            "nodes": [{"name": "ask", "kind": "human",
                       "config": {"question": "agree?", "output_field": "answer"}}],
            "edges": [], "conditionals": []
        })
        builder = WorkflowBuilder(FakeLLM(), {}, MemorySaver(), FakeManager())
        graph = builder.compile(wf)
        self.assertIsNotNone(graph)


if __name__ == "__main__":
    unittest.main()