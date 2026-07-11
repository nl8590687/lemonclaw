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
dao.memory 模块单元测试

覆盖 4 个 DAO 的 CRUD / upsert / reopen / 级联删除 / _row_to_* 往返。
每个用例使用独立的临时 db，不依赖 LLM，不污染 .lemonclaw/lemonclaw.db。
"""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import dao.db as _db
from dao.memory import (
    CoreMemory,
    CoreMemoryDAO,
    MemoryChunk,
    MemoryChunkDAO,
    MemoryMessage,
    MemoryMessageDAO,
    MemorySessionDAO,
    ensure_memory_schema,
)


class _TempDbTestCase(unittest.TestCase):
    """每个用例使用独立的临时 db，互不污染。"""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        _db._global_db_path = Path(self._tmpdir) / "test.db"
        # 清空 MemoryManager 单例缓存，避免跨用例串
        import agent.memory as _am
        _am._global_memory_manager = None

    def tearDown(self):
        _db._global_db_path = None


class TestEnsureSchema(_TempDbTestCase):
    def test_ensure_schema_creates_all_tables_idempotently(self):
        ensure_memory_schema()
        ensure_memory_schema()  # 幂等：再调一次不应报错
        with _db.get_connection() as conn:
            names = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        for t in ("memory_sessions", "memory_messages", "memory_chunks", "core_memory"):
            self.assertIn(t, names)


class TestCoreMemoryDAO(_TempDbTestCase):
    def setUp(self):
        super().setUp()
        self.dao = CoreMemoryDAO()

    def _mk(self, memory_type="fact", key="k", value="v"):
        now = datetime.now()
        return CoreMemory(memory_type=memory_type, key=key, value=value,
                          created_at=now, updated_at=now, is_user_edited=True)

    def test_upsert_and_get(self):
        self.assertTrue(self.dao.upsert(self._mk("preference", "lang", "中文")))
        got = self.dao.get("preference", "lang")
        self.assertIsNotNone(got)
        self.assertEqual(got.value, "中文")
        self.assertTrue(got.is_user_edited)
        self.assertEqual(got.memory_type, "preference")

    def test_upsert_updates_same_type_key(self):
        self.dao.upsert(self._mk("preference", "lang", "中文"))
        self.dao.upsert(self._mk("preference", "lang", "English"))
        self.assertEqual(self.dao.get("preference", "lang").value, "English")
        self.assertEqual(len(self.dao.list_all()), 1)  # 同 (type,key) 只一条

    def test_list_all_and_filter(self):
        self.dao.upsert(self._mk("preference", "lang", "中文"))
        self.dao.upsert(self._mk("preference", "theme", "dark"))
        self.dao.upsert(self._mk("fact", "os", "win11"))
        self.assertEqual(len(self.dao.list_all()), 3)
        self.assertEqual(len(self.dao.list_all("preference")), 2)
        self.assertEqual(len(self.dao.list_all("fact")), 1)
        self.assertEqual(len(self.dao.list_all("persona")), 0)

    def test_delete(self):
        self.dao.upsert(self._mk("preference", "lang", "中文"))
        self.assertTrue(self.dao.delete("preference", "lang"))
        self.assertIsNone(self.dao.get("preference", "lang"))
        self.assertFalse(self.dao.delete("preference", "lang"))  # 再删返回 False


class TestMemorySessionDAO(_TempDbTestCase):
    def setUp(self):
        super().setUp()
        self.dao = MemorySessionDAO()

    def test_create_and_get(self):
        sid = self.dao.create()
        self.assertIsInstance(sid, int)
        s = self.dao.get(sid)
        self.assertIsNotNone(s)
        self.assertIsNone(s.end_time)
        self.assertFalse(s.is_archived)
        self.assertEqual(s.token_count, 0)

    def test_end_archive_and_reopen(self):
        sid = self.dao.create()
        self.assertTrue(self.dao.end_session(sid, "摘要", 100))
        s = self.dao.get(sid)
        self.assertIsNotNone(s.end_time)
        self.assertEqual(s.summary, "摘要")
        self.assertEqual(s.token_count, 100)
        self.assertTrue(self.dao.mark_archived(sid))
        self.assertTrue(self.dao.get(sid).is_archived)
        # reopen：原地续写，清空 end_time、is_archived
        self.assertTrue(self.dao.reopen(sid))
        s2 = self.dao.get(sid)
        self.assertIsNone(s2.end_time)
        self.assertFalse(s2.is_archived)

    def test_list_recent_desc(self):
        a = self.dao.create()
        b = self.dao.create()
        recent = self.dao.list_recent(10)
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[0].id, b)  # 倒序：b 在前
        self.assertEqual(recent[1].id, a)


class TestMemoryMessageDAO(_TempDbTestCase):
    def setUp(self):
        super().setUp()
        self.sdao = MemorySessionDAO()
        self.mdao = MemoryMessageDAO()
        self.sid = self.sdao.create()

    def test_add_list_json_and_tool_call_id_roundtrip(self):
        now = datetime.now()
        m = MemoryMessage(id=None, session_id=self.sid, role="ai", content="call",
                          timestamp=now, tool_name="search", tool_args={"q": "你好"},
                          tool_call_id="tc-1", token_count=5)
        mid = self.mdao.add(m)
        self.assertIsInstance(mid, int)
        msgs = self.mdao.list_by_session(self.sid)
        self.assertEqual(len(msgs), 1)
        back = msgs[0]
        self.assertEqual(back.role, "ai")
        self.assertEqual(back.tool_args, {"q": "你好"})  # JSON 往返
        self.assertEqual(back.tool_call_id, "tc-1")
        self.assertEqual(back.token_count, 5)

    def test_list_order_ascending(self):
        for i in range(3):
            self.mdao.add(MemoryMessage(id=None, session_id=self.sid, role="human",
                                        content=str(i), timestamp=datetime.now()))
        msgs = self.mdao.list_by_session(self.sid)
        self.assertEqual([m.content for m in msgs], ["0", "1", "2"])

    def test_cascade_delete_with_session(self):
        self.mdao.add(MemoryMessage(id=None, session_id=self.sid, role="human",
                                    content="hi", timestamp=datetime.now()))
        with _db.get_connection() as conn:
            conn.execute("DELETE FROM memory_sessions WHERE id = ?", (self.sid,))
        self.assertEqual(len(self.mdao.list_by_session(self.sid)), 0)


class TestMemoryChunkDAO(_TempDbTestCase):
    def setUp(self):
        super().setUp()
        self.dao = MemoryChunkDAO()

    def test_add_get_keywords_roundtrip(self):
        cid = self.dao.add(MemoryChunk(
            id=None, chunk_type="fact", title="t", content="c",
            created_at=datetime.now(), keywords=["数据库", "定时任务"], importance=8))
        c = self.dao.get(cid)
        self.assertEqual(c.keywords, ["数据库", "定时任务"])
        self.assertEqual(c.importance, 8)
        self.assertEqual(c.access_count, 0)

    def test_update_access(self):
        cid = self.dao.add(MemoryChunk(id=None, chunk_type="fact", title="t", content="c",
                                       created_at=datetime.now()))
        self.dao.update_access(cid)
        self.dao.update_access(cid)
        c = self.dao.get(cid)
        self.assertEqual(c.access_count, 2)
        self.assertIsNotNone(c.last_access)

    def test_list_all_order_and_delete(self):
        self.dao.add(MemoryChunk(id=None, chunk_type="fact", title="a", content="c",
                                 created_at=datetime.now(), importance=5))
        self.dao.add(MemoryChunk(id=None, chunk_type="fact", title="b", content="c",
                                 created_at=datetime.now(), importance=9))
        items = self.dao.list_all()
        self.assertEqual(items[0].importance, 9)  # 高重要性在前
        cid = items[0].id
        self.assertTrue(self.dao.delete(cid))
        self.assertIsNone(self.dao.get(cid))
        self.assertFalse(self.dao.delete(cid))


if __name__ == "__main__":
    unittest.main()
