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
工作流工具（BaseTool 包装）+ create_workflow_tools

工具：workflow_define / workflow_execute / workflow_resume / workflow_cancel /
      workflow_list / workflow_list_defs / workflow_inspect_run / workflow_inject
"""

import json
import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def create_workflow_tools(manager) -> list:
    """创建工作流工具集。manager 为 None（ENABLE_WORKFLOW=false）时返回 []。"""
    if manager is None:
        return []

    @tool
    def workflow_define(name: str, description: str, spec: str) -> str:
        """一次性给出完整 spec 创建或更新工作流（主路径，声明式 JSON）。

        spec 格式示例:
        {"state_schema": [{"name": "input_text", "type": "str"}],
         "nodes": [{"name": "step1", "kind": "llm", "config": {"prompt": "处理: {input_text}", "output_field": "result"}}],
         "edges": [{"src": "START", "dst": "step1"}, {"src": "step1", "dst": "END"}]}

        state_schema: [{name, type(str/int/float/bool/list/dict), reducer?(add_messages/overwrite/append)}]
        nodes kind: llm(prompt+output_field) / tool(tool_name+args+output_field) /
                    subagent(type=general, system_prompt, tools=[工具名], task, output_field) /
                    main_agent(task, output_field) / human(question, output_field) / subgraph(sub_workflow_id)
        edges: [{src, dst}]，START/END 可省略（自动补）
        conditionals: [{src, router: {kind: "state_field"|"llm", field?: "..."}, mapping: {key: target}}]

        Args:
            name: 工作流名称（唯一标识）
            description: 工作流描述
            spec: 完整 spec JSON 字符串
        """
        try:
            spec_dict = json.loads(spec) if isinstance(spec, str) else spec
        except json.JSONDecodeError as ex:
            return f"❌ spec JSON 解析失败: {ex}"
        wf = manager.define_workflow(name, description, spec_dict)
        if wf.last_error:
            return f"⚠️ 工作流 {wf.workflow_id} 已保存但编译失败: {wf.last_error}"
        return f"✅ 工作流 {wf.workflow_id}（v{wf.version}）已定义并编译成功"

    @tool
    def workflow_execute(workflow_id: str, input: str = "{}") -> str:
        """启动一个工作流 run（后台执行，不阻塞）。返回 run_id 与初始状态。

        Args:
            workflow_id: 工作流 ID 或名称
            input: 输入参数 JSON 字符串（可选，默认 {}）
        """
        try:
            input_dict = json.loads(input) if isinstance(input, str) else input
        except json.JSONDecodeError:
            input_dict = {}
        run_id, info = manager.start_run(workflow_id, input_dict, {})
        if run_id is None:
            return f"❌ 启动失败: {info.get('error', '未知错误')}"
        return f"✅ 工作流已启动，run_id={run_id}。运行中...（回调时会收到工作流消息）"

    @tool
    def workflow_resume(run_id: str, value: str) -> str:
        """续跑一个暂停中的工作流 run（HITL 回复 / main_agent 回填）。

        Args:
            run_id: 工作流 run ID
            value: 续跑值（人类回复文本或主 Agent 处理结果）
        """
        result = manager.resume_run(run_id, value, {})
        if "error" in result:
            return f"❌ 续跑失败: {result['error']}"
        return f"✅ run {run_id} 已续跑，继续执行中..."

    @tool
    def workflow_cancel(run_id: str) -> str:
        """取消一个工作流 run。

        Args:
            run_id: 工作流 run ID
        """
        ok, msg = manager.cancel_run(run_id)
        return f"✅ {msg}" if ok else f"❌ {msg}"

    @tool
    def workflow_list(status: str = "active") -> str:
        """列出工作流 run（运行中/阻塞中）。status: active(默认)/running/paused/all/completed/error。

        Args:
            status: 状态过滤
        """
        runs = manager.list_runs(status=status, limit=20)
        if not runs:
            return "（无匹配的 run）"
        lines = []
        for r in runs:
            line = f"  {r.run_id} | {r.workflow_id} | {r.status}"
            if r.loop_kind:
                line += f" | {r.loop_kind}"
            line += f" | {r.updated_at}"
            lines.append(line)
        return f"工作流 run（{len(runs)}）:\n" + "\n".join(lines)

    @tool
    def workflow_list_defs() -> str:
        """列出所有已定义的工作流定义。"""
        wfs = manager.list_workflows()
        if not wfs:
            return "（无工作流定义）"
        lines = []
        for w in wfs:
            err = f" ❌{w.last_error[:30]}" if w.last_error else ""
            lines.append(f"  {w.workflow_id} | {w.name} | v{w.version} | {'启用' if w.enabled else '禁用'}{err}")
        return f"工作流定义（{len(wfs)}）:\n" + "\n".join(lines)

    @tool
    def workflow_get_spec_detail(workflow_id: str) -> str:
        """查询指定工作流Spec规格定义详情"""
        wf = manager.get_workflow(workflow_id)
        if not wf:
            return f"(工作流不存在)"
        return f"工作流规格Spec:\n{json.dumps(wf.spec, ensure_ascii=False)}"

    @tool
    def workflow_inspect_run(run_id: str) -> str:
        """查看一个工作流 run 的详情（状态/中断/输出）。

        Args:
            run_id: 工作流 run ID
        """
        run = manager.inspect_run(run_id)
        if run is None:
            return f"❌ run 不存在: {run_id}"
        return json.dumps(run, ensure_ascii=False, indent=2, default=str)

    @tool
    def workflow_inject(run_id: str, message: str) -> str:
        """向暂停的 run 注入控制消息并续跑（带控制语义的 resume）。

        Args:
            run_id: 工作流 run ID
            message: 控制消息
        """
        result = manager.inject_run(run_id, message, {})
        if "error" in result:
            return f"❌ 注入失败: {result['error']}"
        return f"✅ run {run_id} 已注入控制消息并续跑"

    @tool
    def workflow_delete(workflow_id: str) -> str:
        """删除工作流定义及其所有 run（仅允许无在途 run 时删除；含 checkpoint 清理）。
        用于一次性工作流使用完毕后的清理。

        Args:
            workflow_id: 工作流 ID 或名称
        """
        ok, msg = manager.delete_workflow(workflow_id)
        return f"✅ {msg}" if ok else f"❌ {msg}"

    return [
        workflow_define, workflow_execute, workflow_resume, workflow_cancel,
        workflow_list, workflow_list_defs, workflow_get_spec_detail, workflow_inspect_run, workflow_inject,
        workflow_delete,
    ]
