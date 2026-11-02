"""主 Agent 人工问题的单库持久状态与原子提交。"""
import json
import secrets
import time

from dao.db import get_connection


class QuestionDAO:
    def __init__(self):
        with get_connection() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS user_questions (
                question_id TEXT PRIMARY KEY, session_key TEXT NOT NULL,
                payload TEXT NOT NULL, origin TEXT NOT NULL, user_input TEXT NOT NULL,
                nonce TEXT NOT NULL, deadline REAL NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                result TEXT, message_id TEXT, presented INTEGER NOT NULL DEFAULT 0,
                finished INTEGER NOT NULL DEFAULT 0)''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_user_questions_pending ON user_questions(finished, deadline)')

    @staticmethod
    def _decode(row):
        if row is None:
            return None
        item = dict(row)
        for key in ('payload', 'origin', 'result'):
            item[key] = json.loads(item[key]) if item[key] else None
        return item

    def create(self, question_id, session_key, payload, origin, user_input):
        with get_connection() as conn:
            conn.execute('''INSERT OR IGNORE INTO user_questions
                (question_id,session_key,payload,origin,user_input,nonce,deadline) VALUES (?,?,?,?,?,?,?)''',
                (question_id, session_key, json.dumps(payload, ensure_ascii=False),
                 json.dumps(origin, ensure_ascii=False), user_input, secrets.token_urlsafe(24),
                 time.time() + payload['timeout_seconds']))
        return self.get(question_id)

    def get(self, question_id):
        with get_connection() as conn:
            return self._decode(conn.execute('SELECT * FROM user_questions WHERE question_id=?', (question_id,)).fetchone())

    def present(self, question_id, message_id=None):
        with get_connection() as conn:
            conn.execute('UPDATE user_questions SET presented=1,message_id=? WHERE question_id=?', (message_id, question_id))

    def submit(self, question_id, result, now=None):
        now = time.time() if now is None else now
        with get_connection() as conn:
            # 到期后拒绝晚到答案；超时和用户提交只有一个可赢得状态转换。
            conn.execute('''UPDATE user_questions SET status='timeout',result=?
                WHERE question_id=? AND status='pending' AND deadline<=?''',
                (json.dumps({'status': 'timeout', 'action': 'cancel', 'answers': []}), question_id, now))
            changed = conn.execute('''UPDATE user_questions SET status=?,result=?
                WHERE question_id=? AND status='pending' AND finished=0''',
                (result['status'], json.dumps(result, ensure_ascii=False), question_id)).rowcount
        return changed == 1

    def ready(self, now=None):
        now = time.time() if now is None else now
        with get_connection() as conn:
            conn.execute('''UPDATE user_questions SET status='timeout',result=?
                WHERE status='pending' AND finished=0 AND deadline<=?''',
                (json.dumps({'status': 'timeout', 'action': 'cancel', 'answers': []}), now))
            rows = conn.execute("SELECT * FROM user_questions WHERE status!='pending' AND finished=0 ORDER BY deadline").fetchall()
        return [self._decode(row) for row in rows]

    def finish(self, question_id):
        with get_connection() as conn:
            conn.execute('UPDATE user_questions SET finished=1 WHERE question_id=?', (question_id,))

    def cancel_session(self, session_key):
        with get_connection() as conn:
            rows = conn.execute('SELECT * FROM user_questions WHERE session_key=? AND finished=0', (session_key,)).fetchall()
            conn.execute("UPDATE user_questions SET finished=1,status='cancelled',result=? WHERE session_key=? AND finished=0",
                         (json.dumps({'status': 'cancelled', 'action': 'cancel', 'answers': []}), session_key))
        return [dict(self._decode(row), status='cancelled') for row in rows]
