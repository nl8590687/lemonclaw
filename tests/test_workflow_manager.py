#!/usr/bin/env python
# Copyright 2026 LemonClaw Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# ...

"""
agent.workflow.manager 集成测试

全链路：define_workflow -> start_run -> interrupt(resume) -> resume_run -> completed。
用 human 节点（无 LLM）+ MemorySaver 替代 SqliteSaver（临时 db）。
"""

import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

import dao.db as _db
from dao.workflow import ensure_workflow_schema


class _TempDbTestCase(unittest.TestCase):
    """每个用例使用独立的临时 db，互不污染。"""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        _db._global_db_path = Path(self._tmpdir) / "test.db"
        import agent.workflow as _aw
        _aw._workflow_manager = None

    def tearDown(self):
        _db._global_db_path = None


class TestManagerDefineAndRun(_TempDbTestCase):
    """define -> start -> (interrupt) -> resume -> completed 全链路"""

    def setUp(self):
        super().setUp()
        # 覆盖 checkpointer 为 MemorySaver（测试环境不装 SqliteSaver 也不影响）
        self._orig_init_ckpt = None
        import agent.workflow.manager as _wm
        from langgraph.checkpoint.memory import MemorySaver
        self._orig_init_ckpt = _wm.WorkflowManager._init_checkpointer
        _wm.WorkflowManager._init_checkpointer = lambda self: MemorySaver()
        from agent.workflow import get_workflow_manager
        self.mgr = get_workflow_manager()

    def tearDown(self):
        if self._orig_init_ckpt:
            import agent.workflow.manager as _wm
            _wm.WorkflowManager._init_checkpointer = self._orig_init_ckpt
        super().tearDown()

    def _human_spec(self, name="test_hitl"):
        return {"state_schema": [{"name": "answer", "type": "str"}],
                "nodes": [{"name": "ask", "kind": "human",
                           "config": {"question": "同意吗？", "output_field": "answer"}}],
                "edges": [], "conditionals": []}

    def test_define_compile(self):
        wf = self.mgr.define_workflow("test_def", "define test", self._human_spec())
        self.assertIsNotNone(wf)
        self.assertIsNone(wf.last_error)

    def test_define_duplicate_update(self):
        wf1 = self.mgr.define_workflow("test_dup", "v1", self._human_spec())
        v1 = wf1.version
        wf2 = self.mgr.define_workflow("test_dup", "v2", self._human_spec())
        self.assertEqual(wf2.version, v1 + 1)

    def test_start_and_interrupt(self):
        self.mgr.define_workflow("test_hitl", "hitl test", self._human_spec())
        run_id, info = self.mgr.start_run("test_hitl", {}, {"channel": "terminal"})
        self.assertIsNotNone(run_id)
        self.assertEqual(info["status"], "running")
        time.sleep(2)  # wait for worker
        run = self.mgr.inspect_run(run_id)
        self.assertEqual(run["status"], "paused")
        self.assertEqual(run["loop_kind"], "need_human")

    def test_resume_and_complete(self):
        self.mgr.define_workflow("test_resume", "resume test", self._human_spec())
        run_id, _ = self.mgr.start_run("test_resume", {}, {})
        time.sleep(2)
        self.mgr.resume_run(run_id, "同意", {})
        time.sleep(2)
        run = self.mgr.inspect_run(run_id)
        self.assertEqual(run["status"], "completed")
        self.assertIn("answer", run.get("output", {}))

    def test_delete_workflow(self):
        self.mgr.define_workflow("test_del", "del test", self._human_spec())
        # 无在途 run 时可删除
        ok, msg = self.mgr.delete_workflow("test_del")
        self.assertTrue(ok)
        self.assertIsNone(self.mgr.get_workflow("test_del"))

    def test_delete_blocks_on_active_run(self):
        self.mgr.define_workflow("test_block", "block test", self._human_spec())
        self.mgr.start_run("test_block", {}, {})
        time.sleep(2)
        ok, msg = self.mgr.delete_workflow("test_block")
        self.assertFalse(ok)  # 有在途 run 拒绝

    def test_one_shot_auto_delete(self):
        spec = self._human_spec()
        spec["one_shot"] = True
        self.mgr.define_workflow("test_oneshot", "one-shot", spec)
        run_id, _ = self.mgr.start_run("test_oneshot", {}, {})
        time.sleep(2)
        # paused → should NOT auto-delete
        self.assertIsNotNone(self.mgr.get_workflow("test_oneshot"))
        # resume → completed → auto-delete
        self.mgr.resume_run(run_id, "ok", {})
        time.sleep(2)
        self.assertIsNone(self.mgr.get_workflow("test_oneshot"))

    def test_list_runs_and_workflows(self):
        self.mgr.define_workflow("test_list", "list test", self._human_spec())
        self.mgr.start_run("test_list", {}, {})
        time.sleep(2)
        runs = self.mgr.list_runs(status="active")
        self.assertGreaterEqual(len(runs), 1)
        wfs = self.mgr.list_workflows()
        self.assertGreaterEqual(len(wfs), 1)

    def test_cancel_run(self):
        self.mgr.define_workflow("test_cancel", "cancel test", self._human_spec())
        run_id, _ = self.mgr.start_run("test_cancel", {}, {})
        time.sleep(2)
        ok, msg = self.mgr.cancel_run(run_id)
        self.assertTrue(ok)


class TestSubAgentInline(unittest.TestCase):
    """BaseSubAgent.run 基本测试（fake LLM）"""

    def test_run_returns_reply(self):
        from unittest.mock import MagicMock
        from agent.workflow.subagents import BaseSubAgent
        fake_llm = MagicMock()
        fake_resp = MagicMock()
        fake_resp.content = "done"
        fake_llm.invoke.return_value = fake_resp

        # Mock create_agent to return a fake agent
        import agent.workflow.subagents as _sa
        _sa.create_agent = MagicMock(return_value=MagicMock())
        _sa.create_agent.return_value.invoke.return_value = {
            "messages": [MagicMock(content="hello world")]
        }

        agent = BaseSubAgent("sa_test", None, system_prompt="hi", tools=[])
        reply = agent.run("do task")
        self.assertTrue(len(reply) > 0)


if __name__ == "__main__":
    unittest.main()