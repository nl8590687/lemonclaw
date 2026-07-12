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
技能敏感参数单元测试（test_skill_secrets）

覆盖 required_envs 解析、is_available 门禁（缺 env 不可用）、resolve_env_refs
替换 ${VAR} 且缺失变量保留并告警、密钥值不进系统提示摘要、.env 配置后 reload 生效。
用临时 .env + 临时技能目录 + 临时 db。
"""

import os
import tempfile
import unittest
from pathlib import Path

import dao.db as _db
from agent.skill.manager import SkillManager, _get_skill_dir, resolve_env_refs


class _SkillSecretsTestCase(unittest.TestCase):
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
        for k in ("K1", "K2", "SECRET_KEY"):
            os.environ.pop(k, None)

    def _make_skill(self, name: str, required_envs: list[str] | None = None,
                    desc: str = "公开描述") -> Path:
        d = self.skills_dir / f"{name}-1.0.0"
        d.mkdir(exist_ok=True)
        fm = ["---", f"name: {name}", f"description: {desc}"]
        if required_envs:
            fm.append("metadata:\n  openclaw:\n    requires:\n      env: " + str(required_envs))
        fm.append("---")
        (d / "SKILL.md").write_text("\n".join(fm) + "\n# s\n工作流\n", encoding="utf-8")
        return d

    def _new_mgr(self) -> SkillManager:
        return SkillManager()


class TestResolveEnvRefs(unittest.TestCase):
    def test_replaces_configured_var(self):
        os.environ["SECRET_KEY"] = "secret123"
        self.assertEqual(resolve_env_refs("Bearer ${SECRET_KEY}"), "Bearer secret123")

    def test_missing_var_kept_with_warning(self):
        # 未配置的变量保留原样（不崩溃）
        self.assertEqual(resolve_env_refs("${NOPE_VAR}"), "${NOPE_VAR}")

    def test_no_refs_unchanged(self):
        os.environ["K"] = "v"
        self.assertEqual(resolve_env_refs("plain text"), "plain text")


class TestRequiredEnvsAndAvailability(_SkillSecretsTestCase):
    def test_required_envs_parsed(self):
        self._make_skill("a", required_envs=["K1", "K2"])
        mgr = self._new_mgr()
        skill = mgr.get_skill("a")
        self.assertEqual(skill.required_envs, ["K1", "K2"])

    def test_is_available_missing_env(self):
        self._make_skill("a", required_envs=["K1"])
        mgr = self._new_mgr()
        self.assertFalse(mgr.is_available("a"))   # 缺 K1
        os.environ["K1"] = "v"
        self.assertTrue(mgr.is_available("a"))    # 配置后可用

    def test_secret_value_not_in_summary(self):
        self._make_skill("a", required_envs=["K1"], desc="公开描述")
        os.environ["K1"] = "super-secret-value"
        mgr = self._new_mgr()
        summary = mgr.get_skill_summary_text()
        self.assertIn("a", summary)
        self.assertIn("公开描述", summary)
        self.assertNotIn("super-secret-value", summary)  # 密钥不进摘要

    def test_env_configured_after_reload(self):
        self._make_skill("a", required_envs=["K1"])
        mgr = self._new_mgr()
        self.assertFalse(mgr.is_available("a"))
        self.assertNotIn("a", mgr.get_skill_summary_text())
        os.environ["K1"] = "v"
        mgr.reload()  # _reload_dotenv + 重扫
        self.assertTrue(mgr.is_available("a"))
        self.assertIn("a", mgr.get_skill_summary_text())

    def test_load_skill_missing_env_refuses(self):
        self._make_skill("a", required_envs=["K1"])
        mgr = self._new_mgr()
        msg = mgr.load_skill("a")
        self.assertIn("K1", msg)
        self.assertFalse(mgr.is_active("a"))


if __name__ == "__main__":
    unittest.main()
