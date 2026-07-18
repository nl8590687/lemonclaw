#!/usr/bin/env python
# Copyright 2026 LemonClaw Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# ...

"""
agent.workflow.state 模块单元测试

覆盖 build_state_schema（list/dict、各类型、reducer）、render_template（{var} 和 ${var}）。
"""

import unittest
from langgraph.graph import START, END, StateGraph
from langgraph.checkpoint.memory import MemorySaver
from agent.workflow.state import build_state_schema, render_template


class TestBuildStateSchema(unittest.TestCase):
    def test_list_format(self):
        State = build_state_schema([{"name": "name", "type": "str"},
                                     {"name": "count", "type": "int"}])
        annots = State.__annotations__
        self.assertIn("name", annots)
        self.assertIn("count", annots)

    def test_default_type_any(self):
        State = build_state_schema([{"name": "x"}])
        self.assertIn("x", State.__annotations__)

    def test_add_messages_reducer(self):
        from typing import Annotated
        State = build_state_schema([{"name": "msgs", "type": "list", "reducer": "add_messages"}])
        self.assertIn("msgs", State.__annotations__)

    def test_append_reducer(self):
        State = build_state_schema([{"name": "items", "type": "list", "reducer": "append"}])
        self.assertIn("items", State.__annotations__)

    def test_state_graph_compile(self):
        """build_state_schema 产出的类可与 StateGraph 配合编译。"""
        State = build_state_schema([{"name": "result", "type": "str"}])
        g = StateGraph(State)
        g.add_node("n", lambda s: s)
        g.add_edge(START, "n")
        g.add_edge("n", END)
        graph = g.compile(checkpointer=MemorySaver())
        res = graph.invoke({"result": ""}, {"configurable": {"thread_id": "t1"}})
        self.assertIn("result", res)

    def test_empty_fields_placeholder(self):
        State = build_state_schema([])
        self.assertTrue(hasattr(State, "__annotations__"))


class TestRenderTemplate(unittest.TestCase):
    def test_plain_vars(self):
        self.assertEqual(render_template("hello {name}", {"name": "world"}), "hello world")

    def test_dollar_var(self):
        self.assertEqual(render_template("echo: ${x}", {"x": "42"}), "echo: 42")

    def test_missing_var_kept(self):
        self.assertEqual(render_template("hello {missing}", {}), "hello {missing}")

    def test_empty(self):
        self.assertEqual(render_template("", {}), "")

    def test_no_template(self):
        self.assertEqual(render_template("plain text", {}), "plain text")


if __name__ == "__main__":
    unittest.main()