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
技能加载/卸载/执行工具集（供 AI Agent 主动管理技能活跃集）

- load_skill        激活技能（加入活跃集，全文由中间件每轮注入）
- unload_skill      卸载技能（移出活跃集）
- run_skill_script  在技能隔离环境执行脚本（受 ENABLE_SKILL_SCRIPT 控制）
"""

from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr

from agent.skill import SkillManager


# ==================== 工具输入模型 ====================

class LoadSkillInput(BaseModel):
    skill_name: str = Field(..., description="要激活的技能名称（须与可用技能列表完全一致）")


class UnloadSkillInput(BaseModel):
    skill_name: str = Field(..., description="要卸载的技能名称")


class RunSkillScriptInput(BaseModel):
    skill_name: str = Field(..., description="技能名称")
    script: str = Field(..., description="技能目录内的脚本相对路径，如 scripts/foo.py")
    args: str = Field(default="", description="传给脚本的命令行参数")


# ==================== 工具实现 ====================

class _BaseSkillTool(BaseTool):
    """技能工具基类：持有 SkillManager 单例"""
    _manager: SkillManager = PrivateAttr()

    def __init__(self, manager: SkillManager, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._manager = manager


class LoadSkillTool(_BaseSkillTool):
    name: str = "load_skill"
    description: str = """激活指定技能，将其完整指令注入后续上下文（由系统每轮自动注入，无需重复调用）。
仅在需要执行复杂任务、且可用技能列表中有匹配项时调用。用完请调用 unload_skill 卸载以节省上下文。"""
    args_schema: Type[BaseModel] = LoadSkillInput

    def _run(self, skill_name: str, *args, **kwargs) -> str:
        try:
            return self._manager.load_skill(skill_name)
        except Exception as e:
            return f"❌ 激活技能失败: {e}"


class UnloadSkillTool(_BaseSkillTool):
    name: str = "unload_skill"
    description: str = """卸载已激活的技能，使其指令不再注入后续上下文。任务完成或切换语境时调用以节省上下文。"""
    args_schema: Type[BaseModel] = UnloadSkillInput

    def _run(self, skill_name: str, *args, **kwargs) -> str:
        try:
            return self._manager.unload_skill(skill_name)
        except Exception as e:
            return f"❌ 卸载技能失败: {e}"


class RunSkillScriptTool(_BaseSkillTool):
    name: str = "run_skill_script"
    description: str = """在技能的隔离环境（Python venv / Node node_modules）中执行技能脚本。
技能正文应引导调用本工具而非 bash_cmd，以确保使用技能自带依赖。"""
    args_schema: Type[BaseModel] = RunSkillScriptInput

    def _run(self, skill_name: str, script: str, args: str = "", *_args, **kwargs) -> str:
        try:
            return self._manager.run_script(skill_name, script, args)  # 含路径围栏 + 无 shell + 跨平台
        except Exception as e:
            return f"❌ 执行技能脚本失败: {e}"


def create_skill_tools(manager: SkillManager | None, enable_script: bool = False) -> list:
    """创建技能工具集；manager 为 None 时返回空列表。
    enable_script=False（默认）时不注册 run_skill_script（受 ENABLE_SKILL_SCRIPT 控制）。"""
    if manager is None:
        return []
    tools = [LoadSkillTool(manager), UnloadSkillTool(manager)]
    if enable_script:
        tools.append(RunSkillScriptTool(manager))
    return tools
