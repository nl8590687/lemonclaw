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
from langchain_core.runnables import RunnableConfig

from agent.workflow.context import origin_context

logger = logging.getLogger(__name__)


def create_workflow_tools(manager) -> list:
    """创建工作流工具集。manager 为 None（ENABLE_WORKFLOW=false）时返回 []。"""
    if manager is None:
        return []

    @tool
    def workflow_define(name: str, description: str, spec: str) -> str:
        """创建或更新可复用 Workflow，适合多阶段调查、核验汇总、长任务和周期业务处理。
        先 workflow_list_defs 检查可复用定义，再按需定义并 workflow_execute 后台启动。
        llm 处理已有文本；需要自主搜索/调用工具的阶段使用 subagent，并声明 tools 与 skills。

        spec 格式示例:
        {"state_schema": [{"name": "input_text", "type": "str"}, {"name": "result", "type": "str"}],
         "nodes": [{"name": "step1", "kind": "llm", "config": {"prompt": "处理: {input_text}", "output_field": "result"}}],
         "edges": [{"src": "START", "dst": "step1"}, {"src": "step1", "dst": "END"}]}

        spec_version: 1（可省略，保存时补全）；定义期校验结构、引用和规模上限。
        state_schema: [{name, type(str/int/float/bool/list/dict), reducer?(add_messages/overwrite/append)}]
        输入字段与各节点的 output_field 均需在 state_schema 中声明。
        llm/subagent 节点可用 config.image_ids 显式选择当前来源的图片编号，
        或 image_ids_field 指向存放图片编号列表的 list 状态字段；图片仍遵循 ENABLE_VISION 配置。
        nodes kind: llm(prompt+output_field) / tool(tool_name+args+output_field) /
                    subagent(type=general, system_prompt, tools=[工具名], skills=[技能名], task, output_field) /
                    main_agent(task, output_field) / human(question, output_field) / subgraph(sub_workflow_id)
        节点 config 可设置 timeout_seconds（默认 300 秒）、max_retries（默认 0）、retry_backoff（默认 1 秒，指数退避）。
        on_error=fail|continue|compensate；continue 将失败写入 output_field 后继续，
        compensate 需配置 compensation={"tool_name": "补偿工具", "args": {...}}，在重试耗尽后执行一次。
        仅对可安全重放的节点设置重试；超时调用可能仍在运行，超时不会自动重试或补偿。
        取消在节点和模型/工具调用边界生效，已进入的阻塞调用可能继续，但返回后不会推进工作流。
        edges: [{src, dst}]，START/END 可省略（自动补）
        conditionals: [{src, router: {kind: "state_field"|"llm", field?: "..."}, mapping: {key: target}}]

        调查研究示例：state_schema 声明 topic/evidence/report 三个 str 字段；
        collect 为 subagent（tools 选择当前可用搜索/抓取工具，task="调查 {topic}，附来源与日期"，
        output_field="evidence"）；write 为 llm（prompt="核验并汇总 {evidence}"，output_field="report"）；
        edges 为 START->collect->write->END。周期任务复用此定义并用 create_cron_task 绑定。

        支持并行分支：START->A，A->B、A->C，B->D、C->D，D->END。
        B/C 为同一阶段完全独立的子任务，分别写入不同的 output_field（如 evidence_b/evidence_c），
        D 读取两者结果后汇总。只对互不依赖、互不干扰的子任务并行；
        涉及同一文件、数据库记录或外部资源的读写冲突时按依赖串行编排，避免竞态条件。
        同一步并行写同一 state 字段需要适当 reducer，且合并结果不能依赖执行顺序；优先使用独立字段。
        此示例的 B/C 在同一阶段结束后进入 D；分支深度不同时须显式设计同步汇合。

        Args:
            name: 工作流名称（唯一标识）
            description: 工作流描述
            spec: 完整 spec JSON 字符串
        """
        try:
            spec_dict = json.loads(spec) if isinstance(spec, str) else spec
        except json.JSONDecodeError as ex:
            return f"❌ spec JSON 解析失败: {ex}"
        if not isinstance(spec_dict, dict):
            return "❌ spec 必须是 JSON 对象"
        wf = manager.define_workflow(name, description, spec_dict)
        if wf.last_error:
            return f"❌ 工作流 {wf.workflow_id} 定义失败: {wf.last_error}"
        return f"✅ 工作流 {wf.workflow_id}（v{wf.version}）已定义并编译成功"

    @tool
    def workflow_execute(workflow_id: str, input: str = "{}", config: RunnableConfig = None) -> str:
        """启动后台 Workflow，立即返回 run_id；适用于已编排的多阶段/长任务。
        启动成功后向用户说明 run_id 并立即结束当前轮；工作流在后台运行，完成结果通过事件消息回传。
        等待期间禁止调用 sleep 工具或循环轮询阻塞主会话，保持主 Agent 可接收完成/暂停/错误事件。
        用户询问进度时可 workflow_inspect_run；human/main_agent 暂停用 workflow_resume 回填。

        Args:
            workflow_id: 工作流 ID 或名称
            input: 输入参数 JSON 字符串（可选，默认 {}）
        """
        try:
            input_dict = json.loads(input) if isinstance(input, str) else input
        except json.JSONDecodeError as ex:
            return f"❌ 输入 JSON 解析失败: {ex}"
        if not isinstance(input_dict, dict):
            return "❌ 输入必须是 JSON 对象"
        run_id, info = manager.start_run(workflow_id, input_dict, origin_context(config))
        if run_id is None:
            return f"❌ 启动失败: {info.get('error', '未知错误')}"
        return f"✅ 工作流已启动，run_id={run_id}。运行中...（回调时会收到工作流消息）"

    @tool
    def workflow_resume(run_id: str, value: str, config: RunnableConfig = None) -> str:
        """续跑一个暂停中的工作流 run（HITL 回复 / main_agent 回填）。

        Args:
            run_id: 工作流 run ID
            value: 续跑值（人类回复文本或主 Agent 处理结果）
        """
        result = manager.resume_run(run_id, value, origin_context(config))
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
    def workflow_inject(run_id: str, message: str, config: RunnableConfig = None) -> str:
        """向暂停的 run 注入控制消息并续跑（带控制语义的 resume）。

        Args:
            run_id: 工作流 run ID
            message: 控制消息
        """
        result = manager.inject_run(run_id, message, origin_context(config))
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
