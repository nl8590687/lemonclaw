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
SubAgent 层：BaseSubAgent 基类 + GeneralSubAgent + 注册表

所有 SubAgent 继承 BaseSubAgent，统一 run(task, context) -> str 接口；
子类通过 build() 定制工具/提示/图。SubAgent 在 workflow worker 线程内联执行（不 yield）。
"""

import logging
import uuid
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.checkpoint.memory import MemorySaver

from config import get_global_config

logger = logging.getLogger(__name__)


class BaseSubAgent:
    """SubAgent 基类：统一接口 + 公共运行机制（fresh 记忆、ephemeral）。

    子类通过 build() 定制工具/提示/图；通过 impl_type 标识类型。
    """

    impl_type: str = "base"

    def __init__(self, subagent_id: str, llm, *, system_prompt: str, tools: list,
                 model=None):
        self.subagent_id = subagent_id
        self.llm = llm
        self.system_prompt = system_prompt
        self.tools = tools                     # 须不含 workflow_*（builder 编译期校验）
        self.model = model
        self._agent = self.build()             # 编译期一次性构造并缓存

    def build(self):
        """构造 create_agent 实例。子类可覆盖以定制图（多节点/子图/专用工具）。"""
        return create_agent(
            model=self.model or self.llm,
            tools=self.tools,
            system_prompt=self.system_prompt,
            checkpointer=MemorySaver(),         # ephemeral；每 run 用新 thread_id 隔离
        )

    def run(self, task: str, context: dict | None = None) -> str:
        """以独立 fresh thread_id 跑一次 ReAct，返回最终回复文本。

        公共机制，子类一般不覆盖。在 workflow worker 线程内联调用（不 yield 到主循环）。
        """
        thread_id = f"sa_{self.subagent_id}_{uuid.uuid4().hex[:8]}"
        try:
            result = self._agent.invoke(
                {"messages": [HumanMessage(content=task)]},
                config={"configurable": {"thread_id": thread_id}},
            )
            msgs = result.get("messages", [])
            if msgs and isinstance(msgs[-1], AIMessage):
                return msgs[-1].content or ""
            if msgs:
                return str(msgs[-1].content)
            return ""
        except Exception as ex:
            logger.exception("SubAgent %s run failed", self.subagent_id)
            return f"❌ SubAgent {self.subagent_id} 执行出错: {ex}"


class GeneralSubAgent(BaseSubAgent):
    """通用 SubAgent：主 Agent 动态裁剪配置（system_prompt/tools/skills）构建（§1.7）。

    tools 由主 Agent 从自身注册表按名选取（不含 workflow_*），
    skills 指令正文由 builder 追加进 system_prompt。
    """

    impl_type = "general"


# ---- 专用 SubAgent（后续迭代实现，本特性仅预留基类与注册机制）----
# class BrowserSubAgent(BaseSubAgent):
#     impl_type = "browser"
#     # 内置浏览器工具集 + 专用 system_prompt
# class SSHSubAgent(BaseSubAgent):
#     impl_type = "ssh"
#     # 内置 SSH 工具集 + 专用 system_prompt

# SubAgent 实现注册表：impl_type -> 类
SUBAGENT_REGISTRY: dict[str, type[BaseSubAgent]] = {
    "general": GeneralSubAgent,
}


def get_subagent_class(impl_type: str) -> type[BaseSubAgent] | None:
    """从注册表取 SubAgent 类。未知类型返回 None。"""
    return SUBAGENT_REGISTRY.get(impl_type or "general")
