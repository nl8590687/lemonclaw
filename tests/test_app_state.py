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
dao.app_state 模块单元测试

覆盖 KV 读写 / 覆盖 / 删除 / get_or_set 首次绑定语义。
每个用例使用独立的临时 db，不污染 .lemonclaw/lemonclaw.db。
"""

import tempfile
import unittest
from pathlib import Path

import dao.app_state as _app_state
import dao.db as _db


class _TempDbTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        _db._global_db_path = Path(self._tmpdir) / "test.db"
        _app_state._schema_ready = False

    def tearDown(self):
        _db._global_db_path = None
        _app_state._schema_ready = False


class AppStateTest(_TempDbTestCase):
    def test_set_get_overwrite_delete(self):
        self.assertIsNone(_app_state.get_state("k"))

        _app_state.set_state("k", "v1")
        self.assertEqual(_app_state.get_state("k"), "v1")

        _app_state.set_state("k", "v2")
        self.assertEqual(_app_state.get_state("k"), "v2")

        _app_state.delete_state("k")
        self.assertIsNone(_app_state.get_state("k"))

    def test_get_or_set_keeps_first_value(self):
        self.assertEqual(_app_state.get_or_set_state("k", "first"), "first")
        self.assertEqual(_app_state.get_or_set_state("k", "second"), "first")
        self.assertEqual(_app_state.get_state("k"), "first")

    def test_ensure_schema_is_idempotent(self):
        _app_state.ensure_schema()
        _app_state.ensure_schema()
        with _db.get_connection() as conn:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.assertIn("app_state", tables)


if __name__ == "__main__":
    unittest.main()
