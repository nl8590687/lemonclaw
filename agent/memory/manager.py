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
持久化记忆管理器（门面模式）

P1：核心记忆 CRUD。
后续阶段在此类上增量补充：
- P2：会话/消息生命周期（on_session_start/on_messages/on_session_end/reconstruct_messages/reopen_session/recent_session_id）
- P3：长期记忆块与检索（add_chunk/delete_chunk/get_chunk/list_chunks/search）
- P4：上下文注入（build_context）与自动归档
"""

from datetime import datetime

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from agent.memory.extractor import MemoryExtractor
from agent.memory.retriever import MemorySearcher
from config import get_global_config
from dao.memory import (
    CoreMemory,
    CoreMemoryDAO,
    MemoryChunk,
    MemoryChunkDAO,
    MemoryMessage,
    MemoryMessageDAO,
    MemorySession,
    MemorySessionDAO,
    ensure_memory_schema,
)


class MemoryManager:
    """持久化记忆管理器（门面）"""

    def __init__(self):
        ensure_memory_schema()
        self.session_dao = MemorySessionDAO()
        self.message_dao = MemoryMessageDAO()
        self.chunk_dao = MemoryChunkDAO()
        self.core_dao = CoreMemoryDAO()
        self.current_session_id: int | None = None
        self._persisted_msg_ids: set[str] = set()
        self.searcher = MemorySearcher()
        self.extractor = MemoryExtractor()
        self._load_chunks_to_searcher()
        # middleware 在 AgentService 接入

    # ============ 核心记忆 ============

    def remember(
        self,
        key: str,
        value: str,
        memory_type: str = "fact",
        description: str | None = None,
    ) -> bool:
        """写入（或更新）一条核心记忆"""
        now = datetime.now()
        mem = CoreMemory(
            memory_type=memory_type,
            key=key,
            value=value,
            description=description,
            is_user_edited=True,
            created_at=now,
            updated_at=now,
        )
        return self.core_dao.upsert(mem)

    def forget(self, memory_type: str, key: str) -> bool:
        """删除一条核心记忆"""
        return self.core_dao.delete(memory_type, key)

    def get_core_memory(self, memory_type: str, key: str) -> CoreMemory | None:
        """查看单条核心记忆"""
        return self.core_dao.get(memory_type, key)

    def list_core_memory(self, memory_type: str | None = None) -> list[CoreMemory]:
        """列出核心记忆（可选按类型过滤）"""
        return self.core_dao.list_all(memory_type)

    def format_core_memory_for_prompt(self) -> str:
        """格式化核心记忆为注入提示词的字符串"""
        memories = self.list_core_memory()
        if not memories:
            return ""
        lines = ["【核心记忆】"]
        current_type = None
        for m in memories:
            if m.memory_type != current_type:
                current_type = m.memory_type
                lines.append(f"\n[{current_type}]")
            lines.append(f"  {m.key}: {m.value}")
            if m.description:
                lines.append(f"    ({m.description})")
        return "\n".join(lines)

    # ============ 会话与消息（短期记忆） ============

    def on_session_start(self) -> int:
        """开启新会话，返回 session_id"""
        self.current_session_id = self.session_dao.create()
        self._persisted_msg_ids = set()
        return self.current_session_id

    def on_messages(self, messages: list[BaseMessage]) -> None:
        """持久化消息（按 LangGraph 消息 id 去重，避免跨轮重复写入）"""
        if self.current_session_id is None:
            return
        for m in messages:
            if isinstance(m, SystemMessage):
                continue
            mid = getattr(m, "id", None)
            if mid and mid in self._persisted_msg_ids:
                continue
            role, tool_name, tool_args, tool_call_id = self._map_message(m)
            content = m.content if isinstance(m.content, str) else str(m.content)
            self.message_dao.add(MemoryMessage(
                id=None,
                session_id=self.current_session_id,
                role=role,
                content=content,
                timestamp=datetime.now(),
                tool_name=tool_name,
                tool_args=tool_args,
                tool_call_id=tool_call_id,
            ))
            if mid:
                self._persisted_msg_ids.add(mid)

    def on_session_end(self, messages: list[BaseMessage] | None = None,
                       fast: bool = False) -> None:
        """结束当前会话：写入 end_time、标记归档；按配置自动抽取摘要与记忆块。

        - ``fast=True``（程序退出用）：跳过 LLM，仅用统计版回退抽取，且不重载
          检索索引（进程即将退出），保证退出近即时。
        - ``fast=False``（/clear、/resume 用）：复用 ContextAgent 生成摘要、
          LLM 抽取记忆块（失败回退统计版），最后重载检索索引。
        """
        if self.current_session_id is None:
            return
        sid = self.current_session_id
        cfg = get_global_config()
        summary: str | None = None
        chunks: list[dict] = []
        if cfg.MEMORY_AUTO_ARCHIVE and messages:
            try:
                if fast:
                    summary, keywords = self.extractor.extract_session_summary_simple(messages)
                    chunks = self.extractor.extract_chunks_simple(messages, summary, keywords)
                else:
                    summary, _keywords = self.extractor.extract_session_summary(messages)
                    chunks = self.extractor.extract_chunks(messages)
            except Exception:
                summary = None
                chunks = []
        self.session_dao.end_session(sid, summary=summary, token_count=0)
        for chunk in chunks:
            self.chunk_dao.add(MemoryChunk(
                id=None,
                chunk_type=chunk.get("chunk_type", "fact"),
                title=chunk.get("title", ""),
                content=chunk.get("content", ""),
                keywords=chunk.get("keywords", []),
                source_session_id=sid,
                importance=chunk.get("importance", 5),
                created_at=datetime.now(),
            ))
        self.session_dao.mark_archived(sid)
        if not fast:
            self._load_chunks_to_searcher()
        self.current_session_id = None
        self._persisted_msg_ids = set()

    def reopen_session(self, session_id: int) -> bool:
        """原地续写：重开指定会话（清空 end_time/is_archived），置为当前会话。

        已有历史消息标记为已持久化，避免 on_messages 重复写入。
        """
        if not self.session_dao.reopen(session_id):
            return False
        self.current_session_id = session_id
        existing = self.message_dao.list_by_session(session_id)
        self._persisted_msg_ids = {f"mem-{session_id}-{i}" for i in range(len(existing))}
        return True

    def recent_session_id(self) -> int | None:
        """最近一次已结束会话 id（排除当前会话），供 /resume 无参数使用"""
        s = self.session_dao.recent_archived(exclude_id=self.current_session_id)
        return s.id if s else None

    def list_sessions(self, limit: int = 10) -> list[MemorySession]:
        """列出最近的会话"""
        return self.session_dao.list_recent(limit)

    def load_session_messages(self, session_id: int) -> list[MemoryMessage] | None:
        """加载某会话的全部消息；会话不存在返回 None"""
        if self.session_dao.get(session_id) is None:
            return None
        return self.message_dao.list_by_session(session_id)

    def reconstruct_messages(self, session_id: int) -> list[BaseMessage]:
        """从持久化消息重建 LangChain BaseMessage 列表（供 /resume 回放工作记忆）。

        为每条消息分配稳定 id ``mem-<sid>-<i>``，与 reopen_session 标记的已持久化
        集合对齐，避免回放后被 on_messages 重复写入。
        """
        msgs = self.message_dao.list_by_session(session_id)
        result: list[BaseMessage] = []
        for i, m in enumerate(msgs):
            msg_id = f"mem-{session_id}-{i}"
            if m.role == "human":
                result.append(HumanMessage(content=m.content, id=msg_id))
            elif m.role == "ai":
                tool_calls = None
                if m.tool_args is not None and m.tool_call_id:
                    tool_calls = [{
                        "id": m.tool_call_id,
                        "name": m.tool_name,
                        "args": m.tool_args,
                        "type": "tool_call",
                    }]
                result.append(AIMessage(content=m.content, tool_calls=tool_calls or [], id=msg_id))
            elif m.role == "tool":
                result.append(ToolMessage(
                    content=m.content,
                    tool_call_id=m.tool_call_id or "",
                    name=m.tool_name or "",
                    id=msg_id,
                ))
            # role == "system"：跳过
        return result

    @staticmethod
    def _map_message(m: BaseMessage) -> tuple[str, str | None, dict | None, str | None]:
        """LangChain 消息 -> (role, tool_name, tool_args, tool_call_id)"""
        if isinstance(m, HumanMessage):
            return ("human", None, None, None)
        if isinstance(m, AIMessage):
            tool_name, tool_args, tool_call_id = None, None, None
            tool_calls = getattr(m, "tool_calls", None)
            if tool_calls:
                tc = tool_calls[0]
                tool_name = tc.get("name")
                tool_args = tc.get("args")
                tool_call_id = tc.get("id")
            return ("ai", tool_name, tool_args, tool_call_id)
        if isinstance(m, ToolMessage):
            return ("tool", getattr(m, "name", None), None, getattr(m, "tool_call_id", None))
        return ("system", None, None, None)

    # ============ 长期记忆块（检索） ============

    def _load_chunks_to_searcher(self) -> None:
        """加载长期记忆块到检索索引（按重要性+时间取上限）"""
        cfg = get_global_config()
        self.searcher.clear()
        for chunk in self.chunk_dao.list_all(limit=cfg.MEMORY_MAX_SEARCH_CHUNKS):
            self.searcher.add_chunk(chunk)

    def add_chunk(self, chunk_type: str, title: str, content: str,
                  keywords: list[str] | None = None, importance: int = 5,
                  source_session_id: int | None = None) -> int:
        """添加长期记忆块，返回 chunk id"""
        cid = self.chunk_dao.add(MemoryChunk(
            id=None,
            chunk_type=chunk_type,
            title=title,
            content=content,
            keywords=keywords or [],
            source_session_id=source_session_id,
            importance=importance,
            created_at=datetime.now(),
        ))
        self._load_chunks_to_searcher()
        return cid

    def delete_chunk(self, chunk_id: int) -> bool:
        """删除长期记忆块"""
        ok = self.chunk_dao.delete(chunk_id)
        if ok:
            self._load_chunks_to_searcher()
        return ok

    def get_chunk(self, chunk_id: int) -> MemoryChunk | None:
        """查看单条长期记忆块"""
        return self.chunk_dao.get(chunk_id)

    def list_chunks(self, limit: int = 20) -> list[MemoryChunk]:
        """列出长期记忆块（按重要性+时间倒序）"""
        return self.chunk_dao.list_all(limit)

    def search(self, query: str, top_k: int = 5) -> list[tuple[MemoryChunk, float]]:
        """检索相关长期记忆块；命中时更新 access_count / last_access"""
        results = self.searcher.search(query, top_k=top_k)
        for chunk, _ in results:
            if chunk.id is not None:
                self.chunk_dao.update_access(chunk.id)
        return results

    # ============ 上下文注入 ============

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """粗略估算 token 数（每 2 字符约 1 token）"""
        if not text:
            return 0
        return len(text) // 2 + 1

    def _recent_sessions_context(self, limit: int | None = None) -> str:
        """最近会话摘要（排除当前会话）"""
        cfg = get_global_config()
        limit = limit or cfg.MEMORY_RECENT_SESSIONS
        sessions = self.session_dao.list_recent(limit + 1)
        if self.current_session_id:
            sessions = [s for s in sessions if s.id != self.current_session_id]
        sessions = sessions[:limit]
        if not sessions:
            return ""
        lines = ["【最近历史会话】"]
        for s in sessions:
            time_str = s.start_time.strftime("%Y-%m-%d %H:%M") if s.start_time else "?"
            summary = s.summary or "无摘要"
            lines.append(f"  - [{time_str}] 会话 #{s.id}: {summary}")
        return "\n".join(lines)

    def _format_chunks_for_prompt(
        self, results: list[tuple[MemoryChunk, float]], remaining_tokens: int = 1000
    ) -> str:
        """将检索结果格式化为提示词（带 Token 控制）"""
        lines = ["【相关历史记忆】"]
        total = self.estimate_tokens("\n".join(lines))
        for chunk, score in results:
            record_lines = [
                f"\n[{chunk.chunk_type}] (重要性: {chunk.importance}/10, 相关度: {score:.2f})",
                f"  {chunk.title}",
            ]
            content = chunk.content
            if len(content) > 200:
                content = content[:200] + "..."
            record_lines.append(f"  {content}")
            record_text = "\n".join(record_lines)
            if total + self.estimate_tokens(record_text) > remaining_tokens:
                continue
            lines.extend(record_lines)
            total += self.estimate_tokens(record_text)
        return "\n".join(lines) if len(lines) > 1 else ""

    def build_context(self, query: str, max_tokens: int | None = None) -> str:
        """组装记忆上下文：核心记忆 + 最近会话摘要 + 检索块（Token 受控裁剪）。

        注入优先级：核心记忆 > 最近会话摘要 > 检索块；超额按优先级裁剪。
        本方法只读检索（searcher.search），不更新 access_count。
        """
        cfg = get_global_config()
        max_tokens = max_tokens or cfg.MEMORY_MAX_CONTEXT_TOKENS
        parts: list[str] = []
        total = 0
        # 1. 核心记忆（优先级最高）
        core = self.format_core_memory_for_prompt()
        if core:
            t = self.estimate_tokens(core)
            if total + t < max_tokens:
                parts.append(core)
                total += t
        # 2. 最近会话摘要
        recent = self._recent_sessions_context()
        if recent:
            t = self.estimate_tokens(recent)
            if total + t < max_tokens:
                parts.append(recent)
                total += t
        # 3. 检索相关长期记忆
        if query:
            results = self.searcher.search(query, top_k=5)
            if results:
                chunks_ctx = self._format_chunks_for_prompt(results, max_tokens - total)
                if chunks_ctx:
                    t = self.estimate_tokens(chunks_ctx)
                    if total + t < max_tokens:
                        parts.append(chunks_ctx)
                        total += t
        if parts:
            return "\n\n" + "\n\n".join(parts) + "\n\n"
        return ""
