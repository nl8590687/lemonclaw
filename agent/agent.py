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

from agent.llm import create_openai_llm, get_system_prompt, BASE_SYSTEM_PROMPT
from agent.tools import create_tool_list
from agent.callback import StreamingCallback
from agent.context_agent import ContextAgent
from agent.memory import get_memory_manager, MemoryMiddleware
from agent.skill import get_skill_manager
from channels.out.stdout import TerminalOutputChannel
from config import get_global_config
from dao.memory import CoreMemory


def _create_agent(llm: BaseChatModel, tools: dict[str, Any], system_prompt: SystemMessage | str, checkpointer, middleware=None):
    return create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
        middleware=middleware or (),
        checkpointer=checkpointer,
    )


class AgentService:
    def __init__(self):
        config = get_global_config()
        self.memory = get_memory_manager() if config.ENABLE_MEMORY else None
        if self.memory:
            self.memory.on_session_start()
        # 【新增】技能系统
        self.skill_manager = get_skill_manager() if config.ENABLE_SKILLS else None
        self.llm = create_openai_llm()
        self.tools = self._create_tool_list()
        self.checkpointer = MemorySaver()
        # 挂载统一上下文中间件（记忆或技能任一开启即挂载；base_prompt 固定 BASE，
        # 技能摘要与活跃全文由中间件每轮现取）
        mw = self._build_middleware()
        self.agent = _create_agent(self.llm, self.tools, get_system_prompt(), self.checkpointer, middleware=mw)
        self.session_id = "session-default"
        self.max_iterations = config.AGENT_REACT_MAX_ITERATIONS
        self.min_full_messages = config.CONTEXT_MIN_FULL_MESSAGES
        self.model_context_length = config.MODEL_CONTEXT_LENGTH
        self.model_max_tokens = config.MODEL_MAX_COMPLETION_TOKEN
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
        if self.memory:
            self.memory.on_messages(result.get("messages", []))
        return result

    def _update_stats(self, callback: StreamingCallback):
        tokens_stats = callback.tokens
        self.stats["context_tokens"]["total_prompt_tokens"] += tokens_stats["prompt_tokens"]
        self.stats["context_tokens"]["total_completion_tokens"] += tokens_stats["completion_tokens"]
        self.stats["context_tokens"]["context_total_tokens"] += tokens_stats["total_tokens"]

        mem_stats = self.get_memory_stats()
        self.stats["context_messages"]["memory_tokens"] = tokens_stats["memory_tokens"]
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

    def _build_middleware(self) -> list:
        """构造上下文中间件并刷新 self._middleware 引用。
        记忆或技能任一开启 -> 挂载 MemoryMiddleware（base_prompt 固定 BASE_SYSTEM_PROMPT，
        技能摘要与活跃全文由中间件每轮现取）；两者均关 -> 返回 []。"""
        need_mw = bool(self.memory or self.skill_manager)
        if not need_mw:
            self._middleware = None
            return []
        mw = [MemoryMiddleware(self.memory, BASE_SYSTEM_PROMPT, skill_manager=self.skill_manager)]
        self._middleware = mw[0]
        return mw

    def _rebuild_agent(self):
        """重建工作记忆：新 MemorySaver + 重建 agent（含中间件）+ 重置统计。
        修复：原实现未传 middleware，导致 /clear、/resume 后记忆与技能注入丢失；
        现复用 _build_middleware() 重新挂载。"""
        self.checkpointer = MemorySaver()
        mw = self._build_middleware()
        self.agent = _create_agent(self.llm, self.tools, get_system_prompt(), self.checkpointer, middleware=mw)
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

    def _current_messages(self) -> list:
        """获取当前工作记忆中的消息（供 on_session_end 归档用）"""
        try:
            state = self.agent.get_state(
                {"configurable": {"thread_id": self.session_id}}
            )
            return state.values.get("messages", [])
        except Exception:
            return []

    def reset_session(self):
        """清空当前会话上下文（/clear）：归档当前会话 -> 重建工作记忆 -> 开新会话"""
        if self.memory:
            try:
                self.memory.on_session_end(self._current_messages())
            except Exception as ex:
                self.default_out_chan.write_system_error(f"memory archive error: {ex}")
        if self.skill_manager:
            self.skill_manager.reset_active()
        self._rebuild_agent()
        if self.memory:
            self.memory.on_session_start()

    def resume_session(self, session_id: int | None) -> bool:
        """原地续写指定会话（/resume）。

        session_id 为 None 时取最近一次已结束会话。流程：归档当前会话 ->
        重开目标会话 -> 重建工作记忆并回放历史消息。后续新消息记入目标会话。
        """
        if self.memory is None:
            return False
        target = session_id or self.memory.recent_session_id()
        if target is None:
            return False
        # 1. 归档当前会话（与 /clear 一致）
        try:
            self.memory.on_session_end(self._current_messages())
        except Exception as ex:
            self.default_out_chan.write_system_error(f"memory archive error: {ex}")
        # 2. 原地续写目标会话：重置其 end_time/is_archived，置为当前会话
        if not self.memory.reopen_session(target):
            return False
        # 3. 重建工作记忆并回放目标会话历史消息
        self._rebuild_agent()
        msgs = self.memory.reconstruct_messages(target)
        if msgs:
            self.agent.update_state(
                {"configurable": {"thread_id": self.session_id}},
                {"messages": msgs},
            )
        return True

    # ============ Skills 技能系统委托 ============

    def is_skills_enabled(self) -> bool:
        return self.skill_manager is not None

    def list_skills(self) -> list:
        if not self.skill_manager:
            return []
        return self.skill_manager.list_skills()

    def get_skill(self, name: str):
        if not self.skill_manager:
            return None
        return self.skill_manager.get_skill(name)

    def enable_skill(self, name: str) -> bool:
        if not self.skill_manager:
            return False
        return self.skill_manager.enable(name)

    def disable_skill(self, name: str) -> bool:
        if not self.skill_manager:
            return False
        return self.skill_manager.disable(name)

    def load_skill(self, name: str) -> str:
        if not self.skill_manager:
            return "技能功能未启用"
        return self.skill_manager.load_skill(name)

    def unload_skill(self, name: str) -> str:
        if not self.skill_manager:
            return "技能功能未启用"
        return self.skill_manager.unload_skill(name)

    def setup_skill_deps(self, name: str) -> tuple[bool, str]:
        if not self.skill_manager:
            return False, "技能功能未启用"
        return self.skill_manager.setup_deps(name)

    def run_skill_script(self, name: str, script: str, args: str = "") -> str:
        if not self.skill_manager:
            return "技能功能未启用"
        return self.skill_manager.run_script(name, script, args)

    def reload_skills(self) -> None:
        """热加载：仅 skill_manager.reload()；摘要与活跃全文由中间件下轮现取自动反映。"""
        if not self.skill_manager:
            return
        self.skill_manager.reload()

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
            if msg_count > self.min_full_messages and self.stats["context_messages"]["memory_tokens"] >= 0.8 * self.model_context_length:
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

    # ============ 持久化记忆委托（供 command.py 调用） ============

    def list_core_memory(self, memory_type: str | None = None) -> list[CoreMemory]:
        """列出核心记忆（memory_type 为 None 时列出全部）"""
        if self.memory is None:
            return []
        return self.memory.list_core_memory(memory_type)

    def get_core_memory(self, memory_type: str, key: str) -> CoreMemory | None:
        """查看单条核心记忆"""
        if self.memory is None:
            return None
        return self.memory.get_core_memory(memory_type, key)

    def remember(self, key: str, value: str, memory_type: str = "fact",
                 description: str | None = None) -> bool:
        """写入/更新核心记忆"""
        if self.memory is None:
            return False
        return self.memory.remember(key, value, memory_type, description)

    def forget(self, memory_type: str, key: str) -> bool:
        """删除核心记忆"""
        if self.memory is None:
            return False
        return self.memory.forget(memory_type, key)

    def list_sessions(self, limit: int = 10) -> list:
        """列出最近的会话"""
        if self.memory is None:
            return []
        return self.memory.list_sessions(limit)

    def load_session_messages(self, session_id: int):
        """加载某会话的全部消息；未启用记忆或会话不存在返回 None"""
        if self.memory is None:
            return None
        return self.memory.load_session_messages(session_id)

    def list_chunks(self, limit: int = 20) -> list:
        """列出长期记忆块"""
        if self.memory is None:
            return []
        return self.memory.list_chunks(limit)

    def get_chunk(self, chunk_id: int):
        """查看单条长期记忆块"""
        if self.memory is None:
            return None
        return self.memory.get_chunk(chunk_id)

    def add_chunk(self, chunk_type: str, title: str, content: str, importance: int = 5):
        """添加长期记忆块，返回 chunk id（未启用记忆返回 None）"""
        if self.memory is None:
            return None
        return self.memory.add_chunk(chunk_type, title, content, importance=importance,
                                     source_session_id=self.memory.current_session_id)

    def delete_chunk(self, chunk_id: int) -> bool:
        """删除长期记忆块"""
        if self.memory is None:
            return False
        return self.memory.delete_chunk(chunk_id)

    def search_memory(self, query: str, top_k: int = 5) -> list:
        """检索长期记忆块，返回 [(chunk, score), ...]"""
        if self.memory is None:
            return []
        return self.memory.search(query, top_k=top_k)
