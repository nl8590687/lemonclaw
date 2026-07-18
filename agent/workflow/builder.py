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
构建层：spec -> CompiledStateGraph（Path A 声明式）

WorkflowBuilder.compile(wf) 据 wf.spec 构建 StateGraph：
state_schema -> 节点 -> 边 -> 条件边 -> compile(checkpointer)。
subagent 节点编译期构造 BaseSubAgent 实例并注册到 manager._subagents。
"""

import logging
from typing import Any

from langgraph.graph import StateGraph, START, END
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StateT

from agent.workflow.state import build_state_schema, render_template
from agent.workflow.nodes import make_node
from agent.workflow.subagents import GeneralSubAgent, get_subagent_class

logger = logging.getLogger(__name__)


class WorkflowBuilder:
    """spec -> CompiledStateGraph（Path A）"""

    def __init__(self, llm, tools: dict, checkpointer, manager):
        self.llm = llm
        self.tools = tools                  # {name: BaseTool}，须已剔除 workflow_*
        self.checkpointer = checkpointer
        self.manager = manager

    def compile(self, wf) -> CompiledStateGraph[StateT, Any, Any, Any]:
        """据 wf.spec 构建 StateGraph 并编译。失败抛 ValueError。"""
        spec = wf.spec or {}
        state_fields = self._normalize_state_schema(spec.get("state_schema", []))
        nodes_spec = spec.get("nodes", [])
        edges_spec = self._normalize_edges(spec.get("edges", []), nodes_spec)
        conditionals_spec = spec.get("conditionals", [])

        if not nodes_spec:
            raise ValueError("spec 无节点")

        # 1. state schema
        State = build_state_schema(state_fields)
        g = StateGraph(State)

        # 2. 节点
        for nd in nodes_spec:
            name = nd.get("name")
            kind = nd.get("kind")
            nc = self._normalize_node_config(nd)
            if not name or not kind:
                raise ValueError(f"节点定义不完整: {nd}")

            # subagent 节点：编译期构造 BaseSubAgent 并注册
            if kind == "subagent":
                sa_id = f"{wf.workflow_id}:{wf.version}:{name}"
                nc["subagent_id"] = sa_id
                self._build_subagent(sa_id, nc, name)

            fn = make_node(kind, nc, self.llm, self.tools, self.manager)
            g.add_node(name, fn)

        # 3. 边
        for ed in edges_spec:
            src = ed.get("src", "")
            dst = ed.get("dst", "")
            src = START if src == "START" else src
            dst = END if dst == "END" else dst
            g.add_edge(src, dst)

        # 4. 条件边
        for cd in conditionals_spec:
            src = cd.get("src", "")
            router_spec = cd.get("router", {})
            mapping = cd.get("mapping", {})
            # mapping 的 value 可能是 END
            resolved_mapping = {k: (END if v == "END" else v) for k, v in mapping.items()}
            router_fn = self._make_router(router_spec, list(resolved_mapping.keys()))
            g.add_conditional_edges(src, router_fn, resolved_mapping)

        # 5. 编译
        return g.compile(checkpointer=self.checkpointer)

    def _normalize_state_schema(self, raw) -> list:
        """state_schema 归一化为 [{name, type, reducer?}] 列表。
        接受三种格式：
        - list: [{name, type, reducer}]（标准）
        - dict of {name: type}: {"input_text": "str"}
        - JSON Schema: {"type":"object","properties":{...},"required":[...]}
        """
        if not raw:
            return []
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            if "properties" in raw:
                # JSON Schema
                props = raw.get("properties", {})
                return [{"name": k, "type": (v.get("type", "str") if isinstance(v, dict) else str(v))}
                        for k, v in props.items()]
            else:
                # dict of {name: type}
                return [{"name": k, "type": (v if isinstance(v, str) else "str")}
                        for k, v in raw.items()]
        return []

    def _normalize_node_config(self, nd: dict) -> dict:
        """节点 config 归一化。
        - 无 config 键时，取 node 本身（去掉 name/kind）作为 config（容错 AI 扁平写法）。
        - output_key -> output_field 别名。
        - prompt/task/question 模板支持 ${var} 语法（render_template 已兼容）。
        """
        nc = dict(nd.get("config", {}))
        if not nc:
            nc = {k: v for k, v in nd.items() if k not in ("name", "kind")}
        if "output_key" in nc and "output_field" not in nc:
            nc["output_field"] = nc.pop("output_key")
        return nc

    def _normalize_edges(self, edges: list, nodes: list) -> list:
        """边归一化：若无 START 边，自动 START->首节点；若无 END 边，自动末节点->END。"""
        edges = list(edges or [])
        node_names = [n.get("name") for n in nodes if n.get("name")]
        if not node_names:
            return edges
        has_start = any(e.get("src") == "START" for e in edges)
        has_end = any(e.get("dst") == "END" for e in edges)
        if not has_start:
            edges.insert(0, {"src": "START", "dst": node_names[0]})
        if not has_end:
            edges.append({"src": node_names[-1], "dst": "END"})
        return edges

    def _build_subagent(self, sa_id: str, nc: dict, node_name: str):
        """编译期据 nc 构造 SubAgent 实例，注册到 manager._subagents。"""
        impl_type = nc.get("type", "general")
        cls = get_subagent_class(impl_type)
        if cls is None:
            raise ValueError(f"未知 SubAgent 类型: {impl_type}")

        system_prompt = nc.get("system_prompt", "你是一个专注的子 Agent，完成分配给你的子任务。")

        # 工具裁剪：从主 Agent 工具注册表按名选取（须不含 workflow_*）
        tool_names = nc.get("tools", [])
        selected = []
        for tn in tool_names:
            if tn.startswith("workflow_"):
                raise ValueError(f"SubAgent 工具集不能含 workflow_* 工具: {tn}（递归护栏，§1.7）")
            t = self.tools.get(tn)
            if t is None:
                logger.warning("SubAgent %s 引用未知工具 %s，跳过", sa_id, tn)
                continue
            selected.append(t)

        # skills 指令追加进 system_prompt
        skills = nc.get("skills", [])
        skill_text = self._resolve_skills(skills)
        if skill_text:
            system_prompt = system_prompt + "\n\n" + skill_text

        agent = cls(sa_id, self.llm, system_prompt=system_prompt, tools=selected)
        self.manager._subagents[sa_id] = agent

    def _resolve_skills(self, skill_names: list) -> str:
        """把命中技能的指令正文拼接为文本（对齐主 Agent 技能注入）。"""
        if not skill_names:
            return ""
        try:
            from agent.skill import get_skill_manager
            sm = get_skill_manager()
            if sm is None:
                return ""
            parts = []
            for sn in skill_names:
                sk = sm.get_skill(sn)
                if sk:
                    parts.append(f"## 技能: {sn}\n{getattr(sk, 'content', '') or getattr(sk, 'description', '')}")
            return "\n\n".join(parts)
        except Exception:
            return ""

    def _make_router(self, router_spec: dict, branch_keys: list) -> callable:
        """构造条件边路由函数。router_spec.kind: llm / state_field。"""
        kind = router_spec.get("kind", "state_field")

        if kind == "state_field":
            field = router_spec.get("field", "")
            def fn(state):
                val = (state or {}).get(field)
                val_str = str(val) if val is not None else ""
                return val_str if val_str in branch_keys else (branch_keys[0] if branch_keys else END)
            return fn

        if kind == "llm":
            def fn(state):
                keys_str = " / ".join(branch_keys)
                prompt = (
                    f"根据当前工作流状态，选择下一步分支。可选分支: {keys_str}。\n"
                    f"状态: {state}\n只返回其中一个分支名，不要其他内容。"
                )
                try:
                    resp = self.llm.invoke(prompt)
                    choice = getattr(resp, "content", str(resp)).strip()
                    # 取第一个匹配的 key
                    for k in branch_keys:
                        if k in choice:
                            return k
                    return branch_keys[0] if branch_keys else END
                except Exception:
                    return branch_keys[0] if branch_keys else END
            return fn

        # 默认：取第一个分支
        def fn(state):
            return branch_keys[0] if branch_keys else END
        return fn
