"""同库附件登记，按来源会话限定引用范围。"""
import json
import time
import uuid

from dao.db import get_connection


def attachment_scope(context):
    return json.dumps([context.get('source') or 'terminal', context.get('chat_id') or '',
                       context.get('open_id') or '', context.get('session_key') or ''], ensure_ascii=False)


class AttachmentDAO:
    def __init__(self):
        with get_connection() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS attachments (
                attachment_id TEXT PRIMARY KEY, scope TEXT NOT NULL,
                message_id TEXT NOT NULL, image_index INTEGER NOT NULL,
                metadata TEXT NOT NULL, selection_state TEXT NOT NULL DEFAULT 'pending',
                created_at REAL NOT NULL, pending_expires_at REAL NOT NULL,
                UNIQUE(scope, message_id, image_index))''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_attachment_scope ON attachments(scope, selection_state)')

    def register(self, metadata, context, index=0, ttl=1800):
        scope = attachment_scope(context)
        message_id = metadata.get('message_id') or uuid.uuid4().hex
        aid = 'img-' + uuid.uuid4().hex[:12]
        with get_connection() as conn:
            conn.execute('''INSERT OR IGNORE INTO attachments
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)''',
                (aid, scope, message_id, index, json.dumps(metadata, ensure_ascii=False), time.time(), time.time() + ttl))
            row = conn.execute('SELECT attachment_id, metadata FROM attachments WHERE scope=? AND message_id=? AND image_index=?',
                               (scope, message_id, index)).fetchone()
        return dict(json.loads(row['metadata']), attachment_id=row['attachment_id'])

    def get(self, aid, context):
        with get_connection() as conn:
            row = conn.execute('SELECT metadata FROM attachments WHERE attachment_id=? AND scope=?',
                               (aid, attachment_scope(context))).fetchone()
        if row is None:
            raise ValueError(f'图片不存在或不属于当前会话: {aid}')
        return dict(json.loads(row['metadata']), attachment_id=aid)

    def pending(self, context):
        with get_connection() as conn:
            rows = conn.execute('''SELECT attachment_id, metadata FROM attachments
                WHERE scope=? AND selection_state='pending' AND pending_expires_at>?
                ORDER BY created_at, image_index''', (attachment_scope(context), time.time())).fetchall()
        return [dict(json.loads(r['metadata']), attachment_id=r['attachment_id']) for r in rows]

    def for_message(self, message_id, context):
        with get_connection() as conn:
            rows = conn.execute('SELECT attachment_id, metadata FROM attachments WHERE scope=? AND message_id=? ORDER BY image_index',
                                (attachment_scope(context), message_id)).fetchall()
        return [dict(json.loads(r['metadata']), attachment_id=r['attachment_id']) for r in rows]

    def mark(self, aids, context, state):
        with get_connection() as conn:
            conn.executemany('UPDATE attachments SET selection_state=? WHERE attachment_id=? AND scope=?',
                             [(state, aid, attachment_scope(context)) for aid in aids])
