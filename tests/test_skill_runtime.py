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
跨平台与安全单元测试（test_skill_runtime）

覆盖：_venv_python 跨平台解析（Windows Scripts/、POSIX bin/）、run_skill_script
路径围栏（../../ 越界拒绝）、args 走 shlex.split 列表传递且无 shell=True、
ENABLE_SKILL_SCRIPT 工具守卫、load_skill 依赖未就绪时不安装（不阻塞）。
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import dao.db as _db
from agent.skill.manager import SkillManager, _get_skill_dir, _venv_python
from agent.tools.skill_tool import create_skill_tools


class _SkillRuntimeTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        _db._global_db_path = Path(self._tmpdir) / "test.db"
        import agent.skill as _as
        _as._global_skill_manager = None
        self.skills_dir = Path(_get_skill_dir())

    def tearDown(self):
        _db._global_db_path = None
        import agent.skill as _as
        _as._global_skill_manager = None

    def _make_skill(self, name: str, runtime: str | None = None) -> Path:
        d = self.skills_dir / f"{name}-1.0.0"
        d.mkdir(exist_ok=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n---\n# s\n", encoding="utf-8")
        if runtime == "python":
            (d / "requirements.txt").write_text("requests\n", encoding="utf-8")
        return d

    def _new_mgr(self) -> SkillManager:
        return SkillManager()


class TestVenvPythonCrossPlatform(unittest.TestCase):
    def test_windows_uses_scripts(self):
        with patch("os.name", "nt"):
            self.assertIn("Scripts", _venv_python(Path("/v")))
            self.assertIn("python.exe", _venv_python(Path("/v")))

    def test_posix_uses_bin(self):
        from pathlib import PurePosixPath
        with patch("os.name", "posix"):
            p = _venv_python(PurePosixPath("/v"))
            self.assertIn("bin", p)
            self.assertNotIn("Scripts", p)


class TestRunScriptSecurity(_SkillRuntimeTestCase):
    def test_path_containment_rejects_escape(self):
        self._make_skill("a")  # 无 runtime -> deps_status="无依赖"，仍做路径围栏
        mgr = self._new_mgr()
        out = mgr.run_script("a", "../../etc/passwd")
        self.assertIn("越界", out)

    def test_path_containment_rejects_missing_script(self):
        self._make_skill("a")
        mgr = self._new_mgr()
        out = mgr.run_script("a", "nope.py")
        self.assertIn("不存在", out)

    def test_no_runtime_skill_rejects_execution(self):
        self._make_skill("a")
        d = self.skills_dir / "a-1.0.0"
        (d / "scripts").mkdir(exist_ok=True)
        (d / "scripts" / "foo.py").write_text("print('hi')", encoding="utf-8")
        mgr = self._new_mgr()
        out = mgr.run_script("a", "scripts/foo.py")
        self.assertIn("无运行时", out)

    def test_python_script_uses_list_args_no_shell(self):
        d = self._make_skill("a", runtime="python")
        (d / "scripts").mkdir(exist_ok=True)
        (d / "scripts" / "foo.py").write_text("print('hi')", encoding="utf-8")
        mgr = self._new_mgr()
        # 写 .installed marker 让 deps_status="已安装"
        venv_dir = mgr._venv_dir("a")
        venv_dir.mkdir(parents=True, exist_ok=True)
        (venv_dir / ".installed").write_text("x", encoding="utf-8")
        with patch("agent.skill.manager.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=b"output", stderr=b"")
            result = mgr.run_script("a", "scripts/foo.py", "--x y")
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        cmd = args[0]
        self.assertIsInstance(cmd, list)             # 列表传递，非字符串
        self.assertIn("--x", cmd)                    # shlex.split 拆分
        self.assertIn("y", cmd)
        self.assertNotIn("shell", kwargs)            # 无 shell=True
        self.assertIn("output", result)


class TestLoadSkillDepsNotReadyNoInstall(_SkillRuntimeTestCase):
    def test_returns_setup_prompt_without_install(self):
        self._make_skill("a", runtime="python")
        mgr = self._new_mgr()
        with patch("agent.skill.manager.subprocess.run") as mock_run:
            msg = mgr.load_skill("a")
        self.assertIn("/skills setup", msg)          # 提示 setup
        self.assertFalse(mgr.is_active("a"))         # 未激活
        mock_run.assert_not_called()                 # 不安装（不阻塞）


class TestEnableSkillScriptGate(unittest.TestCase):
    def test_default_no_run_skill_script(self):
        mgr = MagicMock()
        tools = create_skill_tools(mgr, enable_script=False)
        self.assertEqual([t.name for t in tools], ["load_skill", "unload_skill"])

    def test_enabled_includes_run_skill_script(self):
        mgr = MagicMock()
        tools = create_skill_tools(mgr, enable_script=True)
        names = [t.name for t in tools]
        self.assertIn("run_skill_script", names)
        self.assertIn("load_skill", names)

    def test_none_manager_returns_empty(self):
        self.assertEqual(create_skill_tools(None), [])


if __name__ == "__main__":
    unittest.main()
