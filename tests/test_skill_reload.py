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
技能热加载回归测试（test_skill_reload）

覆盖临时技能目录新增/修改/删除后 /skills reload 的综合行为：
新技能可激活、修改内容被重新读取（不命中旧缓存）、删除技能从索引与 DB 消失、
活跃集中已删除技能被移出、活跃技能保留并获得新内容。
"""

import shutil
import tempfile
import unittest
from pathlib import Path

import dao.db as _db
from agent.skill.manager import SkillManager, _get_skill_dir


class _SkillReloadTestCase(unittest.TestCase):
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

    def _make_skill(self, name: str, body: str = "# s\n内容\n") -> Path:
        d = self.skills_dir / f"{name}-1.0.0"
        d.mkdir(exist_ok=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n---\n{body}", encoding="utf-8")
        return d

    def _new_mgr(self) -> SkillManager:
        return SkillManager()


class TestHotReload(_SkillReloadTestCase):
    def test_add_modify_delete_in_one_cycle(self):
        # 初始：a, b
        self._make_skill("a", body="# a\nA1\n")
        self._make_skill("b", body="# b\nB1\n")
        mgr = self._new_mgr()
        mgr.load_skill("a")
        self.assertEqual({s.name for s in mgr.list_skills()}, {"a", "b"})
        # 修改 a 内容、新增 c、删除 b
        (self.skills_dir / "a-1.0.0" / "SKILL.md").write_text(
            "---\nname: a\ndescription: d\n---\n# a\nA2\n", encoding="utf-8")
        self._make_skill("c", body="# c\nC1\n")
        shutil.rmtree(self.skills_dir / "b-1.0.0", ignore_errors=True)
        mgr.reload()
        self.assertEqual({s.name for s in mgr.list_skills()}, {"a", "c"})  # b 删除，c 新增
        self.assertTrue(mgr.is_active("a"))                                 # a 仍活跃
        sec = mgr.build_active_section()
        self.assertIn("A2", sec)                                            # a 新内容
        self.assertNotIn("A1", sec)
        self.assertIsNone(mgr.dao.get("b"))                                 # DB 清理

    def test_modified_content_re_read_not_old_cache(self):
        d = self._make_skill("a", body="# a\nV1\n")
        mgr = self._new_mgr()
        mgr.registry.get_full_content("a")  # 填缓存
        self.assertEqual(len(mgr.registry.full_content_cache), 1)
        (d / "SKILL.md").write_text(
            "---\nname: a\ndescription: d\n---\n# a\nV2\n", encoding="utf-8")
        mgr.reload()  # 清缓存
        self.assertEqual(len(mgr.registry.full_content_cache), 0)
        fc = mgr.registry.get_full_content("a")
        self.assertIn("V2", fc)
        self.assertNotIn("V1", fc)

    def test_reload_preserves_active_but_drops_deleted(self):
        self._make_skill("a")
        self._make_skill("b")
        mgr = self._new_mgr()
        mgr.load_skill("a")
        mgr.load_skill("b")
        shutil.rmtree(self.skills_dir / "b-1.0.0", ignore_errors=True)
        mgr.reload()
        self.assertTrue(mgr.is_active("a"))   # 保留
        self.assertFalse(mgr.is_active("b"))  # 已删除 -> 移出


if __name__ == "__main__":
    unittest.main()
