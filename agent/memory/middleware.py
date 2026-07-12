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
上下文注入中间件（记忆 + 技能）

在每次模型调用前，把【记忆上下文 + 技能摘要 + 活跃技能全文】动态拼入 ``system_message``：
- 通过 ``request.override(system_message=...)`` 仅替换本次调用的系统消息，
  不写入 state，因此不会在 checkpointer 中逐轮累积，也不与 ``create_agent``
  的静态 ``system_prompt`` 共存为双系统消息。
- 记忆上下文按 query 缓存（同一回合 ReAct 多轮复用）；技能摘要与活跃全文每轮现算
  （不缓存，因 load_skill/unload_skill/enable/disable 可能在本回合内改变）。
- ``skill_manager=None`` 时退化为纯记忆注入（向后兼容）。
"""

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage, SystemMessage


class MemoryMiddleware(AgentMiddleware):
    """每次模型调用前，把记忆上下文动态拼入 system_message"""

    def __init__(self, memory_manager, base_prompt: str, skill_manager=None):
        self.memory_manager = memory_manager
        self.skill_manager = skill_manager
        self.base_prompt = base_prompt            # 固定为 BASE_SYSTEM_PROMPT
        self._query: str | None = None
        self._ctx: str = ""                       # 仅记忆上下文按 query 缓存

    @staticmethod
    def _latest_query(messages) -> str:
        """取最新的用户消息作为检索 query"""
        for m in reversed(messages):
            if isinstance(m, HumanMessage):
                return m.content if isinstance(m.content, str) else ""
        return ""

    def wrap_model_call(self, request, handler):
        query = self._latest_query(request.messages)
        # 记忆上下文：按 query 缓存（同一回合 ReAct 多轮复用，避免重复 TF-IDF 检索）
        if query != self._query:
            self._ctx = (
                self.memory_manager.build_context(query)
                if self.memory_manager else ""
            )
            self._query = query
        # 技能摘要 + 活跃全文：每轮现算（不缓存）--本回合 load_skill/unload_skill/enable/disable 会改变
        skill_summary = self.skill_manager.get_skill_summary_text() if self.skill_manager else ""
        active_section = self.skill_manager.build_active_section() if self.skill_manager else ""
        content = self.base_prompt
        if skill_summary:
            content += "\n\n" + skill_summary
        if active_section:
            content += "\n\n" + active_section
        if self._ctx:
            content += "\n\n" + self._ctx
        return handler(request.override(system_message=SystemMessage(content=content)))
