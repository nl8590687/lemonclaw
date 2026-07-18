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
dao.workflow 模块单元测试

覆盖 WorkflowDAO 的 upsert_workflow / get / list / delete /
create_run / get_run / list_runs / update_run_status / list_pending_runs /
_row_to_workflow / _row_to_run JSON 往返。
每个用例使用独立的临时 db，不依赖 LLM，不污染 .lemonclaw/lemonclaw.db。
"""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import dao.db as _db
from dao.workflow import (Workflow, WorkflowRun, WorkflowDAO, ensure_workflow_schema,
                          _row_to_workflow, _row_to_run)


class _TempDbTestCase(unittest.TestCase):
    """每个用例使用独立的临时 db，互不污染。"""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        _db._global_db_path = Path(self._tmpdir) / "test.db"
        import agent.workflow as _aw
        _aw._workflow_manager = None

    def tearDown(self):
        _db._global_db_path = None


class TestEnsureSchema(_TempDbTestCase):
    def test_creates_tables_and_indexes_idempotently(self):
        ensure_workflow_schema()
        ensure_workflow_schema()  # 幂等
        with _db.get_connection() as conn:
            tables = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            indexes = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'")}
        self.assertIn("workflows", tables)
        self.assertIn("workflow_runs", tables)
        self.assertIn("idx_wf_enabled", indexes)
        self.assertIn("idx_wfr_workflow", indexes)
        self.assertIn("idx_wfr_status", indexes)


class TestWorkflowCRUD(_TempDbTestCase):
    def setUp(self):
        super().setUp()
        self.dao = WorkflowDAO()

    def test_upsert_and_get(self):
        wf = Workflow(workflow_id="wf_test", name="测试", description="desc",
                      spec={"state_schema": [{"name": "x", "type": "str"}],
                            "nodes": [], "edges": [], "conditionals": []},
                      version=1)
        self.assertTrue(self.dao.upsert_workflow(wf))
        got = self.dao.get_workflow("wf_test")
        self.assertIsNotNone(got)
        self.assertEqual(got.name, "测试")
        self.assertEqual(got.version, 1)
        self.assertEqual(got.spec["state_schema"][0]["type"], "str")
        self.assertTrue(got.enabled)

    def test_upsert_updates_existing(self):
        wf = Workflow(workflow_id="wf_test", name="original", version=1)
        self.dao.upsert_workflow(wf)
        wf.name = "updated"
        wf.version = 2
        self.dao.upsert_workflow(wf)
        got = self.dao.get_workflow("wf_test")
        self.assertEqual(got.name, "updated")
        self.assertEqual(got.version, 2)

    def test_get_by_name(self):
        self.dao.upsert_workflow(Workflow(workflow_id="w1", name="foo", version=1))
        got = self.dao.get_workflow_by_name("foo")
        self.assertIsNotNone(got)
        self.assertEqual(got.workflow_id, "w1")

    def test_list_workflows(self):
        self.dao.upsert_workflow(Workflow(workflow_id="w1", name="a", version=1))
        self.dao.upsert_workflow(Workflow(workflow_id="w2", name="b", version=1, enabled=False))
        wfs = self.dao.list_workflows()
        self.assertEqual(len(wfs), 2)
        wfs_enabled = self.dao.list_workflows(include_disabled=False)
        self.assertEqual(len(wfs_enabled), 1)

    def test_set_last_error(self):
        self.dao.upsert_workflow(Workflow(workflow_id="w1", name="e", version=1))
        self.dao.set_last_error("w1", "something broke")
        got = self.dao.get_workflow("w1")
        self.assertEqual(got.last_error, "something broke")
        self.dao.set_last_error("w1", None)
        self.assertIsNone(self.dao.get_workflow("w1").last_error)

    def test_delete_workflow(self):
        self.dao.upsert_workflow(Workflow(workflow_id="w1", name="d", version=1))
        self.dao.delete_workflow("w1")
        self.assertIsNone(self.dao.get_workflow("w1"))

    def test_json_roundtrip(self):
        """spec / interrupt_info / input / output JSON 往返"""
        spec = {"state_schema": [{"name": "answer", "type": "str"}],
                "nodes": [{"name": "ask", "kind": "human",
                           "config": {"question": "OK?", "output_field": "answer"}}],
                "edges": [{"src": "START", "dst": "ask"}, {"src": "ask", "dst": "END"}],
                "conditionals": []}
        wf = Workflow(workflow_id="wf_json", name="json_test", version=1, spec=spec)
        self.dao.upsert_workflow(wf)
        got = self.dao.get_workflow("wf_json")
        self.assertEqual(got.spec["nodes"][0]["name"], "ask")
        # spec JSON roundtrip
        raw = json.dumps(got.spec, ensure_ascii=False)
        reloaded = json.loads(raw)
        self.assertEqual(reloaded["nodes"][0]["kind"], "human")


class TestWorkflowRunCRUD(_TempDbTestCase):
    def setUp(self):
        super().setUp()
        self.dao = WorkflowDAO()
        self.dao.upsert_workflow(Workflow(workflow_id="wf_parent", name="p", version=1,
                                          spec={"state_schema": [], "nodes": [], "edges": [],
                                                "conditionals": []}))

    def test_create_and_get_run(self):
        run = WorkflowRun(run_id="r1", workflow_id="wf_parent", workflow_version=1,
                          status="running", origin_context={"channel": "feishu", "chat_id": "oc_x"})
        self.dao.create_run(run)
        got = self.dao.get_run("r1")
        self.assertEqual(got.status, "running")
        self.assertEqual(got.origin_context["channel"], "feishu")

    def test_list_runs_filter(self):
        for rid, st in [("r1", "running"), ("r2", "paused"), ("r3", "completed")]:
            self.dao.create_run(WorkflowRun(run_id=rid, workflow_id="wf_parent",
                                             workflow_version=1, status=st))
        self.assertEqual(len(self.dao.list_runs(status="active")), 2)  # running + paused
        self.assertEqual(len(self.dao.list_runs(status="paused")), 1)
        self.assertEqual(len(self.dao.list_runs(status="all")), 3)

    def test_update_run_status(self):
        self.dao.create_run(WorkflowRun(run_id="r1", workflow_id="wf_parent", workflow_version=1,
                                         status="running"))
        self.dao.update_run_status("r1", "paused", loop_kind="need_human",
                                   interrupt_info={"question": "q"})
        got = self.dao.get_run("r1")
        self.assertEqual(got.status, "paused")
        self.assertEqual(got.loop_kind, "need_human")
        self.assertEqual(got.interrupt_info["question"], "q")

    def test_list_pending_runs(self):
        self.dao.create_run(WorkflowRun(run_id="r1", workflow_id="wf_parent", workflow_version=1,
                                         status="paused"))
        self.dao.create_run(WorkflowRun(run_id="r2", workflow_id="wf_parent", workflow_version=1,
                                         status="completed"))
        self.assertEqual(len(self.dao.list_pending_runs()), 1)
        self.assertEqual(self.dao.list_pending_runs()[0].run_id, "r1")

    def test_delete_run_and_cascade(self):
        """删除 workflow 应级联删除 run（CASCADE）"""
        self.dao.create_run(WorkflowRun(run_id="r1", workflow_id="wf_parent", workflow_version=1,
                                         status="completed"))
        self.dao.delete_workflow("wf_parent")
        self.assertIsNone(self.dao.get_run("r1"))
        self.assertIsNone(self.dao.get_workflow("wf_parent"))


class TestRowConverters(_TempDbTestCase):
    """_row_to_workflow / _row_to_run JSON 异常回退"""

    def setUp(self):
        super().setUp()
        ensure_workflow_schema()

    def test_row_to_workflow_bad_json(self):
        with _db.get_connection() as conn:
            conn.execute("INSERT INTO workflows (workflow_id,name,spec,created_at,updated_at) "
                         "VALUES ('w1','x','bad json',datetime('now'),datetime('now'))")
            row = conn.execute("SELECT * FROM workflows WHERE workflow_id='w1'").fetchone()
        wf = _row_to_workflow(row)
        self.assertEqual(wf.spec, {})  # fallback to {}
        self.assertEqual(wf.workflow_id, "w1")

    def test_row_to_run_bad_json(self):
        self.dao = WorkflowDAO()
        self.dao.upsert_workflow(Workflow(workflow_id="w1", name="x", version=1,
                                          spec={"state_schema": [], "nodes": [], "edges": [],
                                                "conditionals": []}))
        with _db.get_connection() as conn:
            conn.execute("INSERT INTO workflow_runs (run_id,workflow_id,workflow_version,"
                         "status,interrupt_info,input,output,origin_context,created_at,updated_at) "
                         "VALUES ('r1','w1',1,'running','x','{}','{}','{}',"
                         "datetime('now'),datetime('now'))")
            row = conn.execute("SELECT * FROM workflow_runs WHERE run_id='r1'").fetchone()
        run = _row_to_run(row)
        self.assertEqual(run.interrupt_info, {})
        self.assertEqual(run.run_id, "r1")


if __name__ == "__main__":
    unittest.main()