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

"""Skill system 注入中间件。"""

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage

from agent.skill import get_skill_manager
from config import get_global_config


class MemoryMiddleware(AgentMiddleware):
    """每次模型调用前注入技能目录和活跃技能全文。"""

    def __init__(self, memory_manager, base_prompt: str, skill_manager=None, *, live_config=False):
        self.live_config = live_config
        self.memory_manager = memory_manager
        self.skill_manager = skill_manager
        self.base_prompt = base_prompt            # 固定为 BASE_SYSTEM_PROMPT

    def wrap_model_call(self, request, handler):
        # 技能摘要 + 活跃全文：每轮现算（不缓存）--本回合 load_skill/unload_skill/enable/disable 会改变
        manager = self.skill_manager
        if self.live_config:
            cfg = get_global_config()
            manager = get_skill_manager() if cfg.ENABLE_SKILLS else None
        skill_summary = manager.get_skill_summary_text() if manager else ""
        active_section = manager.build_active_section() if manager else ""
        content = self.base_prompt
        if skill_summary:
            content += "\n\n" + skill_summary
        if active_section:
            content += "\n\n" + active_section
        return handler(request.override(system_message=SystemMessage(content=content)))
