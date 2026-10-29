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

"""Skill system 注入中间件；记忆由普通记忆工具读取，不自动加入 system。"""

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage


class MemoryMiddleware(AgentMiddleware):
    """保留兼容名称和构造参数，只负责原有 Skill system 注入。"""

    def __init__(self, memory_manager, base_prompt: str, skill_manager=None):
        self.memory_manager = memory_manager
        self.skill_manager = skill_manager
        self.base_prompt = base_prompt            # 固定为 BASE_SYSTEM_PROMPT

    def wrap_model_call(self, request, handler):
        # 技能摘要 + 活跃全文：每轮现算（不缓存）--本回合 load_skill/unload_skill/enable/disable 会改变
        skill_summary = self.skill_manager.get_skill_summary_text() if self.skill_manager else ""
        active_section = self.skill_manager.build_active_section() if self.skill_manager else ""
        content = self.base_prompt
        if skill_summary:
            content += "\n\n" + skill_summary
        if active_section:
            content += "\n\n" + active_section
        return handler(request.override(system_message=SystemMessage(content=content)))
