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
记忆读写工具集（供 AI Agent 主动读写持久化记忆）

- recall_memory  检索长期记忆块
- remember        写入/更新核心记忆
- forget          删除核心记忆
- list_memory     列出核心记忆
- add_memory_chunk 添加长期记忆块
"""

from typing import Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr

from agent.memory import MemoryManager


# ==================== 工具输入模型 ====================

class RecallMemoryInput(BaseModel):
    query: str = Field(..., description="检索关键词或问题")
    top_k: int = Field(default=5, description="返回的最大记忆块数量，默认5")


class RememberInput(BaseModel):
    key: str = Field(..., description="记忆键名")
    value: str = Field(..., description="记忆内容")
    memory_type: str = Field(default="fact",
                             description="记忆类型：fact/preference/project/persona/skill，默认 fact")
    description: Optional[str] = Field(default=None, description="可选说明")


class ForgetInput(BaseModel):
    memory_type: str = Field(..., description="记忆类型")
    key: str = Field(..., description="记忆键名")


class ListMemoryInput(BaseModel):
    memory_type: Optional[str] = Field(default=None, description="按类型过滤，留空列出全部")


class AddMemoryChunkInput(BaseModel):
    chunk_type: str = Field(..., description="块类型：summary/fact/decision/skill/issue")
    title: str = Field(..., description="简短标题")
    content: str = Field(..., description="详细内容")
    keywords: Optional[str] = Field(default=None, description="关键词，英文逗号分隔")
    importance: int = Field(default=5, description="重要性 1-10，默认5")


# ==================== 工具实现 ====================

class _BaseMemoryTool(BaseTool):
    """记忆工具基类：持有 MemoryManager 单例"""
    _manager: MemoryManager = PrivateAttr()

    def __init__(self, manager: MemoryManager, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._manager = manager


class RecallMemoryTool(_BaseMemoryTool):
    name: str = "recall_memory"
    description: str = """检索长期记忆块。当需要回忆历史决策、事实、技能或过往会话经验时使用。
返回最相关的若干条记忆块及其相关度。"""
    args_schema: Type[BaseModel] = RecallMemoryInput

    def _run(self, query: str, top_k: int = 5, *args, **kwargs) -> str:
        try:
            results = self._manager.search(query, top_k=top_k)
            if not results:
                return f"未找到与「{query}」相关的记忆"
            lines = [f"找到 {len(results)} 条相关记忆："]
            for c, score in results:
                lines.append(f"  #{c.id} [{c.chunk_type}] (重要性{c.importance}, 相关度{score:.2f}) {c.title}")
                lines.append(f"    {c.content[:200]}")
            return "\n".join(lines)
        except Exception as e:
            return f"检索记忆失败: {e}"


class RememberTool(_BaseMemoryTool):
    name: str = "remember"
    description: str = """写入或更新一条核心记忆（KV）。用于记住用户偏好、项目知识、关键事实等需长期保留的信息。
同一 (memory_type, key) 重复写入会更新而非新增。"""
    args_schema: Type[BaseModel] = RememberInput

    def _run(self, key: str, value: str, memory_type: str = "fact",
             description: Optional[str] = None, *args, **kwargs) -> str:
        try:
            if self._manager.remember(key, value, memory_type=memory_type, description=description):
                return f"✅ 已记住 [{memory_type}] {key}: {value}"
            return "❌ 写入核心记忆失败"
        except Exception as e:
            return f"❌ 写入失败: {e}"


class ForgetTool(_BaseMemoryTool):
    name: str = "forget"
    description: str = """删除一条核心记忆。"""
    args_schema: Type[BaseModel] = ForgetInput

    def _run(self, memory_type: str, key: str, *args, **kwargs) -> str:
        try:
            if self._manager.forget(memory_type, key):
                return f"✅ 已删除 [{memory_type}] {key}"
            return f"❌ 删除失败，可能不存在: [{memory_type}] {key}"
        except Exception as e:
            return f"❌ 删除失败: {e}"


class ListMemoryTool(_BaseMemoryTool):
    name: str = "list_memory"
    description: str = """列出核心记忆（可按类型过滤）。"""
    args_schema: Type[BaseModel] = ListMemoryInput

    def _run(self, memory_type: Optional[str] = None, *args, **kwargs) -> str:
        try:
            memories = self._manager.list_core_memory(memory_type)
            if not memories:
                return "当前没有核心记忆"
            lines = []
            for m in memories:
                lines.append(f"[{m.memory_type}] {m.key}: {m.value}")
            return "\n".join(lines)
        except Exception as e:
            return f"列出记忆失败: {e}"


class AddMemoryChunkTool(_BaseMemoryTool):
    name: str = "add_memory_chunk"
    description: str = """添加一条长期记忆块。用于持久化重要决策、技能、问题解决方案等结构化经验，
供后续 recall_memory 检索复用。"""
    args_schema: Type[BaseModel] = AddMemoryChunkInput

    def _run(self, chunk_type: str, title: str, content: str,
             keywords: Optional[str] = None, importance: int = 5, *args, **kwargs) -> str:
        try:
            kw_list = [k.strip() for k in keywords.split(",")] if keywords else []
            cid = self._manager.add_chunk(chunk_type, title, content,
                                          keywords=kw_list, importance=importance)
            return f"✅ 已添加记忆块 #{cid} [{chunk_type}] {title}"
        except Exception as e:
            return f"❌ 添加记忆块失败: {e}"


# ==================== 工厂函数 ====================

def create_memory_tools(manager: MemoryManager) -> list:
    """
    创建所有记忆相关工具

    Args:
        manager: MemoryManager 实例（与 AgentService 共享单例）

    Returns:
        工具实例列表
    """
    return [
        RecallMemoryTool(manager),
        RememberTool(manager),
        ForgetTool(manager),
        ListMemoryTool(manager),
        AddMemoryChunkTool(manager),
    ]
