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
记忆提取与摘要生成模块

- 摘要：复用 ``ContextAgent``（失败回退统计版）
- 记忆块抽取：LLM 抽取（失败回退统计版）
"""

import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from agent.context_agent import ContextAgent


MEMORY_CHUNK_PROMPT = """请从以下对话中提取值得长期记忆的关键信息。

对话内容：
{conversation}

请分析这段对话，提取以下类型的记忆片段：
1. fact - 事实信息（用户偏好、项目信息等）
2. decision - 重要决策
3. skill - 技能/工作流
4. issue - 遇到的问题及解决方案

以 JSON 数组格式返回：
[
    {{
        "type": "fact|decision|skill|issue",
        "title": "简短标题",
        "content": "详细内容",
        "keywords": ["关键词1", "关键词2"],
        "importance": 1-10
    }}
]
"""


class MemoryExtractor:
    """记忆提取器"""

    def __init__(self):
        self._context_agent: ContextAgent | None = None
        self._llm: Any = None

    @property
    def context_agent(self) -> ContextAgent:
        if self._context_agent is None:
            self._context_agent = ContextAgent()
        return self._context_agent

    def _get_llm(self):
        if self._llm is None:
            from agent.llm import create_openai_llm
            self._llm = create_openai_llm()
        return self._llm

    @staticmethod
    def _format_messages(messages: list[BaseMessage]) -> str:
        lines = []
        for m in messages:
            if isinstance(m, HumanMessage):
                role = "user"
            elif isinstance(m, AIMessage):
                role = "assistant"
                if getattr(m, "tool_calls", None):
                    role = f"assistant (工具: {m.tool_calls[0].get('name')})"
            elif isinstance(m, ToolMessage):
                role = f"tool ({getattr(m, 'name', '')})"
            else:
                role = getattr(m, "type", "unknown")
            content = m.content if isinstance(m.content, str) else str(m.content)
            lines.append(f"[{role}]\n{content}\n")
        return "\n".join(lines)

    # ---------- 摘要 ----------

    def extract_session_summary_simple(
        self, messages: list[BaseMessage]
    ) -> tuple[str, list[str]]:
        """统计版摘要（不依赖 LLM），返回 (summary, keywords)"""
        if not messages:
            return "空会话", []
        user_count = sum(1 for m in messages if isinstance(m, HumanMessage))
        ai_count = sum(1 for m in messages if isinstance(m, AIMessage))
        tool_count = sum(1 for m in messages if isinstance(m, ToolMessage))
        first_user = ""
        for m in messages:
            if isinstance(m, HumanMessage) and m.content:
                first_user = (m.content if isinstance(m.content, str) else str(m.content))[:100]
                break
        summary = (f"会话包含 {len(messages)} 条消息"
                   f"（用户: {user_count}, 助手: {ai_count}, 工具: {tool_count}）")
        if first_user:
            summary += f"。用户初始请求: {first_user}..."
        # 关键词从工具名提取
        keywords: set[str] = set()
        for m in messages:
            if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
                for tc in m.tool_calls:
                    name = tc.get("name")
                    if name:
                        keywords.add(name)
            elif isinstance(m, ToolMessage) and getattr(m, "name", None):
                keywords.add(m.name)
        return summary, list(keywords)[:5]

    def extract_session_summary(
        self, messages: list[BaseMessage]
    ) -> tuple[str, list[str]]:
        """生成会话摘要：复用 ContextAgent；失败回退 simple。返回 (summary, keywords)"""
        _, keywords = self.extract_session_summary_simple(messages)
        try:
            summary = self.context_agent.run(messages)
            if summary and summary.strip():
                return summary.strip(), keywords
        except Exception:
            pass
        summary, _ = self.extract_session_summary_simple(messages)
        return summary, keywords

    # ---------- 记忆块抽取 ----------

    def extract_chunks_simple(
        self, messages: list[BaseMessage], summary: str, keywords: list[str]
    ) -> list[dict]:
        """统计版记忆块：工具调用统计 + 会话摘要"""
        chunks: list[dict] = []
        tool_counts: dict[str, int] = {}
        for m in messages:
            name = None
            if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
                name = m.tool_calls[0].get("name") if m.tool_calls else None
            elif isinstance(m, ToolMessage):
                name = getattr(m, "name", None)
            if name:
                tool_counts[name] = tool_counts.get(name, 0) + 1
        for name, cnt in tool_counts.items():
            chunks.append({
                "chunk_type": "fact",
                "title": f"使用了工具: {name}",
                "content": f"本次会话中 {name} 被调用了 {cnt} 次",
                "keywords": [name, "工具调用"],
                "importance": 5,
            })
        if summary:
            chunks.append({
                "chunk_type": "summary",
                "title": "会话摘要",
                "content": summary,
                "keywords": keywords,
                "importance": 6,
            })
        return chunks

    def extract_chunks(self, messages: list[BaseMessage]) -> list[dict]:
        """LLM 抽取记忆块；失败回退 simple"""
        summary, keywords = self.extract_session_summary_simple(messages)
        try:
            conv = self._format_messages(messages)
            if len(conv) > 8000:
                conv = conv[:8000] + "\n... (对话过长已截断)"
            result = self._get_llm().invoke(MEMORY_CHUNK_PROMPT.format(conversation=conv))
            content = result.content if hasattr(result, "content") else str(result)
            start = content.find("[")
            end = content.rfind("]")
            if start >= 0 and end > start:
                data = json.loads(content[start:end + 1])
                chunks = [{
                    "chunk_type": item.get("type", "fact"),
                    "title": item.get("title", ""),
                    "content": item.get("content", ""),
                    "keywords": item.get("keywords", []),
                    "importance": item.get("importance", 5),
                } for item in data]
                if chunks:
                    return chunks
        except Exception:
            pass
        return self.extract_chunks_simple(messages, summary, keywords)
