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
agent.skill.registry 模块单元测试

覆盖 parse_frontmatter、scan（同名覆盖、name/version 推导、required_envs、
runtime 检测）、get_full_content（拼接顺序与缓存）、get_skill_summary_text、
reload 清缓存。用临时技能目录，不依赖 LLM 与 db。
"""

import json
import tempfile
import unittest
from pathlib import Path

from agent.skill.registry import SkillRegistry, parse_frontmatter


def _write_skill(td: Path, folder: str, frontmatter: str, body: str = "# s\n",
                 extra: dict[str, str] | None = None, meta_json: dict | None = None):
    d = td / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")
    if meta_json is not None:
        (d / "_meta.json").write_text(json.dumps(meta_json), encoding="utf-8")
    for name, content in (extra or {}).items():
        (d / name).write_text(content, encoding="utf-8")
    return d


class TestParseFrontmatter(unittest.TestCase):
    def test_parses_frontmatter_and_body(self):
        fm, body = parse_frontmatter("---\nname: x\ndescription: d\ntags: [a, b]\n---\nbody here")
        self.assertEqual(fm.get("name"), "x")
        self.assertEqual(fm.get("tags"), ["a", "b"])
        self.assertEqual(body, "body here")

    def test_no_frontmatter(self):
        fm, body = parse_frontmatter("just text")
        self.assertEqual(fm, {})
        self.assertEqual(body, "just text")

    def test_malformed_yaml_returns_empty(self):
        fm, _ = parse_frontmatter("---\n: : :\n---\nbody")
        self.assertEqual(fm, {})


class TestScan(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.mkdtemp()
        self.dir = Path(self._td)

    def test_scan_detects_skills_and_missing_skill_md(self):
        _write_skill(self.dir, "a-1.0.0", "name: a\ndescription: da")
        (self.dir / "b-1.0.0").mkdir()  # 无 SKILL.md -> 跳过
        reg = SkillRegistry(str(self.dir))
        self.assertEqual([s["name"] for s in reg.list_skills()], ["a"])

    def test_scan_same_frontmatter_name_override(self):
        _write_skill(self.dir, "a-1.0.0", "name: dup\ndescription: first")
        _write_skill(self.dir, "a-1.0.1", "name: dup\ndescription: second")
        reg = SkillRegistry(str(self.dir))
        meta = reg.get_metadata("dup")
        self.assertEqual(meta["description"], "second")  # 后者覆盖

    def test_scan_name_version_derived_from_folder(self):
        _write_skill(self.dir, "no-fm-name-2.3.1", "description: d")  # frontmatter 无 name/version
        reg = SkillRegistry(str(self.dir))
        meta = reg.get_metadata("no-fm-name")
        self.assertEqual(meta["version"], "2.3.1")

    def test_scan_detects_required_envs_and_primary_env(self):
        _write_skill(self.dir, "s-1.0.0",
                     "name: s\nmetadata:\n  openclaw:\n    requires:\n      env:\n        - K1\n        - K2\n    primaryEnv: K1")
        reg = SkillRegistry(str(self.dir))
        meta = reg.get_metadata("s")
        self.assertEqual(meta["required_envs"], ["K1", "K2"])
        self.assertEqual(meta["primary_env"], "K1")

    def test_scan_detects_runtime(self):
        _write_skill(self.dir, "py-1.0.0", "name: py", extra={"requirements.txt": "requests\n"})
        _write_skill(self.dir, "node-1.0.0", "name: node", extra={"package.json": "{}"})
        reg = SkillRegistry(str(self.dir))
        self.assertTrue(reg.get_metadata("py")["runtime"]["python"])
        self.assertIsNotNone(reg.get_metadata("py")["runtime"]["python_req"])
        self.assertTrue(reg.get_metadata("node")["runtime"]["node"])
        self.assertFalse(reg.get_metadata("py")["runtime"]["node"])

    def test_scan_missing_dir_is_empty(self):
        reg = SkillRegistry(str(self.dir / "nope"))
        self.assertEqual(reg.list_skills(), [])

    def test_scan_merges_meta_json(self):
        _write_skill(self.dir, "s-1.0.0", "description: from-fm", meta_json={"slug": "from-meta", "version": "9.9"})
        reg = SkillRegistry(str(self.dir))
        meta = reg.get_metadata("from-meta")  # slug -> name
        self.assertIsNotNone(meta)
        self.assertEqual(meta["version"], "9.9")


class TestFullContent(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.mkdtemp()
        self.dir = Path(self._td)
        # 用小写文件名，避免 Windows 大小写不敏感排序与 POSIX 不一致
        _write_skill(self.dir, "s-1.0.0", "name: s", body="# S\n主文件\n",
                     extra={"aaa.md": "附加说明A", "zzz.md": "附加说明Z"})
        self.reg = SkillRegistry(str(self.dir))

    def test_full_content_order_skill_md_first_then_alphabetical(self):
        fc = self.reg.get_full_content("s")
        # SKILL.md 内容前置
        self.assertLess(fc.index("主文件"), fc.index("附加说明A"))
        # 其他 .md 按文件名字母序：aaa.md < zzz.md（大小写不敏感下仍成立）
        self.assertLess(fc.index("附加说明A"), fc.index("附加说明Z"))

    def test_full_content_cached(self):
        self.reg.get_full_content("s")
        # 第二次命中缓存（返回同一对象）
        a = self.reg.get_full_content("s")
        b = self.reg.get_full_content("s")
        self.assertIs(a, b)

    def test_reload_clears_cache(self):
        self.reg.get_full_content("s")
        self.assertEqual(len(self.reg.full_content_cache), 1)
        self.reg.reload()
        self.assertEqual(len(self.reg.full_content_cache), 0)
        # 重新读取能拿到内容
        self.assertIn("主文件", self.reg.get_full_content("s"))


class TestSummary(unittest.TestCase):
    def test_summary_format(self):
        td = Path(tempfile.mkdtemp())
        _write_skill(td, "a-1.0.0",
                     "name: a\ndescription: 描述A\ntags: [x, y]\nmetadata:\n  openclaw:\n    emoji: 🔧")
        reg = SkillRegistry(str(td))
        summary = reg.get_skill_summary_text()
        self.assertIn("你拥有以下技能", summary)
        self.assertIn("a", summary)
        self.assertIn("描述A", summary)
        self.assertIn("x, y", summary)

    def test_summary_empty_when_no_skills(self):
        reg = SkillRegistry(str(Path(tempfile.mkdtemp())))
        self.assertEqual(reg.get_skill_summary_text(), "")


if __name__ == "__main__":
    unittest.main()
