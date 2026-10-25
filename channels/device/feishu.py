#!/usr/bin/env python
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
飞书（Lark）消息设备

提供两部分能力：

1. ``FeishuMessageSender`` —— 主动发送文本/Markdown/Post 消息给指定 ``open_id``
2. ``FeishuClient`` —— 通过飞书 WebSocket 长链接接收用户消息，
   解析后调用上层 ``on_message`` 回调（由 ``channels.ins.feishu.FeishuInput``
   通过该回调把事件投递到消息总线）

依赖 ``lark-oapi`` 包，未安装时本模块仅做占位（实例化时报错）。

注意：本设备本身不直接写消息总线，向 ``MessageBus`` 投递事件的逻辑
统一交给 ``channels.ins.feishu.FeishuInput`` 通过回调完成，
与 ``channels/ins/webhook.py`` 的写法保持一致。
"""

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from config import get_global_config
from dao import delete_state, get_or_set_state, get_state, set_state


# ---- lark_oapi 是可选依赖 ----
try:
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest,
        CreateMessageRequestBody,
        CreateMessageResponse,
    )
    HAS_LARK = True
except ImportError:  # pragma: no cover - 缺包时占位
    lark = None  # type: ignore[assignment]
    CreateMessageRequest = None  # type: ignore[assignment]
    CreateMessageRequestBody = None  # type: ignore[assignment]
    CreateMessageResponse = None  # type: ignore[assignment]
    HAS_LARK = False


_LARK_MISSING_MSG = (
    "lark-oapi 未安装，飞书功能不可用。请执行: pip install lark-oapi"
)


# 飞书文件上传 file_type 取值（以飞书开放平台文件上传接口为准）
_FILE_TYPE_MAP = {
    ".opus": "opus",
    ".mp4": "mp4",
    ".pdf": "pdf",
    ".doc": "doc",
    ".docx": "doc",
    ".xls": "xls",
    ".xlsx": "xls",
    ".ppt": "ppt",
    ".pptx": "ppt",
}
_IMAGE_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp",
    ".ico", ".tiff", ".tif", ".heic", ".heif",
}
_AUDIO_EXTS = {".opus"}
_VIDEO_EXTS = {".mp4"}
_MESSAGE_RESOURCE_TYPES = {"image", "file", "audio", "media"}

# 飞书开放平台上传限制（官方文档 2026-10-25 核验）：
# 图片 <= 10MB，文件 <= 30MB，且都不允许 0 字节
_MAX_IMAGE_UPLOAD_BYTES = 10 * 1024 * 1024
_MAX_FILE_UPLOAD_BYTES = 30 * 1024 * 1024


# 收到飞书消息时的回调签名（与 webhook 的 _write_message 保持兼容）：
#   (text, img_urls, context) -> event_id
MessageCallback = Callable[[str, Optional[list[str]], dict[str, object]], str]


# =====================================================================
# Markdown -> Post 富文本
# =====================================================================

def md_to_lark_post(md_text: str) -> str:
    """
    把 Markdown 文本转成飞书 Post 富文本格式。

    飞书 Post 支持 ``md`` 标签直接渲染 Markdown，这里将整段 Markdown
    放入单个 ``md`` 标签，确保代码块、表格、列表等多行语法正确渲染。

    :param md_text: Markdown 文本
    :return: 飞书 Post JSON 字符串
    """
    return json.dumps({
        "zh_cn": {
            "content": [
                [{"tag": "md", "text": md_text}]
            ]
        }
    }, ensure_ascii=False)


# =====================================================================
# 主动发送
# =====================================================================

class FeishuMessageSender:
    """飞书消息发送器（主动外呼）"""

    def __init__(self, app_id: str | None = None, app_secret: str | None = None):
        if not HAS_LARK:
            raise ImportError(_LARK_MISSING_MSG)

        config = get_global_config()
        self.app_id = app_id or (config.FEISHU_APP_ID or "")
        self.app_secret = app_secret or config.FEISHU_APP_SECRET.get_secret_value()

        if not self.app_id or not self.app_secret:
            raise ValueError("FEISHU_APP_ID / FEISHU_APP_SECRET 未配置")

        self.client = lark.Client.builder() \
            .app_id(self.app_id) \
            .app_secret(self.app_secret) \
            .domain(lark.FEISHU_DOMAIN) \
            .timeout(30) \
            .log_level(lark.LogLevel.INFO) \
            .build()

    # ---- 内部 ----

    def _send_message(self, receive_id: str, msg_type: str, content: str,
                      receive_id_type: str = "open_id") -> tuple[bool, str | None, str | None]:
        request = CreateMessageRequest.builder() \
            .receive_id_type(receive_id_type) \
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(receive_id)
                .msg_type(msg_type)
                .content(content)
                .uuid(uuid.uuid4().hex)
                .build()
            ) \
            .build()

        response: CreateMessageResponse = self.client.im.v1.message.create(request)
        if not response.success():
            lark.logger.error(
                f"feishu send {msg_type} failed, code={response.code}, "
                f"msg={response.msg}, log_id={response.get_log_id()}"
            )
            return False, None, f"{response.code}: {response.msg}"
        message_id = getattr(getattr(response, "data", None), "message_id", None)
        return True, message_id, None

    def _send(self, receive_id: str, msg_type: str, content: str,
              receive_id_type: str = "open_id") -> bool:
        ok, _, _ = self._send_message(receive_id, msg_type, content, receive_id_type)
        return ok

    # ---- 对外 ----

    def send_text(self, open_id: str, text: str) -> bool:
        """发送纯文本"""
        return self._send(open_id, "text", json.dumps({"text": text}, ensure_ascii=False))

    def send_markdown(self, open_id: str, md_text: str) -> bool:
        """发送 Markdown 格式（转为飞书 Post 富文本）"""
        return self._send(open_id, "post", md_to_lark_post(md_text))

    def send_post(self, open_id: str, post_content: dict[str, Any]) -> bool:
        """发送原生 Post 富文本（内容由调用方组装）"""
        return self._send(open_id, "post", json.dumps(post_content, ensure_ascii=False))

    # ---- 文件 / 媒体 ----

    def upload_image(self, file_path: str) -> str:
        """上传图片，返回 image_key。失败时抛出 RuntimeError。"""
        from lark_oapi.api.im.v1 import CreateImageRequest, CreateImageRequestBody

        size = os.path.getsize(file_path)
        if size == 0:
            raise RuntimeError("飞书不允许上传空图片")
        if size > _MAX_IMAGE_UPLOAD_BYTES:
            raise RuntimeError("图片超过飞书 10MB 上传上限")

        with open(file_path, "rb") as file_obj:
            request = CreateImageRequest.builder().request_body(
                CreateImageRequestBody.builder().image_type("message").image(file_obj).build()
            ).build()
            response = self.client.im.v1.image.create(request)
        if not response.success() or not getattr(response.data, "image_key", None):
            raise RuntimeError(f"图片上传失败: {response.code}: {response.msg}")
        return response.data.image_key

    def upload_file(self, file_path: str) -> str:
        """上传文件，返回 file_key。失败时抛出 RuntimeError。"""
        from lark_oapi.api.im.v1 import CreateFileRequest, CreateFileRequestBody

        size = os.path.getsize(file_path)
        if size == 0:
            raise RuntimeError("飞书不允许上传空文件")
        if size > _MAX_FILE_UPLOAD_BYTES:
            raise RuntimeError("文件超过飞书 30MB 上传上限")

        extension = os.path.splitext(file_path)[1].lower()
        file_type = _FILE_TYPE_MAP.get(extension, "stream")
        with open(file_path, "rb") as file_obj:
            request = CreateFileRequest.builder().request_body(
                CreateFileRequestBody.builder()
                .file_type(file_type)
                .file_name(os.path.basename(file_path))
                .file(file_obj)
                .build()
            ).build()
            response = self.client.im.v1.file.create(request)
        if not response.success() or not getattr(response.data, "file_key", None):
            raise RuntimeError(f"文件上传失败: {response.code}: {response.msg}")
        return response.data.file_key

    def send_file(self, file_path: str, receive_id: str,
                  receive_id_type: str = "open_id") -> dict[str, Any]:
        """上传并发送文件/图片/音频/视频，返回 message_id 与 msg_type。

        图片上传上限 10MB、文件上限 30MB。超过 10MB 的图片按官方建议
        降级为普通文件发送，保证内容仍能送达。
        """
        extension = os.path.splitext(file_path)[1].lower()
        size = os.path.getsize(file_path)
        degraded = False
        if extension in _IMAGE_EXTS and size <= _MAX_IMAGE_UPLOAD_BYTES:
            image_key = self.upload_image(file_path)
            msg_type = "image"
            content = json.dumps({"image_key": image_key}, ensure_ascii=False)
        else:
            file_key = self.upload_file(file_path)
            if extension in _AUDIO_EXTS:
                msg_type = "audio"
            elif extension in _VIDEO_EXTS:
                msg_type = "media"
            else:
                msg_type = "file"
                degraded = extension in _IMAGE_EXTS
            content = json.dumps({"file_key": file_key}, ensure_ascii=False)

        ok, message_id, error = self._send_message(receive_id, msg_type, content, receive_id_type)
        if not ok:
            raise RuntimeError(error or "飞书消息发送失败")
        return {"message_id": message_id, "msg_type": msg_type, "degraded": degraded}

    def download_message_resource(self, message_id: str, file_key: str,
                                  message_type: str) -> tuple[bytes | None, str | None, str | None]:
        """下载消息资源。图片用 type=image，其余统一用 type=file。"""
        from lark_oapi.api.im.v1 import GetMessageResourceRequest

        resource_type = "image" if message_type == "image" else "file"
        request = GetMessageResourceRequest.builder() \
            .message_id(message_id) \
            .file_key(file_key) \
            .type(resource_type) \
            .build()
        response = self.client.im.v1.message_resource.get(request)
        if not response.success():
            return None, None, f"{response.code}: {response.msg}"
        data = response.file
        if hasattr(data, "read"):
            data = data.read()
        if not isinstance(data, (bytes, bytearray)):
            return None, None, "飞书返回了无法识别的文件内容"
        return bytes(data), response.file_name, None


# =====================================================================
# 文件/媒体接收与暂存
# =====================================================================

ATTACHMENT_LABELS: dict[str, str] = {
    "image": "图片",
    "file": "文件",
    "audio": "语音",
    "media": "视频",
}

_PENDING_KEY_PREFIX = "feishu.pending_attachments"
_MAX_PENDING_ITEMS = 20
_MAX_FILENAME_LENGTH = 120
_UNSAFE_FILENAME_RE = re.compile(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+")


def received_dir() -> Path:
    """返回并确保飞书接收目录存在。"""
    config = get_global_config()
    raw = str(getattr(config, "FEISHU_RECEIVED_DIR", "") or "/root/workspace/received").strip()
    directory = Path(raw).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def max_download_bytes() -> int:
    config = get_global_config()
    return max(0, int(getattr(config, "FEISHU_MAX_DOWNLOAD_MB", 30))) * 1024 * 1024


def pending_ttl_seconds() -> int:
    config = get_global_config()
    return max(1, int(getattr(config, "FEISHU_PENDING_FILE_TTL_SECONDS", 1800)))


def attachment_label(message_type: str) -> str:
    return ATTACHMENT_LABELS.get(message_type, "文件")


def safe_filename(name: str | None, fallback: str) -> str:
    """清洗飞书返回的文件名，确保只能落在接收目录内部。"""
    candidate = os.path.basename((name or "").replace("\\", "/")).strip()
    candidate = _UNSAFE_FILENAME_RE.sub("_", candidate).strip("._")
    if not candidate:
        candidate = fallback
    stem, suffix = os.path.splitext(candidate)
    if len(stem) > _MAX_FILENAME_LENGTH:
        stem = stem[:_MAX_FILENAME_LENGTH]
    return f"{stem}{suffix}" if stem else fallback


def unique_path(directory: Path, filename: str) -> Path:
    """重名时追加序号，避免覆盖用户历史文件。"""
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem, suffix = os.path.splitext(filename)
    index = 1
    while True:
        candidate = directory / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def save_attachment(
    data: bytes,
    filename: str | None,
    message_type: str,
    message_id: str | None,
) -> dict[str, Any]:
    """把下载到的字节写入接收目录，返回附件描述。"""
    fallback = f"{message_type or 'file'}_{message_id or uuid.uuid4().hex[:12]}"
    safe_name = safe_filename(filename, fallback)
    if message_type == "image" and not os.path.splitext(safe_name)[1]:
        safe_name = f"{safe_name}.jpg"
    elif message_type == "audio" and not safe_name.lower().endswith((".opus", ".ogg", ".oga")):
        safe_name = f"{safe_name}.ogg"
    elif message_type == "media" and not os.path.splitext(safe_name)[1]:
        safe_name = f"{safe_name}.mp4"

    path = unique_path(received_dir(), safe_name)
    path.write_bytes(data)
    return {
        "type": message_type,
        "kind": attachment_label(message_type),
        "path": str(path),
        "name": path.name,
        "size": len(data),
        "message_id": message_id,
    }


def _pending_key(open_id: str | None, chat_id: str | None) -> str:
    return f"{_PENDING_KEY_PREFIX}.{open_id or '-'}.{chat_id or '-'}"


def load_pending_attachments(open_id: str | None, chat_id: str | None) -> list[dict[str, Any]]:
    """读取未过期的暂存附件。"""
    raw = get_state(_pending_key(open_id, chat_id))
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(items, list):
        return []

    deadline = time.time() - pending_ttl_seconds()
    return [
        item for item in items
        if isinstance(item, dict) and float(item.get("ts", 0)) >= deadline
    ]


def add_pending_attachment(
    open_id: str | None,
    chat_id: str | None,
    attachment: dict[str, Any],
) -> None:
    """暂存一条附件，等待用户后续文本消息。"""
    items = load_pending_attachments(open_id, chat_id)
    items.append({**attachment, "ts": time.time()})
    set_state(
        _pending_key(open_id, chat_id),
        json.dumps(items[-_MAX_PENDING_ITEMS:], ensure_ascii=False),
    )


def pop_pending_attachments(open_id: str | None, chat_id: str | None) -> list[dict[str, Any]]:
    """取出并清空暂存附件。"""
    items = load_pending_attachments(open_id, chat_id)
    delete_state(_pending_key(open_id, chat_id))
    for item in items:
        item.pop("ts", None)
    return items


def _parse_post_block(block: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    """解析单个 post 内容块（title + content 行）。"""
    rows = block.get("content")
    if not isinstance(rows, list):
        return "", [], []

    texts: list[str] = []
    images: list[str] = []
    media_keys: list[str] = []
    title = block.get("title")
    if isinstance(title, str) and title:
        texts.append(title)

    for row in rows:
        if not isinstance(row, list):
            continue
        for element in row:
            if not isinstance(element, dict):
                continue
            tag = element.get("tag")
            if tag in ("text", "md", "a"):
                value = element.get("text")
                if isinstance(value, str) and value:
                    texts.append(value)
            elif tag == "at":
                user_name = element.get("user_name")
                user_id = element.get("user_id")
                name = user_name if isinstance(user_name, str) and user_name else user_id
                texts.append(f"@{name if isinstance(name, str) and name else 'user'}")
            elif tag == "code_block":
                language = element.get("language")
                code = element.get("text")
                language = language if isinstance(language, str) else ""
                code = code if isinstance(code, str) else ""
                texts.append(f"\n```{language}\n{code}\n```\n")
            elif tag == "img":
                image_key = element.get("image_key")
                if isinstance(image_key, str) and image_key:
                    images.append(image_key)
            elif tag == "media":
                file_key = element.get("file_key")
                if isinstance(file_key, str) and file_key:
                    media_keys.append(file_key)
            elif tag == "hr":
                texts.append("\n---\n")

    return " ".join(texts).strip(), images, media_keys


def extract_post_content(content_json: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    """从飞书 post 富文本中提取文本、内嵌图片与视频 key。

    兼容三种结构：

    1. Direct:    ``{"title": "...", "content": [[...]]}``
    2. Localized: ``{"zh_cn": {"title": "...", "content": [...]}}``
    3. Wrapped:   ``{"post": {"zh_cn": {"title": "...", "content": [...]}}}``

    返回 ``(text, image_keys, media_keys)``。
    """
    if not isinstance(content_json, dict):
        return "", [], []

    root = content_json
    post = root.get("post")
    if isinstance(post, dict):
        root = post

    if "content" in root:
        text, images, media_keys = _parse_post_block(root)
        if text or images or media_keys:
            return text, images, media_keys

    for locale in ("zh_cn", "en_us", "ja_jp"):
        block = root.get(locale)
        if isinstance(block, dict):
            text, images, media_keys = _parse_post_block(block)
            if text or images or media_keys:
                return text, images, media_keys

    for value in root.values():
        if isinstance(value, dict):
            text, images, media_keys = _parse_post_block(value)
            if text or images or media_keys:
                return text, images, media_keys

    return "", [], []


# =====================================================================
# 接收（WebSocket 长链接）
# =====================================================================

class FeishuClient:
    """
    飞书 WebSocket 客户端

    后台线程接入飞书事件平台，把收到的用户消息解析后调用上层 ``on_message``
    回调；同时持有一个 ``FeishuMessageSender`` 供 loop 处理完事件后回复用户。

    回调签名与 ``WebhookServer`` 的 ``write_callback`` 保持一致：
    ``(text: str, img_urls: list[str] | None, context: dict[str, object]) -> str``。
    """

    def __init__(
        self,
        app_id: str | None = None,
        app_secret: str | None = None,
        on_message: Optional[MessageCallback] = None,
    ):
        if not HAS_LARK:
            raise ImportError(_LARK_MISSING_MSG)

        config = get_global_config()
        self.app_id = app_id or (config.FEISHU_APP_ID or "")
        self.app_secret = app_secret or config.FEISHU_APP_SECRET.get_secret_value()

        if not self.app_id or not self.app_secret:
            raise ValueError("FEISHU_APP_ID / FEISHU_APP_SECRET 未配置")

        self.on_message: Optional[MessageCallback] = on_message

        self._ws_client: Any | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._sender: FeishuMessageSender | None = None

    @property
    def sender(self) -> FeishuMessageSender:
        """懒加载消息发送器"""
        if self._sender is None:
            self._sender = FeishuMessageSender(self.app_id, self.app_secret)
        return self._sender

    def _download_and_save_attachment(
        self,
        message_type: str,
        content_json: dict[str, Any],
        message_id: str | None,
    ) -> dict[str, Any]:
        """下载单条消息资源并落盘；失败时返回带 error 的描述，不抛异常。"""
        file_key = content_json.get("image_key") if message_type == "image" else content_json.get("file_key")
        label = attachment_label(message_type)
        base: dict[str, Any] = {
            "type": message_type,
            "kind": label,
            "path": None,
            "name": None,
            "size": 0,
            "message_id": message_id,
        }
        if not file_key or not message_id:
            return {**base, "error": "消息缺少 file_key 或 message_id"}

        try:
            data, filename, error = self.sender.download_message_resource(
                message_id, str(file_key), message_type
            )
        except Exception as exc:  # pragma: no cover - 网络/凭据异常
            return {**base, "error": str(exc)}
        if data is None:
            return {**base, "error": error or "下载失败"}

        limit = max_download_bytes()
        if limit and len(data) > limit:
            return {**base, "error": f"文件超过 {limit // (1024 * 1024)}MB 限制"}

        fallback = f"{message_type}_{str(file_key)[:16]}"
        if message_type == "file":
            fallback = str(content_json.get("file_name") or fallback)
        try:
            return save_attachment(
                data, filename or fallback, message_type, message_id
            )
        except Exception as exc:
            return {**base, "error": f"保存失败: {exc}"}

    # ---- 事件处理 ----

    def _handle_message(self, data: Any) -> None:
        """飞书消息事件回调：解析 → 通过 on_message 上抛"""
        if self.on_message is None:
            return
        try:
            event = data.event
            sender = event.sender
            message = event.message

            user_open_id = sender.sender_id.open_id
            owner_open_id: str | None = None
            try:
                owner_open_id = bind_feishu_owner_open_id(user_open_id)
            except Exception as e:
                # 绑定失败不应影响本次消息处理，输出侧仍会用 context 中的 open_id
                if lark:
                    lark.logger.error(f"绑定飞书用户 open_id 失败: {e}")

            if not is_feishu_owner(user_open_id, owner_open_id):
                # 个人专用：只处理首个绑定用户的消息，其他用户直接忽略
                if lark:
                    lark.logger.warning(f"忽略非绑定飞书用户的消息: {user_open_id}")
                return

            message_type = message.message_type
            message_content = message.content

            # 解析消息内容
            try:
                content_json = json.loads(message_content)
            except json.JSONDecodeError:
                content_json = {"raw": message_content}

            # 提取用户文本与附件
            user_text = ""
            attachments: list[dict[str, Any]] = []
            if message_type == "text":
                user_text = str(content_json.get("text") or "")
            elif message_type == "post":
                user_text, image_keys, media_keys = extract_post_content(content_json)
                for image_key in image_keys:
                    attachments.append(self._download_and_save_attachment(
                        "image", {"image_key": image_key}, message.message_id
                    ))
                for file_key in media_keys:
                    attachments.append(self._download_and_save_attachment(
                        "media", {"file_key": file_key}, message.message_id
                    ))
            elif message_type in _MESSAGE_RESOURCE_TYPES:
                attachments.append(self._download_and_save_attachment(
                    message_type, content_json, message.message_id
                ))
            else:
                user_text = json.dumps(content_json, ensure_ascii=False)

            # 上下文，回复时需要 open_id
            context = {
                "source": "feishu",
                "open_id": user_open_id,
                "message_id": message.message_id,
                "chat_id": message.chat_id,
                "chat_type": message.chat_type,
                "message_type": message_type,
                "sender": {
                    "open_id": user_open_id,
                    "union_id": sender.sender_id.union_id,
                    "user_id": sender.sender_id.user_id,
                },
                "mentions": [
                    {
                        "key": m.key,
                        "open_id": m.id.open_id,
                        "name": m.name,
                    }
                    for m in (message.mentions or [])
                ],
            }

            if not user_text.strip() and not attachments:
                if lark:
                    lark.logger.warning(
                        "忽略无法解析的飞书消息: type=%s, content=%s",
                        message_type,
                        json.dumps(content_json, ensure_ascii=False)[:500],
                    )
                return

            # 文本消息会带上此前暂存的纯文件消息；纯文件消息先暂存，不触发 AI
            is_command = user_text.strip().startswith("/")
            pending = (
                pop_pending_attachments(user_open_id, message.chat_id)
                if user_text.strip() and not is_command else []
            )
            context["attachments"] = pending + attachments

            if not user_text.strip():
                for attachment in attachments:
                    add_pending_attachment(
                        user_open_id, message.chat_id, attachment
                    )
                return

            # 由上层（FeishuInput）决定如何投递到消息总线
            self.on_message(user_text, None, context)

        except Exception as e:  # pragma: no cover
            if lark:
                lark.logger.error(f"处理飞书消息异常: {e}")

    # ---- 生命周期 ----

    def start(self) -> None:
        if self._running:
            return
        self._running = True

        event_handler = lark.EventDispatcherHandler.builder("", "") \
            .register_p2_im_message_receive_v1(self._handle_message) \
            .build()

        self._ws_client = lark.ws.Client(
            self.app_id,
            self.app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )

        self._thread = threading.Thread(
            target=self._run, daemon=True, name="feishu-ws"
        )
        self._thread.start()

    def _run(self) -> None:  # pragma: no cover - 网络
        if self._ws_client:
            try:
                self._ws_client.start()
            except Exception as e:
                if self._running and lark:
                    lark.logger.error(f"飞书 WebSocket 连接异常: {e}")

    def stop(self) -> None:
        self._running = False
        if self._ws_client:
            try:
                self._ws_client.stop()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=5.0)


# =====================================================================
# 全局单例
# =====================================================================

_feishu_client: FeishuClient | None = None
_feishu_lock = threading.Lock()
_OWNER_OPEN_ID_KEY = "feishu.owner_open_id"


def get_feishu_client() -> FeishuClient | None:
    """获取全局飞书客户端实例（未设置则返回 None）"""
    return _feishu_client


def set_feishu_client(client: FeishuClient) -> None:
    """设置全局飞书客户端实例"""
    global _feishu_client
    with _feishu_lock:
        _feishu_client = client


def get_feishu_owner_open_id() -> str | None:
    """获取自动绑定的飞书用户 open_id（首个向机器人发消息的用户）"""
    return get_state(_OWNER_OPEN_ID_KEY)


def bind_feishu_owner_open_id(open_id: str | None) -> str | None:
    """绑定首个向机器人发消息的飞书用户；已绑定时保持不变"""
    if not open_id:
        return get_feishu_owner_open_id()
    return get_or_set_state(_OWNER_OPEN_ID_KEY, open_id)


def is_feishu_owner(open_id: str | None, owner_open_id: str | None = None) -> bool:
    """判断是否为自动绑定的飞书用户；尚未绑定时允许通过"""
    if not open_id:
        return False
    if owner_open_id is None:
        owner_open_id = get_feishu_owner_open_id()
    return owner_open_id is None or owner_open_id == open_id
