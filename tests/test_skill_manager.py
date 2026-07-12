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
agent.skill.manager 模块单元测试

覆盖 load_skill（激活/去重/access 统计/依赖未就绪不安装）、unload_skill、
build_active_section（截断与顺序）、reset_active、LRU 淘汰、reload（保留活跃集 +
清理已删除/不可用）、enable/disable 过滤摘要、is_available。
用独立临时 db + 临时技能目录，不依赖 LLM。
"""

import os
import tempfile
import unittest
from pathlib import Path

import dao.db as _db
from agent.skill.manager import SkillManager, _get_skill_dir


class _SkillMgrTestCase(unittest.TestCase):
    """每个用例独立临时 db + 临时技能目录（_get_skill_dir 派生自 db 路径）。"""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        _db._global_db_path = Path(self._tmpdir) / "test.db"
        import agent.skill as _as
        _as._global_skill_manager = None
        self.skills_dir = Path(_get_skill_dir())  # <tmpdir>/skills，自动创建

    def tearDown(self):
        _db._global_db_path = None
        import agent.skill as _as
        _as._global_skill_manager = None
        # 清理可能残留的环境变量
        for k in ("K1", "K2", "FOO_KEY"):
            os.environ.pop(k, None)

    def _make_skill(self, name: str, desc: str = "d", body: str = "# s\n工作流\n",
                    required_envs: list[str] | None = None, runtime: str | None = None) -> Path:
        d = self.skills_dir / f"{name}-1.0.0"
        d.mkdir(exist_ok=True)
        fm = ["---", f"name: {name}", f"description: {desc}"]
        if required_envs:
            fm.append("metadata:\n  openclaw:\n    requires:\n      env: " + str(required_envs))
        fm.append("---")
        (d / "SKILL.md").write_text("\n".join(fm) + "\n" + body, encoding="utf-8")
        if runtime == "python":
            (d / "requirements.txt").write_text("requests\n", encoding="utf-8")
        return d

    def _new_mgr(self) -> SkillManager:
        return SkillManager()


class TestLoadUnload(_SkillMgrTestCase):
    def test_load_activates_and_increments_access(self):
        self._make_skill("a")
        mgr = self._new_mgr()
        msg = mgr.load_skill("a")
        self.assertIn("已激活", msg)
        self.assertTrue(mgr.is_active("a"))
        self.assertEqual(mgr.dao.get("a").access_count, 1)

    def test_load_repeat_dedup(self):
        self._make_skill("a")
        mgr = self._new_mgr()
        mgr.load_skill("a")
        msg = mgr.load_skill("a")
        self.assertIn("已处于激活状态", msg)
        # 第二次不重复 increment
        self.assertEqual(mgr.dao.get("a").access_count, 1)

    def test_load_nonexistent(self):
        mgr = self._new_mgr()
        self.assertIn("不存在", mgr.load_skill("nope"))

    def test_load_missing_env_refuses(self):
        self._make_skill("a", required_envs=["K1"])
        mgr = self._new_mgr()
        msg = mgr.load_skill("a")
        self.assertIn("K1", msg)
        self.assertFalse(mgr.is_active("a"))

    def test_load_deps_not_ready_returns_setup_prompt(self):
        # Python 技能、依赖未装 -> 返回 setup 提示，不激活（P2-6）
        self._make_skill("a", runtime="python")
        mgr = self._new_mgr()
        msg = mgr.load_skill("a")
        self.assertIn("/skills setup", msg)
        self.assertFalse(mgr.is_active("a"))

    def test_unload(self):
        self._make_skill("a")
        mgr = self._new_mgr()
        mgr.load_skill("a")
        msg = mgr.unload_skill("a")
        self.assertIn("已卸载", msg)
        self.assertFalse(mgr.is_active("a"))
        self.assertIn("未激活", mgr.unload_skill("a"))


class TestActiveSection(_SkillMgrTestCase):
    def test_empty_when_no_active(self):
        self._make_skill("a")
        mgr = self._new_mgr()
        self.assertEqual(mgr.build_active_section(), "")

    def test_contains_active_full_text(self):
        self._make_skill("a", body="# A\n专属指令内容\n")
        mgr = self._new_mgr()
        mgr.load_skill("a")
        sec = mgr.build_active_section()
        self.assertIn("专属指令内容", sec)
        self.assertIn("【已加载技能指令】", sec)

    def test_truncation(self):
        self._make_skill("a", body="# A\n" + ("X" * 15000))
        mgr = self._new_mgr()
        mgr.load_skill("a")
        sec = mgr.build_active_section()
        self.assertIn("[... 技能内容较长，已截断中间部分 ...]", sec)
        # 截断后不应包含完整 15000 个 X
        self.assertLess(sec.count("X"), 15000)

    def test_order_follows_lru(self):
        for i in range(3):
            self._make_skill(f"s{i}", body=f"# s{i}\n内容{i}\n")
        mgr = self._new_mgr()
        mgr.load_skill("s0")
        mgr.load_skill("s1")
        mgr.load_skill("s0")  # s0 置顶
        mgr.load_skill("s2")
        sec = mgr.build_active_section()
        # 顺序应为 s1, s0, s2（s0 被 move_to_end 后，s2 再置顶）
        self.assertLess(sec.index("内容1"), sec.index("内容0"))
        self.assertLess(sec.index("内容0"), sec.index("内容2"))


class TestResetAndLRU(_SkillMgrTestCase):
    def test_reset_active_clears(self):
        self._make_skill("a")
        mgr = self._new_mgr()
        mgr.load_skill("a")
        mgr.reset_active()
        self.assertEqual(len(mgr._active), 0)

    def test_lru_eviction(self):
        for i in range(3):
            self._make_skill(f"s{i}")
        mgr = self._new_mgr()
        mgr.max_active = 2
        mgr.load_skill("s0")
        mgr.load_skill("s1")
        msg = mgr.load_skill("s2")  # 超限，淘汰 s0
        self.assertIn("s0", msg)  # 提示被淘汰
        self.assertEqual(list(mgr._active.keys()), ["s1", "s2"])
        self.assertFalse(mgr.is_active("s0"))


class TestReload(_SkillMgrTestCase):
    def test_reload_picks_up_new_skill(self):
        mgr = self._new_mgr()
        self.assertEqual([], [s.name for s in mgr.list_skills()])
        self._make_skill("a")
        mgr.reload()
        self.assertEqual(["a"], [s.name for s in mgr.list_skills()])

    def test_reload_removes_deleted_skill(self):
        d = self._make_skill("a")
        mgr = self._new_mgr()
        self.assertEqual(["a"], [s.name for s in mgr.list_skills()])
        import shutil
        shutil.rmtree(d, ignore_errors=True)
        mgr.reload()
        self.assertEqual([], [s.name for s in mgr.list_skills()])
        self.assertIsNone(mgr.dao.get("a"))  # DB 也清理

    def test_reload_removes_deleted_from_active(self):
        d = self._make_skill("a")
        mgr = self._new_mgr()
        mgr.load_skill("a")
        self.assertTrue(mgr.is_active("a"))
        import shutil
        shutil.rmtree(d, ignore_errors=True)
        mgr.reload()
        self.assertFalse(mgr.is_active("a"))  # 已删除 -> 移出活跃集

    def test_reload_preserves_active_with_new_content(self):
        d = self._make_skill("a", body="# A\nv1\n")
        mgr = self._new_mgr()
        mgr.load_skill("a")
        self.assertIn("v1", mgr.build_active_section())
        (d / "SKILL.md").write_text("---\nname: a\ndescription: d\n---\n# A\nv2\n", encoding="utf-8")
        mgr.reload()
        self.assertTrue(mgr.is_active("a"))  # 仍活跃
        self.assertIn("v2", mgr.build_active_section())  # 内容已刷新
        self.assertNotIn("v1", mgr.build_active_section())


class TestEnableDisableSummary(_SkillMgrTestCase):
    def test_disable_filters_summary_and_removes_active(self):
        self._make_skill("a")
        mgr = self._new_mgr()
        mgr.load_skill("a")
        self.assertIn("a", mgr.get_skill_summary_text())
        mgr.disable("a")
        self.assertEqual(mgr.get_skill_summary_text(), "")  # 摘要不再含
        self.assertFalse(mgr.is_active("a"))  # disable 移出活跃集

    def test_enable_re_adds_to_summary(self):
        self._make_skill("a")
        mgr = self._new_mgr()
        mgr.disable("a")
        self.assertEqual(mgr.get_skill_summary_text(), "")
        mgr.enable("a")
        self.assertIn("a", mgr.get_skill_summary_text())

    def test_is_available(self):
        self._make_skill("a", required_envs=["K1"])
        mgr = self._new_mgr()
        self.assertFalse(mgr.is_available("a"))       # 缺 K1
        os.environ["K1"] = "v"
        self.assertTrue(mgr.is_available("a"))         # 配置后可用
        mgr.disable("a")
        self.assertFalse(mgr.is_available("a"))        # 禁用


if __name__ == "__main__":
    unittest.main()
