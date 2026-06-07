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
AI Agent Core Implements
"""

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain.agents import create_agent
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver

from agent.llm import create_openai_llm, get_system_prompt
from agent.tools import create_tool_list
from agent.callback import StreamingCallback
from channels.out.stdout import TerminalOutputChannel
from config import get_global_config


def _create_agent(llm: BaseChatModel, tools: dict[str, Any], system_prompt: SystemMessage | str, checkpointer):
    return create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
        checkpointer=checkpointer,
    )


class AgentService:
    def __init__(self):
        config = get_global_config()
        self.llm = create_openai_llm()
        self.tools = self._create_tool_list()
        self.checkpointer = MemorySaver()
        self.agent = _create_agent(self.llm, self.tools, get_system_prompt(), self.checkpointer)
        self.session_id = "session-default"
        self.max_iterations = config.AGENT_REACT_MAX_ITERATIONS
        self.default_out_chan = TerminalOutputChannel()
        self.stats = {
            "context_tokens": {
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "context_total_tokens": 0,
            },
            "context_messages": {
                "memory_tokens": 0,
                "human_count": 0,
                "ai_count": 0,
                "tool_count": 0,
                "system_count": 0,
                "message_count": 0,
            }
        }

    def _create_tool_list(self) -> dict[str, Any]:
        tools = create_tool_list()
        return tools

    def run(self, input_msg: str, context: dict):
        """
        执行一次用户查询，返回最终状态
        """
        callback = StreamingCallback(self.default_out_chan)
        result = self.agent.invoke(
            {
                "messages": [HumanMessage(content=input_msg)]},
            config = {
                "configurable": {"thread_id": self.session_id},
                "callbacks": [callback],
                "recursion_limit": self.max_iterations * 2,
            }
        )
        self._update_stats(callback)
        context["tokens"] = callback.tokens
        context["context_tokens"] = self.stats.get("context_tokens", {})
        context["messages"] = self.stats.get("context_messages", {})
        self.default_out_chan.write_message(result.get("messages", [])[-1].content, context)
        return result

    def _update_stats(self, callback: StreamingCallback):
        tokens_stats = callback.tokens
        self.stats["context_tokens"]["total_prompt_tokens"] += tokens_stats["prompt_tokens"]
        self.stats["context_tokens"]["total_completion_tokens"] += tokens_stats["completion_tokens"]
        self.stats["context_tokens"]["context_total_tokens"] += tokens_stats["total_tokens"]

        mem_stats = self.get_memory_stats()
        self.stats["context_messages"]["memory_tokens"] = mem_stats["memory_tokens"]
        self.stats["context_messages"]["human_count"] = mem_stats["human_count"]
        self.stats["context_messages"]["ai_count"] = mem_stats["ai_count"]
        self.stats["context_messages"]["tool_count"] = mem_stats["tool_count"]
        self.stats["context_messages"]["system_count"] = mem_stats["system_count"]
        self.stats["context_messages"]["message_count"] = mem_stats["message_count"]

    def get_memory_stats(self) -> dict[str, Any]:
        """
        获取当前会话的上下文记忆统计
        """
        try:
            state = self.agent.get_state(
                {"configurable": {"thread_id": self.session_id}}
            )
            messages = state.values.get("messages", [])

            # 统计不同类型的消息
            human_count = 0
            ai_count = 0
            tool_count = 0
            system_count = 0

            for msg in messages:
                if isinstance(msg, HumanMessage):
                    human_count += 1
                elif isinstance(msg, AIMessage):
                    ai_count += 1
                elif isinstance(msg, ToolMessage):
                    tool_count += 1
                elif isinstance(msg, SystemMessage):
                    system_count += 1

            return {
                "memory_tokens": 0,
                "message_count": len(messages),
                "human_count": human_count,
                "ai_count": ai_count,
                "tool_count": tool_count,
                "system_count": system_count
            }
        except Exception as e:
            return {
                "memory_tokens": 0,
                "message_count": 0,
                "human_count": 0,
                "ai_count": 0,
                "tool_count": 0,
                "system_count": 0
            }

    def reset_session(self):
        self.checkpointer = MemorySaver()
        self.agent = _create_agent(self.llm, self.tools, get_system_prompt(), self.checkpointer)
        self.stats = {
            "context_tokens": {
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "context_total_tokens": 0,
            },
            "context_messages": {
                "memory_tokens": 0,
                "human_count": 0,
                "ai_count": 0,
                "tool_count": 0,
                "system_count": 0,
                "message_count": 0,
            }
        }
