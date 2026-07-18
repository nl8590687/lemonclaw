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
内置节点实现

节点 kind：llm / tool / subagent / main_agent / human / subgraph
（python 节点本期不支持，待沙箱选型后与 skill 脚本统一支持，§4.6）

subagent 节点在 worker 线程内联执行（不 yield）；main_agent / human 节点 interrupt 让出。
"""

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import interrupt

from agent.workflow.state import render_template

logger = logging.getLogger(__name__)


def make_node(kind: str, nc: dict, llm, tools: dict, manager) -> callable:
    """按 kind 返回节点函数 f(state, config=None) -> dict（state 更新）。

    nc: 节点 config（spec 中的 config）；llm: 主 Agent 的 LLM；tools: {name: BaseTool}；
    manager: WorkflowManager（供 subagent 节点调 run_subagent_inline）。
    """
    if kind == "llm":
        return _llm_node(nc, llm)
    if kind == "tool":
        return _tool_node(nc, tools)
    if kind == "subagent":
        return _subagent_node(nc, manager)
    if kind == "main_agent":
        return _main_agent_node(nc)
    if kind == "human":
        return _human_node(nc)
    if kind == "subgraph":
        return _subgraph_node(nc, manager)
    raise ValueError(f"未知节点 kind: {kind}")


def _output_field(nc: dict, default: str = "output") -> str:
    return nc.get("output_field", default)


def _llm_node(nc: dict, llm):
    """render(prompt, state) -> llm.invoke -> 写入 output_field。"""
    def fn(state, config=None):
        prompt = render_template(nc.get("prompt", ""), state)
        resp = llm.invoke(prompt)
        content = getattr(resp, "content", str(resp))
        return {_output_field(nc, "output"): content}
    return fn


def _tool_node(nc: dict, tools: dict):
    """调用 tools[tool_name]，参数来自 nc.args 模板 + state，写入 output_field。"""
    def fn(state, config=None):
        tool_name = nc.get("tool_name", "")
        tool = tools.get(tool_name)
        if tool is None:
            return {_output_field(nc, "output"): f"❌ 工具不存在: {tool_name}"}
        args = nc.get("args", {})
        # 如果 args 是 JSON 字符串（AI 可能把整个参数字典写成字符串），先解析
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (ValueError, TypeError):
                pass
        if isinstance(args, dict):
            def _render_value(v, st):
                """递归渲染：只处理字符串值，列表/字典保持结构"""
                if isinstance(v, str):
                    return render_template(v, st)
                elif isinstance(v, list):
                    return [_render_value(item, st) for item in v]
                elif isinstance(v, dict):
                    return {k: _render_value(val, st) for k, val in v.items()}
                else:
                    return v
            args = {k: _render_value(v, state) for k, v in args.items()}
        try:
            result = tool.invoke(args) if args else tool.invoke({})
            return {_output_field(nc, "output"): str(result)}
        except Exception as ex:
            logger.exception("tool_node %s failed", tool_name)
            return {_output_field(nc, "output"): f"❌ 工具 {tool_name} 调用出错: {ex}"}
    return fn


def _subagent_node(nc: dict, manager):
    """在 worker 线程内联执行 SubAgent（不 yield）：run_subagent_inline -> 写入 output_field。"""
    def fn(state, config=None):
        subagent_id = nc.get("subagent_id", "")
        task = render_template(nc.get("task", nc.get("task_template", "")), state)
        reply = manager.run_subagent_inline(subagent_id, task)
        return {_output_field(nc, "agent_reply"): reply}
    return fn


def _main_agent_node(nc: dict):
    """主 Agent 自身作为节点（可选）：interrupt(need_main_agent) 让出到主循环。"""
    def fn(state, config=None):
        run_id = (config or {}).get("configurable", {}).get("thread_id", "")
        task = render_template(nc.get("task", ""), state)
        summary = render_template(nc.get("summary", ""), state)
        value = interrupt({
            "kind": "need_main_agent",
            "run_id": run_id,
            "task": task,
            "context_summary": summary,
        })
        return {_output_field(nc, "agent_reply"): value}
    return fn


def _human_node(nc: dict):
    """HITL 输入：interrupt(need_human) 让出，主 Agent 通知人，人答复经 run_id 续跑回填。"""
    def fn(state, config=None):
        run_id = (config or {}).get("configurable", {}).get("thread_id", "")
        question = render_template(nc.get("question", ""), state)
        handler = nc.get("handler", "interactive")
        value = interrupt({
            "kind": "need_human",
            "run_id": run_id,
            "question": question,
            "handler": handler,
        })
        return {_output_field(nc, "user_input"): value}
    return fn


def _subgraph_node(nc: dict, manager):
    """嵌套另一工作流作为子图（编译期静态嵌套）。子图共享同名 state key。"""
    def fn(state, config=None):
        sub_workflow_id = nc.get("sub_workflow_id", "")
        try:
            sub_graph = manager._get_graph_by_id(sub_workflow_id)
            if sub_graph is None:
                return {_output_field(nc, "output"): f"❌ 子工作流不存在: {sub_workflow_id}"}
            import uuid
            sub_thread = f"sub_{uuid.uuid4().hex[:8]}"
            result = sub_graph.invoke(
                dict(state),
                config={"configurable": {"thread_id": sub_thread}},
            )
            return {k: v for k, v in result.items() if k in (state or {})}
        except Exception as ex:
            logger.exception("subgraph_node %s failed", sub_workflow_id)
            return {_output_field(nc, "output"): f"❌ 子工作流 {sub_workflow_id} 执行出错: {ex}"}
    return fn
