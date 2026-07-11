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
记忆上下文注入中间件

在每次模型调用前，把记忆上下文动态拼入 ``system_message``：
- 通过 ``request.override(system_message=...)`` 仅替换本次调用的系统消息，
  不写入 state，因此不会在 checkpointer 中逐轮累积，也不与 ``create_agent``
  的静态 ``system_prompt`` 共存为双系统消息。
- 按 query 缓存 ``build_context`` 结果，避免同一回合 ReAct 多轮重复检索。
"""

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage, SystemMessage


class MemoryMiddleware(AgentMiddleware):
    """每次模型调用前，把记忆上下文动态拼入 system_message"""

    def __init__(self, memory_manager, base_prompt: str):
        self.memory_manager = memory_manager
        self.base_prompt = base_prompt
        self._query: str | None = None
        self._ctx: str = ""

    @staticmethod
    def _latest_query(messages) -> str:
        """取最新的用户消息作为检索 query"""
        for m in reversed(messages):
            if isinstance(m, HumanMessage):
                return m.content if isinstance(m.content, str) else ""
        return ""

    def wrap_model_call(self, request, handler):
        query = self._latest_query(request.messages)
        # 同一 query 在一次回合的 ReAct 多轮中复用，避免重复 TF-IDF 检索
        if query != self._query:
            self._ctx = (
                self.memory_manager.build_context(query)
                if self.memory_manager else ""
            )
            self._query = query
        content = self.base_prompt + (("\n\n" + self._ctx) if self._ctx else "")
        return handler(request.override(system_message=SystemMessage(content=content)))
