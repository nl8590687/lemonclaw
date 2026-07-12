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
Skill 业务层

``SkillManager`` 是唯一的技能业务入口；Registry 只做文件扫描/解析/缓存；
DAO 只做纯 SQL；工具与命令都经由 ``SkillManager`` 访问技能；活跃全文仅由
``MemoryMiddleware`` 在每轮模型调用时统一注入。
"""

from agent.skill.manager import SkillManager, _get_skill_dir  # noqa: F401

_global_skill_manager: SkillManager | None = None


def get_skill_manager() -> SkillManager:
    """
    获取全局 ``SkillManager`` 单例。

    AgentService 与技能工具共享同一实例，保证活跃集与索引状态一致。

    Returns:
        全局唯一的 SkillManager 实例
    """
    global _global_skill_manager
    if _global_skill_manager is None:
        _global_skill_manager = SkillManager()
    return _global_skill_manager


__all__ = ["SkillManager", "get_skill_manager"]
