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
dao.skill 模块单元测试

覆盖 SkillDAO 的 upsert（保留管理状态）/ delete_missing / set_enabled /
increment_access / get / list_all / get_enabled_set / _row_to_skill 往返。
每个用例使用独立的临时 db，不依赖 LLM，不污染 .lemonclaw/lemonclaw.db。
"""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import dao.db as _db
from dao.skill import Skill, SkillDAO, ensure_schema


class _TempDbTestCase(unittest.TestCase):
    """每个用例使用独立的临时 db，互不污染。"""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        _db._global_db_path = Path(self._tmpdir) / "test.db"
        import agent.skill as _as
        _as._global_skill_manager = None

    def tearDown(self):
        _db._global_db_path = None


class TestEnsureSchema(_TempDbTestCase):
    def test_creates_table_and_index_idempotently(self):
        ensure_schema()
        ensure_schema()  # 幂等
        with _db.get_connection() as conn:
            tables = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            indexes = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'")}
        self.assertIn("skills", tables)
        self.assertIn("idx_skills_enabled", indexes)

    def test_columns(self):
        ensure_schema()
        with _db.get_connection() as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(skills)").fetchall()]
        for c in ("name", "version", "description", "tags", "emoji", "dir_path",
                  "required_envs", "primary_env", "enabled", "access_count",
                  "last_access", "synced_at"):
            self.assertIn(c, cols)


class TestSkillDAO(_TempDbTestCase):
    def setUp(self):
        super().setUp()
        self.dao = SkillDAO()

    def _mk(self, name: str = "s1", **kw) -> Skill:
        s = Skill(name=name, version="1.0", description="d", tags=["a"],
                  dir_path="/tmp/s", required_envs=["K1"], primary_env="K1",
                  synced_at=datetime.now())
        for k, v in kw.items():
            setattr(s, k, v)
        return s

    def test_upsert_insert_and_get(self):
        self.dao.upsert_metadata(self._mk())
        s = self.dao.get("s1")
        self.assertIsNotNone(s)
        self.assertEqual(s.version, "1.0")
        self.assertEqual(s.tags, ["a"])
        self.assertEqual(s.required_envs, ["K1"])
        self.assertTrue(s.enabled)            # 默认 enabled=1
        self.assertEqual(s.access_count, 0)   # 默认 0

    def test_upsert_preserves_management_state(self):
        self.dao.upsert_metadata(self._mk())
        # 用户改管理状态 + 统计
        self.dao.set_enabled("s1", False)
        self.dao.increment_access("s1", datetime.now())
        self.dao.increment_access("s1", datetime.now())
        # 再 upsert 元数据（模拟 reload 同步）
        self.dao.upsert_metadata(self._mk(description="updated"))
        s = self.dao.get("s1")
        self.assertEqual(s.description, "updated")   # 元数据列更新
        self.assertFalse(s.enabled)                  # 管理状态保留
        self.assertEqual(s.access_count, 2)          # 统计保留

    def test_delete_missing(self):
        self.dao.upsert_metadata(self._mk("a"))
        self.dao.upsert_metadata(self._mk("b"))
        n = self.dao.delete_missing({"a"})  # 保留 a，删 b
        self.assertEqual(n, 1)
        self.assertIsNotNone(self.dao.get("a"))
        self.assertIsNone(self.dao.get("b"))

    def test_delete_missing_empty_set(self):
        self.dao.upsert_metadata(self._mk("a"))
        n = self.dao.delete_missing(set())  # 全删
        self.assertEqual(n, 1)
        self.assertIsNone(self.dao.get("a"))

    def test_set_enabled(self):
        self.dao.upsert_metadata(self._mk())
        self.assertTrue(self.dao.set_enabled("s1", False))
        self.assertFalse(self.dao.get("s1").enabled)
        self.assertTrue(self.dao.set_enabled("s1", True))
        self.assertTrue(self.dao.get("s1").enabled)
        self.assertFalse(self.dao.set_enabled("nope", True))  # 未命中

    def test_increment_access(self):
        self.dao.upsert_metadata(self._mk())
        now = datetime.now()
        self.dao.increment_access("s1", now)
        self.dao.increment_access("s1", now)
        s = self.dao.get("s1")
        self.assertEqual(s.access_count, 2)
        self.assertIsNotNone(s.last_access)
        self.assertFalse(self.dao.increment_access("nope", now))

    def test_list_all_and_get_enabled_set(self):
        self.dao.upsert_metadata(self._mk("a"))
        self.dao.upsert_metadata(self._mk("b"))
        self.dao.set_enabled("b", False)
        all_skills = self.dao.list_all()
        self.assertEqual({s.name for s in all_skills}, {"a", "b"})
        enabled = self.dao.list_all(include_disabled=False)
        self.assertEqual({s.name for s in enabled}, {"a"})
        self.assertEqual(self.dao.get_enabled_set(), {"a"})

    def test_row_to_skill_roundtrip_and_bad_json_fallback(self):
        self.dao.upsert_metadata(self._mk(tags=["x", "y"], required_envs=["E1", "E2"]))
        s = self.dao.get("s1")
        self.assertEqual(s.tags, ["x", "y"])
        self.assertEqual(s.required_envs, ["E1", "E2"])
        # 异常 JSON 回退空列表
        with _db.get_connection() as conn:
            conn.execute("UPDATE skills SET tags='not-json' WHERE name='s1'")
        s2 = self.dao.get("s1")
        self.assertEqual(s2.tags, [])


if __name__ == "__main__":
    unittest.main()
