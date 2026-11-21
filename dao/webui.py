"""Web request idempotency and bounded replay log in the existing database."""

import json
import time

from dao.db import get_connection


class WebStore:
    def __init__(self):
        with get_connection() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS webui_events (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, data TEXT NOT NULL, created REAL NOT NULL)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS webui_requests (id TEXT PRIMARY KEY, status TEXT NOT NULL, data TEXT NOT NULL, created REAL NOT NULL)"
            )
            c.execute("CREATE TABLE IF NOT EXISTS webui_layouts (id TEXT PRIMARY KEY, data TEXT NOT NULL)")

    def emit(self, kind, data):
        with get_connection() as c:
            row = c.execute(
                "INSERT INTO webui_events(kind,data,created) VALUES(?,?,?)",
                (kind, json.dumps(data, ensure_ascii=False, default=str), time.time()),
            )
            c.execute("DELETE FROM webui_events WHERE id < ?", (row.lastrowid - 5000,))
            return row.lastrowid

    def latest_event_id(self):
        with get_connection() as c:
            return c.execute("SELECT COALESCE(MAX(id), 0) FROM webui_events").fetchone()[0]

    def events(self, after, limit=200):
        with get_connection() as c:
            return [
                dict(id=r["id"], kind=r["kind"], data=json.loads(r["data"]))
                for r in c.execute("SELECT * FROM webui_events WHERE id>? ORDER BY id LIMIT ?", (after, limit))
            ]

    def request(self, rid, status=None, data=None):
        with get_connection() as c:
            if status:
                c.execute(
                    "UPDATE webui_requests SET status=? WHERE id=?",
                    (status, rid),
                )
            row = c.execute("SELECT * FROM webui_requests WHERE id=?", (rid,)).fetchone()
            return dict(row) if row else None

    def create_request(self, rid, payload=None):
        encoded = json.dumps(payload or {}, sort_keys=True, ensure_ascii=False)
        with get_connection() as c:
            created = bool(
                c.execute(
                    "INSERT OR IGNORE INTO webui_requests VALUES(?,?,?,?)", (rid, "queued", encoded, time.time())
                ).rowcount
            )
            if not created:
                row = c.execute("SELECT data FROM webui_requests WHERE id=?", (rid,)).fetchone()
                if json.loads(row[0]) != (payload or {}):
                    raise ValueError("Request ID already belongs to a different message")
            return created

    def claim(self, rid, resume=False):
        with get_connection() as c:
            return bool(
                c.execute(
                    "UPDATE webui_requests SET status='running' WHERE id=? AND (status IN ('queued','restored','waiting_human') OR (? AND status='interrupted'))",
                    (rid, resume),
                ).rowcount
            )

    def recover(self):
        """Replay only unstarted requests; in-flight side effects are never blindly replayed."""
        with get_connection() as c:
            c.execute("UPDATE webui_requests SET status='interrupted' WHERE status='running'")
            rows = [
                dict(row)
                for row in c.execute(
                    "SELECT * FROM webui_requests WHERE status IN ('queued','restored') ORDER BY created"
                )
            ]
            c.execute("UPDATE webui_requests SET status='restored' WHERE status='queued'")
        return rows

    def layout(self, wid, data=None):
        with get_connection() as c:
            if data is not None:
                c.execute("INSERT OR REPLACE INTO webui_layouts VALUES(?,?)", (wid, json.dumps(data)))
            row = c.execute("SELECT data FROM webui_layouts WHERE id=?", (wid,)).fetchone()
            return json.loads(row["data"]) if row else {}
