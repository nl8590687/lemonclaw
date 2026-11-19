"""Shared WebUI state. Output adapters do not own or duplicate the Agent."""

import json
import threading

from channels.bus import EventType, get_bus
from config.runtime import redact
from dao.db import get_connection
from dao.question import QuestionDAO
from dao.webui import WebStore

enabled = False
service = None
busy = threading.Event()
mutation_lock = threading.RLock()


def emit(kind, data):
    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [clean(v) for v in value]
        return redact(value) if isinstance(value, str) else value

    return WebStore().emit(kind, clean(data))


def context():
    if service is None:
        return []
    result = []
    for message in service._current_messages():
        if message.type == "system":
            continue
        result.append(
            dict(
                id=message.id,
                role=message.type,
                content=redact(message.content),
                attachments=[
                    dict(attachment_id=r["attachment_id"])
                    for r in message.additional_kwargs.get(
                        "lemonclaw_images", message.additional_kwargs.get("image_refs", [])
                    )
                ],
                tools=[dict(name=x.get("name"), id=x.get("id")) for x in getattr(message, "tool_calls", [])],
            )
        )
    return result


def questions():

    store = QuestionDAO()
    store.ready()  # persist elapsed deadlines even while the main agent is busy
    with get_connection() as c:
        ids = [
            r[0]
            for r in c.execute(
                "SELECT question_id FROM user_questions WHERE session_key='session-default' ORDER BY deadline DESC LIMIT 50"
            )
        ]
    return [
        dict(
            question_id=r["question_id"],
            payload=r["payload"],
            status=r["status"],
            result=r["result"],
            deadline=r["deadline"],
        )
        for qid in ids
        if (r := store.get(qid))
    ]


def recover_requests():

    for row in WebStore().recover():
        payload = json.loads(row["data"])
        if not payload.get("text") and not payload.get("attachments"):
            WebStore().request(row["id"], "failed")
            continue
        get_bus().publish(
            event_type=EventType.WEBUI,
            content={"text": payload.get("text") or "请处理所选附件"},
            context=dict(
                source="webui",
                session_key="session-default",
                _webui_owner=True,
                request_id=row["id"],
                attachments=payload.get("attachments", []),
            ),
        )
