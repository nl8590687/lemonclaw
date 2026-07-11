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
持久化记忆业务层

``MemoryManager`` 是唯一的记忆业务入口；DAO 只做纯 SQL；工具与命令都经由
``MemoryManager``（或 ``AgentService`` 委托方法）访问记忆。
"""

from agent.memory.manager import MemoryManager
from agent.memory.middleware import MemoryMiddleware

_global_memory_manager: MemoryManager | None = None


def get_memory_manager() -> MemoryManager:
    """
    获取全局 ``MemoryManager`` 单例。

    AgentService 与 Agent 记忆工具共享同一实例，保证检索索引与状态一致。

    Returns:
        全局唯一的 MemoryManager 实例
    """
    global _global_memory_manager
    if _global_memory_manager is None:
        _global_memory_manager = MemoryManager()
    return _global_memory_manager


__all__ = ["MemoryManager", "get_memory_manager", "MemoryMiddleware"]
