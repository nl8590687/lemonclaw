"""Authenticated, same-origin API for the single LemonClaw owner."""

import asyncio
import hashlib
import hmac
import json
import secrets
import time
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from agent.media.images import register_image
from agent.questions import validate_answers
from channels.bus import EventType, get_bus
from channels.device.feishu import sync_owner_question
from channels.webui import state
from channels.webui.management import operation
from channels.webui.packages import MAX_BYTES, install, stage
from config import get_global_config, runtime
from dao.attachment import AttachmentDAO
from dao.db import get_connection
from dao.question import QuestionDAO
from dao.webui import WebStore

OWNER = dict(source="webui", session_key="session-default", _webui_owner=True)
STATIC_MEDIA_TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".html": "text/html"}


def ensure_key():
    cfg = get_global_config()
    if not cfg.WEBUI_AUTH_KEY.get_secret_value():
        runtime.save({"WEBUI_AUTH_KEY": secrets.token_urlsafe(32)})
    return cfg.WEBUI_AUTH_KEY.get_secret_value()


def fingerprint():
    return hashlib.sha256(ensure_key().encode()).hexdigest()


def cookie_valid(value):
    if not value:
        return False
    with get_connection() as c:
        c.execute("CREATE TABLE IF NOT EXISTS webui_auth (token TEXT PRIMARY KEY, fingerprint TEXT NOT NULL)")
        row = c.execute(
            "SELECT fingerprint FROM webui_auth WHERE token=?", (hashlib.sha256(value.encode()).hexdigest(),)
        ).fetchone()
    return bool(row and hmac.compare_digest(row[0], fingerprint()))


def require_idle():
    if state.service is None:
        raise HTTPException(503, "Agent is initializing")
    if state.busy.is_set():
        raise HTTPException(409, "Agent busy; retry at the next call boundary")
    return state.service


class Message(BaseModel):
    text: str = Field(default="", max_length=200000)
    attachments: list[str] = Field(default_factory=list, max_length=20)
    request_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex, min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_-]+$"
    )


def create_app(dist: Path):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    ensure_key()

    @app.middleware("http")
    async def auth(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/"):
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                origin = request.headers.get("origin")
                if (
                    not origin
                    or urlsplit(origin).netloc != request.headers.get("host")
                    or urlsplit(origin).scheme != request.url.scheme
                ):
                    return JSONResponse({"detail": "Origin check failed"}, status_code=403)
            if path not in ("/api/v1/auth/login", "/api/v1/health") and not cookie_valid(
                request.cookies.get("lemonclaw_auth")
            ):
                return JSONResponse({"detail": "Authentication required"}, status_code=401)
        try:
            response = await call_next(request)
        except Exception:
            raise
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = (
            "no-store" if not path.startswith("/assets/") else "public,max-age=31536000,immutable"
        )
        return response

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": runtime.redact(str(exc))}, status_code=409)

    @app.exception_handler(Exception)
    async def failure(request, exc):
        return JSONResponse({"detail": "Operation failed; inspect server logs"}, status_code=500)

    attempts = {}

    @app.post("/api/v1/auth/login")
    async def login(request: Request):
        address = request.client.host if request.client else ""
        recent = [x for x in attempts.get(address, []) if time.monotonic() - x < 60]
        if len(recent) >= 10:
            raise HTTPException(429, "Too many login attempts")
        attempts[address] = recent + [time.monotonic()]
        data = await request.json()
        if not isinstance(data.get("key"), str) or not hmac.compare_digest(data["key"].encode(), ensure_key().encode()):
            raise HTTPException(401, "Invalid key")
        token = secrets.token_urlsafe(32)
        cookie_valid(None)
        with get_connection() as c:
            c.execute("CREATE TABLE IF NOT EXISTS webui_auth (token TEXT PRIMARY KEY, fingerprint TEXT NOT NULL)")
            c.execute("INSERT INTO webui_auth VALUES(?,?)", (hashlib.sha256(token.encode()).hexdigest(), fingerprint()))
        response = JSONResponse({"authenticated": True})
        response.set_cookie(
            "lemonclaw_auth",
            token,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            max_age=60 * 60 * 24 * 365,
        )
        return response

    @app.post("/api/v1/auth/logout")
    def logout(request: Request):
        token = request.cookies.get("lemonclaw_auth", "")
        with get_connection() as c:
            c.execute("DELETE FROM webui_auth WHERE token=?", (hashlib.sha256(token.encode()).hexdigest(),))
        response = JSONResponse({"authenticated": False})
        response.delete_cookie("lemonclaw_auth")
        return response

    @app.get("/api/v1/health")
    def health():
        return {"status": "running", "ready": state.service is not None}

    @app.get("/api/v1/bootstrap")
    def bootstrap():
        return dict(
            busy=state.busy.is_set(),
            context=state.context(),
            questions=state.questions(),
            settings=runtime.settings(),
            session="session-default",
        )

    @app.get("/api/v1/conversation/context")
    def conversation():
        return dict(messages=state.context(), busy=state.busy.is_set())

    @app.post("/api/v1/conversation/messages", status_code=202)
    def send(data: Message):

        attachments = []
        for aid in data.attachments:
            item = AttachmentDAO().get(aid, OWNER)
            attachments.append(dict(item, vision_selected=item.get("type") == "image"))
        if not data.text.strip() and not attachments:
            raise ValueError("Message is empty")
        store = WebStore()
        if store.create_request(data.request_id, {"text": data.text, "attachments": attachments}):
            try:
                get_bus().publish(
                    context=dict(OWNER, request_id=data.request_id, attachments=attachments),
                    event_type=EventType.WEBUI,
                    content={"text": data.text or "请处理所选附件"},
                )
            except Exception:
                store.request(data.request_id, "failed", {"error": "Message queue full"})
                raise
            state.emit("queued", dict(request_id=data.request_id, content=data.text))
        return store.request(data.request_id)

    @app.get("/api/v1/requests/{rid}")
    def request_state(rid: str):
        result = WebStore().request(rid)
        if not result:
            raise HTTPException(404)
        return result

    @app.get("/api/v1/events")
    async def events(request: Request, after: int = 0):
        async def stream():
            cursor = max(after, int(request.headers.get("last-event-id", "0") or "0"))
            last_questions = ""
            while not await request.is_disconnected() and cookie_valid(request.cookies.get("lemonclaw_auth")):
                rows = await asyncio.to_thread(WebStore().events, cursor)
                if rows and rows[0]["id"] > cursor + 1:
                    yield "event: reset\ndata: {}\n\n"
                for row in rows:
                    cursor = row["id"]
                    yield f"id: {cursor}\nevent: update\ndata: {json.dumps(row, ensure_ascii=False)}\n\n"
                q = await asyncio.to_thread(state.questions)
                encoded = json.dumps(q, ensure_ascii=False)
                if encoded != last_questions:
                    last_questions = encoded
                    yield f"event: questions\ndata: {encoded}\n\n"
                yield ": heartbeat\n\n"
                await asyncio.sleep(0.35)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/api/v1/questions")
    def questions():
        return state.questions()

    @app.post("/api/v1/questions/{qid}/{action}")
    async def answer(qid: str, action: str, request: Request):

        store = QuestionDAO()
        row = store.get(qid)
        if not row or row["session_key"] != "session-default":
            raise HTTPException(404)
        data = await request.json()
        result = (
            {"status": "cancelled", "action": "cancel", "answers": []}
            if action == "cancel"
            else validate_answers(row["payload"], data.get("fields", {}))
            if action == "answers"
            else None
        )
        if result is None:
            raise HTTPException(404)
        store.submit(qid, result)
        row = store.get(qid)

        asyncio.create_task(asyncio.to_thread(sync_owner_question, row))
        state.emit("questions", {"question_id": qid, "status": row["status"]})
        return dict(status=row["status"], result=row["result"])

    @app.get("/api/v1/settings")
    def settings():
        return runtime.settings()

    @app.patch("/api/v1/settings")
    async def update_settings(request: Request):
        data = await request.json()
        result = runtime.save(data.get("changes", {}), data.get("revision"), custom=data.get("custom", False))
        state.emit("settings", {"revision": result["revision"]})
        return result

    @app.post("/api/v1/attachments")
    async def upload(request: Request):

        cfg = get_global_config()
        limit = cfg.FEISHU_MAX_DOWNLOAD_MB * 1024 * 1024
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                raise HTTPException(413)
            chunks.append(chunk)
        data = b"".join(chunks)
        name = Path(unquote(request.headers.get("x-file-name", "upload")).replace("\\", "/")).name
        directory = Path(cfg.FEISHU_RECEIVED_DIR)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (uuid.uuid4().hex + "-" + name[:120])
        path.write_bytes(data)
        item = dict(path=str(path), name=name, size=size, kind="文件", type="file", message_id=uuid.uuid4().hex)
        try:
            if request.headers.get("content-type", "").startswith("image/"):
                item = register_image(item, OWNER)
                item["vision_selected"] = True
            else:
                item = AttachmentDAO().register(item, OWNER, ttl=cfg.FEISHU_PENDING_FILE_TTL_SECONDS)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return item

    @app.get("/api/v1/attachments/{aid}")
    def download(aid: str):

        # Owner can download registered shared attachments, never arbitrary paths.
        with get_connection() as c:
            row = c.execute("SELECT metadata FROM attachments WHERE attachment_id=?", (aid,)).fetchone()
        if not row:
            raise HTTPException(404)
        item = json.loads(row[0])
        path = Path(item["path"])
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(
            path,
            filename=item.get("name", path.name),
            content_disposition_type="inline" if item.get("type") == "image" else "attachment",
        )

    @app.post("/api/v1/skills/packages")
    async def package_upload(request: Request):

        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_BYTES:
                raise HTTPException(413)
        return stage(bytes(data))

    @app.post("/api/v1/skills/packages/{token}/install")
    async def package_install(token: str, request: Request):
        require_idle()

        data = await request.json()
        with state.mutation_lock:
            return install(token, bool(data.get("replace")))

    @app.api_route("/api/v1/manage/{kind}", methods=["GET", "POST"])
    @app.api_route("/api/v1/manage/{kind}/{item_id:path}", methods=["GET", "PUT", "DELETE", "POST"])
    async def manage(kind: str, request: Request, item_id: str = ""):

        data = (
            await request.json()
            if request.method in ("POST", "PUT")
            or (request.method == "DELETE" and request.headers.get("content-length", "0") != "0")
            else {}
        )
        if request.method != "GET":
            require_idle()

        def perform():
            with state.mutation_lock:
                if request.method != "GET":
                    require_idle()
                return operation(kind, item_id, request.method, data)

        return await asyncio.to_thread(perform)

    @app.get("/api/{path:path}")
    def unknown(path: str):
        raise HTTPException(404)

    @app.get("/{path:path}")
    def static(path: str):
        target = (dist / path).resolve()
        if not target.is_relative_to(dist.resolve()):
            raise HTTPException(404)
        if target.is_file():
            return FileResponse(target, media_type=STATIC_MEDIA_TYPES.get(target.suffix.lower()))
        if path.startswith("assets/"):
            raise HTTPException(404)
        return FileResponse(dist / "index.html", media_type="text/html")

    return app
