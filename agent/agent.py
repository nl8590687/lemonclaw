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
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage, SystemMessage, RemoveMessage
from langgraph.checkpoint.memory import MemorySaver

from agent.llm import create_openai_llm, get_system_prompt
from agent.tools import create_tool_list
from agent.callback import StreamingCallback
from agent.context_agent import ContextAgent
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
        self.min_full_messages = config.CONTEXT_MIN_FULL_MESSAGES
        self.model_max_tokens = config.MODEL_MAX_TOKEN
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
        self.stats["context_messages"]["memory_tokens"] = tokens_stats["memory_tokens"]
        #self.stats["context_messages"]["memory_tokens"] = mem_stats["memory_tokens"]
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
                "message_count": len(messages),
                "human_count": human_count,
                "ai_count": ai_count,
                "tool_count": tool_count,
                "system_count": system_count
            }
        except Exception as e:
            return {
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

    def trim_msg_history(self):
        try:
            cfg = {"configurable": {"thread_id": self.session_id}}
            state = self.agent.get_state(cfg)
            messages = state.values.get("messages", [])
            new_messages = []
            changed = False
            msg_count = len(messages)

            # trim each message content
            for idx, msg in enumerate(messages):
                # trim each tool message content
                if msg_count - idx > self.min_full_messages and isinstance(msg, ToolMessage) and msg.content and len(msg.content) > 500:
                    new_messages.append(
                        msg.model_copy(update={
                            "content": msg.content[:200] + " <full-message-has-been-trimmed> " + msg.content[-200:]
                        })
                    )
                    changed = True
                # trim each AI tool call message
                elif msg_count - idx > self.min_full_messages and isinstance(msg, AIMessage) and msg.tool_calls:
                    new_tool_calls = []
                    for tool_call in msg.tool_calls:
                        new_tool_call = {
                            "name": tool_call.get("name"),
                            "id": tool_call.get("id"),
                            "type": tool_call.get("type"),
                            "args": tool_call.get("args") or {}
                        }
                        for key, value in tool_call.get("args", {}).items():
                            if len(str(value)) > 500:
                                value_str = str(value)
                                new_tool_call["args"][key] = value_str[:200] + " <full-arg-value-was-too-long-and-has-been-trimmed> " + value_str[-200:]
                        new_tool_calls.append(new_tool_call)
                    new_messages.append(msg.model_copy(update={"tool_calls": new_tool_calls}))
                    changed = True
                else:
                    new_messages.append(msg)

            # trim total message tokens
            if msg_count > self.min_full_messages and self.stats["context_messages"]["memory_tokens"] >= 0.8 * self.model_max_tokens:
                p = len(new_messages) if self.min_full_messages == 0 else -self.min_full_messages
                need_sum_msgs = new_messages[:p]
                ctx_agent = ContextAgent()
                txt = ctx_agent.run(need_sum_msgs)
                remove_msgs = [RemoveMessage(id=msg.id) for msg in need_sum_msgs]
                new_messages = remove_msgs + [HumanMessage(content=f"稍早前对话内容摘要：\n{txt}")] + new_messages[p:]
                changed = True

            if changed:
                self.agent.update_state(cfg, {"messages": new_messages})
        except Exception as ex:
            self.default_out_chan.write_system_error(f"error: cut message history exception\n{ex}")
