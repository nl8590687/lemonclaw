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
command.py /skills 命令集成测试

覆盖 /skills list/show/enable/disable/unload/setup/reload/help 解析与输出、
ENABLE_SKILLS=false 降级。用 mock AgentService + out_chan，不依赖 LLM。
"""

import io
import unittest
from unittest.mock import MagicMock, patch

from rich.console import Console

from command import _handle_skills
from dao.skill import Skill


class _FakeOut:
    """用 rich.Console 渲染 Table/Panel/str，便于断言文本内容。"""

    def __init__(self):
        self.outputs = []

    def _render(self, content) -> str:
        buf = io.StringIO()
        Console(file=buf, width=200).print(content)
        return buf.getvalue()

    def write_menu_content(self, content):
        self.outputs.append(self._render(content))

    def write_system_error(self, msg):
        self.outputs.append(self._render(msg))


class TestSkillsCommands(unittest.TestCase):
    def setUp(self):
        self.out = _FakeOut()
        self.svc = MagicMock()
        self.svc.is_skills_enabled.return_value = True

    def _run(self, cmd: str) -> str:
        self.out.outputs.clear()
        _handle_skills(self.out, self.svc, cmd)
        return "\n".join(self.out.outputs)

    def test_disabled_feature(self):
        self.svc.is_skills_enabled.return_value = False
        out = self._run("/skills")
        self.assertIn("未启用", out)

    def test_list(self):
        self.svc.list_skills.return_value = [Skill(name="a", version="1.0", description="da", enabled=True)]
        with patch("agent.skill.get_skill_manager") as gsm:
            gsm.return_value.is_active.return_value = False
            out = self._run("/skills list")
        self.assertIn("a", out)

    def test_enable(self):
        self.svc.enable_skill.return_value = True
        self._run("/skills enable a")
        self.svc.enable_skill.assert_called_once_with("a")

    def test_enable_missing_arg(self):
        out = self._run("/skills enable")
        self.assertIn("用法", out)

    def test_disable(self):
        self.svc.disable_skill.return_value = True
        self._run("/skills disable a")
        self.svc.disable_skill.assert_called_once_with("a")

    def test_unload(self):
        self.svc.unload_skill.return_value = "✅ 已卸载"
        self._run("/skills unload a")
        self.svc.unload_skill.assert_called_once_with("a")

    def test_setup(self):
        self.svc.setup_skill_deps.return_value = (True, "依赖已就绪")
        out = self._run("/skills setup a")
        self.svc.setup_skill_deps.assert_called_once_with("a")
        self.assertIn("依赖已就绪", out)

    def test_reload(self):
        self.svc.list_skills.return_value = []
        self._run("/skills reload")
        self.svc.reload_skills.assert_called_once()

    def test_help(self):
        out = self._run("/skills help")
        self.assertIn("Skills 命令", out)

    def test_show_not_found(self):
        self.svc.get_skill.return_value = None
        out = self._run("/skills show nope")
        self.assertIn("不存在", out)

    def test_show(self):
        self.svc.get_skill.return_value = Skill(
            name="a", version="1.0", description="da", dir_path="/x",
            required_envs=["K"], enabled=True)
        with patch("agent.skill.get_skill_manager") as gsm:
            gsm.return_value.registry.get_full_content.return_value = "内容预览"
            out = self._run("/skills show a")
        self.assertIn("a", out)
        self.assertIn("K", out)  # 显示所需环境变量

    def test_unknown_subcommand_falls_to_help(self):
        out = self._run("/skills xyz")
        self.assertIn("Skills 命令", out)


if __name__ == "__main__":
    unittest.main()
