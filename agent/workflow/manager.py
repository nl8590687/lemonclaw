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
业务层：WorkflowManager 门面

工作流 CRUD + 编译 + run/resume + SubAgent 内联 + 监督控制。
持有 SqliteSaver（持久 checkpointer）、WorkflowBuilder、WorkflowRunner、WorkflowExecutor。
"""

import logging
import re
import uuid
from datetime import datetime
from typing import Any

from dao.workflow import Workflow, WorkflowRun, WorkflowDAO, ensure_workflow_schema
from agent.workflow.builder import WorkflowBuilder
from agent.workflow.runner import WorkflowRunner
from agent.workflow.executor import WorkflowExecutor

logger = logging.getLogger(__name__)


class WorkflowManager:
    """工作流业务门面"""

    def __init__(self):
        ensure_workflow_schema()
        from config import get_global_config
        cfg = get_global_config()

        from agent.llm import create_openai_llm
        self.llm = create_openai_llm()

        self.dao = WorkflowDAO()
        self.checkpointer = self._init_checkpointer()
        self.builder = None  # 延迟创建（需 tools_dict）
        self.runner = WorkflowRunner(self.checkpointer, cfg.WORKFLOW_RECURSION_LIMIT,
                                     cfg.WORKFLOW_RESULT_MAX_CHARS)
        self.executor = WorkflowExecutor(cfg.WORKFLOW_WORKER_POOL_SIZE)

        self._graph_cache: dict[str, Any] = {}       # workflow_id:version -> CompiledStateGraph
        self._subagents: dict[str, Any] = {}          # workflow_id:version:node -> BaseSubAgent
        self._tools_dict: dict[str, Any] | None = None

    # ---- checkpointer ----

    def _init_checkpointer(self):
        """SqliteSaver 单例（指向 .lemonclaw/lemonclaw.db，WAL）。"""
        import sqlite3
        from langgraph.checkpoint.sqlite import SqliteSaver
        from dao.db import get_db_path
        conn = sqlite3.connect(str(get_db_path()), check_same_thread=False, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        saver = SqliteSaver(conn)
        saver.setup()
        return saver

    # ---- tools（延迟，避免循环初始化）----

    def _get_tools_dict(self) -> dict:
        """主 Agent 工具注册表（剔除 workflow_*，供 SubAgent 裁剪选取）。"""
        if self._tools_dict is None:
            from agent.tools import create_tool_list
            tools = create_tool_list()  # 此时 manager 已初始化，无递归
            self._tools_dict = {t.name: t for t in tools if not t.name.startswith("workflow_")}
        return self._tools_dict

    def _make_builder(self) -> WorkflowBuilder:
        return WorkflowBuilder(self.llm, self._get_tools_dict(), self.checkpointer, self)

    # ---- 编译 ----

    def _get_graph(self, wf: Workflow):
        """取已编译图（缓存 workflow_id:version）。"""
        key = f"{wf.workflow_id}:{wf.version}"
        if key in self._graph_cache:
            return self._graph_cache[key]
        builder = self._make_builder()
        graph = builder.compile(wf)
        self._graph_cache[key] = graph
        return graph

    def _get_graph_by_id(self, workflow_id: str):
        """据 workflow_id 取图（供 subgraph 节点用）。"""
        wf = self.dao.get_workflow(workflow_id)
        if wf is None:
            return None
        return self._get_graph(wf)

    # ---- Workflow CRUD ----

    def define_workflow(self, name: str, description: str, spec: dict) -> Workflow:
        """主路径：一次性给出完整 spec，创建或更新工作流 + 编译 + version+1。"""
        slug = re.sub(r'[^a-zA-Z0-9_-]', '_', name).strip('_').lower() or f"wf_{uuid.uuid4().hex[:6]}"
        wf = self.dao.get_workflow_by_name(name)
        if wf is None:
            wf = self.dao.get_workflow(slug)
        if wf is None:
            wf = Workflow(workflow_id=slug, name=name, description=description or "",
                          spec=spec, version=1)
        else:
            wf.description = description or ""
            wf.spec = spec
            wf.version += 1

        # 试编译
        try:
            builder = self._make_builder()
            builder.compile(wf)
            wf.last_error = None
        except Exception as ex:
            wf.last_error = str(ex)
            logger.warning("workflow %s compile failed: %s", slug, ex)

        self.dao.upsert_workflow(wf)
        # 失效旧版本缓存
        self._graph_cache = {k: v for k, v in self._graph_cache.items()
                             if not k.startswith(f"{wf.workflow_id}:")}
        return wf

    def list_workflows(self) -> list[Workflow]:
        return self.dao.list_workflows()

    def get_workflow(self, workflow_id: str) -> Workflow | None:
        return self.dao.get_workflow(workflow_id) or self.dao.get_workflow_by_name(workflow_id)

    def delete_workflow(self, workflow_id: str) -> tuple[bool, str]:
        wf = self.dao.get_workflow(workflow_id) or self.dao.get_workflow_by_name(workflow_id)
        if wf is None:
            return False, "工作流不存在"
        # 有在途 run 拒绝
        active = self.dao.list_runs(workflow_id=wf.workflow_id, status="active")
        if active:
            return False, f"有 {len(active)} 个在途 run，请先取消"
        # 清理所有 run 的 checkpoint
        all_runs = self.dao.list_runs(workflow_id=wf.workflow_id, status=None, limit=10000)
        for r in all_runs:
            self._cleanup_run(r.run_id)
        # 删除定义（CASCADE 删 run 记录）
        self.dao.delete_workflow(wf.workflow_id)
        # 失效缓存
        self._graph_cache = {k: v for k, v in self._graph_cache.items()
                             if not k.startswith(f"{wf.workflow_id}:")}
        return True, "已删除（含全部 run 与 checkpoint）"

    def reload_workflow(self, workflow_id: str) -> tuple[bool, str]:
        wf = self.dao.get_workflow(workflow_id) or self.dao.get_workflow_by_name(workflow_id)
        if wf is None:
            return False, "工作流不存在"
        self._graph_cache = {k: v for k, v in self._graph_cache.items()
                             if not k.startswith(f"{wf.workflow_id}:")}
        try:
            self._get_graph(wf)
            self.dao.set_last_error(wf.workflow_id, None)
            return True, "已重载"
        except Exception as ex:
            self.dao.set_last_error(wf.workflow_id, str(ex))
            return False, str(ex)

    # ---- Run ----

    def start_run(self, workflow_id: str, input: dict, context: dict) -> tuple[str | None, dict]:
        wf = self.get_workflow(workflow_id)
        if wf is None:
            return None, {"error": "工作流不存在"}
        if not wf.enabled:
            return None, {"error": "工作流未启用"}
        if wf.last_error:
            return None, {"error": f"工作流编译失败: {wf.last_error}"}
        try:
            graph = self._get_graph(wf)
        except Exception as ex:
            return None, {"error": f"编译失败: {ex}"}

        run_id = f"wf_run_{uuid.uuid4().hex[:12]}"
        run = WorkflowRun(
            run_id=run_id, workflow_id=wf.workflow_id, workflow_version=wf.version,
            status="running", input=input or {}, origin_context=context or {},
        )
        self.dao.create_run(run)

        self.executor.submit(self._run_invoke_task, graph, run_id, wf.workflow_id, input or {}, context or {})
        return run_id, {"status": "running"}

    def resume_run(self, run_id: str, value, context: dict) -> dict:
        run = self.dao.get_run(run_id)
        if run is None:
            return {"error": "run 不存在"}
        if run.status != "paused":
            return {"error": f"run 状态为 {run.status}，非 paused，无法续跑"}
        wf = self.dao.get_workflow(run.workflow_id)
        if wf is None:
            return {"error": "工作流不存在"}
        try:
            graph = self._get_graph(wf)
        except Exception as ex:
            return {"error": f"编译失败: {ex}"}

        self.executor.submit(self._run_resume_task, graph, run_id, wf.workflow_id, value, context or {})
        return {"status": "resuming"}

    def _run_invoke_task(self, graph, run_id, workflow_id, input, context):
        try:
            result = self.runner.invoke(graph, run_id, workflow_id, input, context, self.dao)
            self._update_run_from_result(run_id, result, workflow_id)
        except Exception as ex:
            logger.exception("invoke task failed: %s", run_id)
            self.dao.update_run_status(run_id, "error", error=str(ex))

    def _run_resume_task(self, graph, run_id, workflow_id, value, context):
        try:
            result = self.runner.resume(graph, run_id, workflow_id, value, context)
            self._update_run_from_result(run_id, result, workflow_id)
        except Exception as ex:
            logger.exception("resume task failed: %s", run_id)
            self.dao.update_run_status(run_id, "error", error=str(ex))

    def _update_run_from_result(self, run_id, result, workflow_id):
        status = result.get("status", "error")
        if status == "paused":
            self.dao.update_run_status(run_id, "paused",
                                       loop_kind=result.get("loop_kind"),
                                       interrupt_info=result.get("payload", {}))
        elif status == "completed":
            self.dao.update_run_status(run_id, "completed",
                                       output=result.get("payload", {}).get("result", {}),
                                       completed_at=datetime.now())
        elif status == "error":
            self.dao.update_run_status(run_id, "error",
                                       error=result.get("payload", {}).get("error", ""))

        # one_shot 自动删除：run 到终态后，若定义标记 one_shot，自动清理
        if status in ("completed", "error", "cancelled"):
            wf = self.dao.get_workflow(workflow_id)
            if wf and (wf.spec or {}).get("one_shot"):
                self._cleanup_run(run_id)
                active = self.dao.list_runs(workflow_id=workflow_id, status="active")
                if not active:
                    self.dao.delete_workflow(workflow_id)
                    self._graph_cache = {k: v for k, v in self._graph_cache.items()
                                         if not k.startswith(f"{workflow_id}:")}
                    logger.info("one_shot workflow %s auto-deleted after run %s", workflow_id, run_id)

    def _cleanup_run(self, run_id: str):
        """删除 run 的 LangGraph checkpoint（checkpoints + writes 表）+ run 记录。"""
        try:
            from dao.db import get_connection
            with get_connection() as conn:
                conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (run_id,))
                conn.execute("DELETE FROM writes WHERE thread_id = ?", (run_id,))
        except Exception:
            logger.warning("checkpoint cleanup failed for %s", run_id)
        self.dao.delete_run(run_id)

    # ---- SubAgent 内联 ----

    def run_subagent_inline(self, subagent_id: str, task: str, context: dict | None = None) -> str:
        """SubAgent 内联执行（worker 线程内，不 yield）。"""
        agent = self._subagents.get(subagent_id)
        if agent is None:
            return f"❌ SubAgent 不存在: {subagent_id}"
        return agent.run(task, context)

    # ---- 监督 ----

    def inspect_run(self, run_id: str) -> dict | None:
        run = self.dao.get_run(run_id)
        if run is None:
            return None
        return run.to_dict()

    def cancel_run(self, run_id: str) -> tuple[bool, str]:
        run = self.dao.get_run(run_id)
        if run is None:
            return False, "run 不存在"
        if run.status in ("completed", "cancelled"):
            return False, f"run 已 {run.status}"
        self.dao.update_run_status(run_id, "cancelled", completed_at=datetime.now())
        return True, "已取消"

    def list_runs(self, workflow_id: str | None = None, status: str | None = None,
                  limit: int = 50) -> list[WorkflowRun]:
        return self.dao.list_runs(workflow_id=workflow_id, status=status, limit=limit)

    def inject_run(self, run_id: str, message: str, context: dict) -> dict:
        """向暂停的 run 注入控制消息并续跑（带控制语义的 resume）。"""
        return self.resume_run(run_id, message, context)
