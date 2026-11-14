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

from langchain_core.messages import AIMessage

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

    def send_question(self, row) -> str:
        origin = row['origin']
        target = origin.get('chat_id') or origin['open_id']
        ok, message_id, _ = self._send_message(target, 'interactive',
            json.dumps(question_card(row), ensure_ascii=False),
            'chat_id' if origin.get('chat_id') else 'open_id')
        if not ok or not message_id:
            raise ValueError('飞书人工确认卡片发送失败')
        return message_id

    def close_question(self, row):
        if not row.get('message_id'):
            return
        try:
            from lark_oapi.api.im.v1 import PatchMessageRequest, PatchMessageRequestBody
            request = PatchMessageRequest.builder().message_id(row['message_id']).request_body(
                PatchMessageRequestBody.builder().content(json.dumps(question_closed_card(row), ensure_ascii=False)).build()).build()
            response = self.client.im.v1.message.patch(request)
            if not response.success():
                lark.logger.warning('人工确认卡片状态更新失败')
        except Exception:
            lark.logger.warning('人工确认卡片状态更新失败')

    def add_reaction(self, message_id: str, emoji_type: str) -> str | None:
        """以当前机器人身份添加消息表情，返回可用于撤销的 reaction_id。"""
        try:
            from lark_oapi.api.im.v1 import CreateMessageReactionRequest, CreateMessageReactionRequestBody, Emoji
            request = CreateMessageReactionRequest.builder().message_id(message_id).request_body(
                CreateMessageReactionRequestBody.builder().reaction_type(
                    Emoji.builder().emoji_type(emoji_type).build()).build()).build()
            response = self.client.im.v1.message_reaction.create(request)
            if response.success():
                return getattr(response.data, 'reaction_id', None)
            if lark:
                lark.logger.warning('添加消息表情失败: code=%s', response.code)
        except Exception:
            if lark:
                lark.logger.warning('添加消息表情失败，继续处理消息')
        return None

    def delete_reaction(self, message_id: str, reaction_id: str) -> bool:
        """撤销本机器人添加的指定表情。"""
        try:
            from lark_oapi.api.im.v1 import DeleteMessageReactionRequest
            request = DeleteMessageReactionRequest.builder().message_id(message_id).reaction_id(reaction_id).build()
            response = self.client.im.v1.message_reaction.delete(request)
            if response.success():
                return True
            if lark:
                lark.logger.warning('删除消息表情失败: code=%s', response.code)
        except Exception:
            if lark:
                lark.logger.warning('删除消息表情失败，继续处理消息')
        return False

    def send_text(self, open_id: str, text: str) -> bool:
        """发送纯文本"""
        return self._send(open_id, "text", json.dumps({"text": text}, ensure_ascii=False))

    def send_markdown(self, open_id: str, md_text: str) -> bool:
        """发送 Markdown 格式（转为飞书 Post 富文本）"""
        return self._send(open_id, "post", md_to_lark_post(md_text))

    def send_markdown_card(self, open_id: str, md_text: str, event_type: object = None) -> bool:
        """最终输出使用 Card 2.0；分段失败即停止，不重复发送已交付部分。"""
        for card in markdown_reply_cards(md_text, event_type):
            if not self._send(open_id, "interactive", json.dumps(card, ensure_ascii=False)):
                return False
        return True

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


def discard_pending_images(open_id, chat_id, ids=None):
    """移除已显式处理的暂存项；其他待选附件继续保留。"""
    items = load_pending_attachments(open_id, chat_id)
    remaining = [item for item in items if ids is not None and item.get('attachment_id') not in ids]
    if remaining:
        set_state(_pending_key(open_id, chat_id), json.dumps(remaining, ensure_ascii=False))
    else:
        delete_state(_pending_key(open_id, chat_id))


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
                "sender_type": getattr(sender, "sender_type", None),
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

            from agent.media.images import register_image
            from dao.attachment import AttachmentDAO
            registered = []
            for index, attachment in enumerate(attachments):
                if attachment.get('type') == 'image' and attachment.get('path'):
                    try:
                        attachment = register_image(attachment, context, index)
                    except (ValueError, OSError) as ex:
                        attachment = dict(attachment, vision_error=str(ex))
                registered.append(attachment)
            attachments = registered
            image_items = [item for item in attachments if item.get('attachment_id')]
            if image_items:
                receipt = '已保存图片：\n' + '\n'.join(f"{item['attachment_id']} {item['name']}" for item in image_items)
                receipt += '\n引用图片并回复问题，或 /image <编号...|all> -- 问题；/upload 仅保存'
                self._image_receipt(user_open_id, receipt)
            parent_id = getattr(message, 'parent_id', None)
            if isinstance(parent_id, str) and parent_id and user_text.strip() and not user_text.strip().startswith('/'):
                try:
                    quoted = self._quoted_images(parent_id, context)
                except Exception:
                    self._image_receipt(user_open_id, '引用消息暂时无法读取；可使用 /image 指定图片编号，本轮继续处理文字')
                    user_text += '\n[附件说明：被引用消息未加载，本轮未附加其中的图片。]'
                    quoted = []
                attachments = [dict(item, vision_selected=True) for item in quoted] + attachments
            if message_type == 'post' and user_text.strip() and not user_text.strip().startswith('/'):
                attachments = [dict(item, vision_selected=True) if item.get('attachment_id') else item for item in attachments]
            if user_text.strip().lower() == '/upload' and attachments:
                ids = [item['attachment_id'] for item in attachments if item.get('attachment_id')]
                AttachmentDAO().mark(ids, context, 'stored')
                self._image_receipt(user_open_id, '本条消息附件已保存，未加入视觉上下文')
                return
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
            if reaction_eligible(context) and (
                not user_text.strip().startswith('/') or
                (user_text.strip().split(maxsplit=1)[0].lower() == '/image' and len(user_text.split()) > 1)
            ):
                context['feishu_reaction_active'] = True
                try:
                    context['feishu_typing_reaction_id'] = self.sender.add_reaction(message.message_id, 'Typing')
                except Exception:
                    context['feishu_typing_reaction_id'] = None
            try:
                self.on_message(user_text, None, context)
            except Exception:
                try:
                    finish_reaction(context, self.sender, False)
                except Exception:
                    pass
                raise

        except Exception as e:  # pragma: no cover
            if lark:
                lark.logger.error(f"处理飞书消息异常: {e}")

    def _image_receipt(self, open_id, text):
        try:
            self.sender.send_text(open_id, text)
        except Exception:
            if lark:
                lark.logger.warning('图片回执发送失败，继续处理接收消息')

    def _quoted_images(self, parent_id, context):
        """解析用户显式引用的图片消息，先查本地登记再按消息 ID 获取。"""
        from dao.attachment import AttachmentDAO
        from agent.media.images import register_image
        dao = AttachmentDAO()
        items = dao.for_message(parent_id, context)
        if items:
            return items
        from lark_oapi.api.im.v1 import GetMessageRequest
        response = self.sender.client.im.v1.message.get(GetMessageRequest.builder().message_id(parent_id).build())
        if not response.success():
            raise ValueError('无法读取被引用图片，请使用已接收的图片编号')
        messages = getattr(response.data, 'items', None) or []
        target = next((item for item in messages if item.message_id == parent_id), None)
        if target is None or target.chat_id != context['chat_id']:
            raise ValueError('被引用消息不属于当前聊天')
        content = json.loads(target.body.content)
        if target.msg_type == 'image':
            keys = [content['image_key']]
        elif target.msg_type == 'post':
            _, keys, _ = extract_post_content(content)
        else:
            return []
        if not keys:
            raise ValueError('被引用消息没有图片')
        return [register_image(self._download_and_save_attachment('image', {'image_key': key}, parent_id), context, i)
                for i, key in enumerate(keys)]

    def _handle_question_action(self, data):
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            P2CardActionTriggerResponse, CallBackToast, CallBackCard)
        from dao.question import QuestionDAO
        from agent.questions import actor_matches, validate_answers
        response = P2CardActionTriggerResponse()
        try:
            event = data.event
            action = event.action
            value = action.value or {}
            if action.tag != 'button':
                return response
            if action.name and action.name.startswith('ask_confirm__'):
                _, question_id, nonce = action.name.split('__', 2)
                cancel = False
            elif value.get('action') == 'ask_cancel':
                question_id, nonce = value.get('question_id'), value.get('nonce')
                cancel = True
            else:
                return response
            store = QuestionDAO()
            row = store.get(question_id)
            ctx = {'source': 'feishu', 'sender_type': 'user', 'open_id': event.operator.open_id,
                   'chat_id': event.context.open_chat_id}
            import secrets
            if (row is None or not isinstance(nonce, str) or not secrets.compare_digest(nonce, row['nonce'])
                    or row['message_id'] != event.context.open_message_id or not actor_matches(row, ctx)):
                raise ValueError('问题不属于当前用户/卡片，或卡片已失效')
            if row['finished'] or row['status'] != 'pending':
                raise ValueError('此问题已处理或已到期，请勿重复提交')
            if cancel:
                result = {'status': 'cancelled', 'action': 'cancel', 'answers': []}
            else:
                form = action.form_value or {}
                fields = {}
                for i, question in enumerate(row['payload']['questions'], 1):
                    raw = form.get(f'q{i}')
                    fields[str(i)] = raw if question['kind'] == 'text' or isinstance(raw, list) else [raw] if isinstance(raw, str) else []
                    fields[f'{i}_other'] = form.get(f'q{i}_other', '')
                result = validate_answers(row['payload'], fields)
            if not store.submit(question_id, result):
                raise ValueError('问题已超时或已处理，本次答案未提交')
            row = store.get(question_id)
            response.toast = CallBackToast({'type': 'success', 'content': '已取消，本轮将结束' if cancel else '已提交，继续执行'})
            response.card = CallBackCard({'type': 'raw', 'data': question_closed_card(row)})
        except (ValueError, TypeError, AttributeError) as ex:
            response.toast = CallBackToast({'type': 'error', 'content': str(ex)[:200]})
        except Exception:
            response.toast = CallBackToast({'type': 'error', 'content': '暂时无法提交，请稍后重试；等待时限不变'})
        return response

    # ---- 生命周期 ----

    def start(self) -> None:
        if self._running:
            return
        self._running = True

        event_handler = lark.EventDispatcherHandler.builder("", "") \
            .register_p2_im_message_receive_v1(self._handle_message) \
            .register_p2_card_action_trigger(self._handle_question_action) \
            .register_p2_im_message_reaction_created_v1(lambda _: None) \
            .register_p2_im_message_reaction_deleted_v1(lambda _: None) \
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


def reaction_eligible(context):
    return (getattr(get_global_config(), 'ENABLE_FEISHU', False)
            and context.get('source') == 'feishu'
            and context.get('sender_type') == 'user'
            and isinstance(context.get('message_id'), str) and bool(context['message_id']))


def turn_completed(result):
    if isinstance(result, dict) and result.get("completed") is True:
        return True
    messages = result.get('messages', []) if isinstance(result, dict) else []
    return bool(messages and isinstance(messages[-1], AIMessage)
                and isinstance(messages[-1].content, str) and messages[-1].content.strip())


def finish_reaction(context, sender, completed):
    if not context.pop('feishu_reaction_active', False):
        return
    reaction_id = context.pop('feishu_typing_reaction_id', None)
    try:
        if reaction_id:
            sender.delete_reaction(context['message_id'], reaction_id)
        if completed:
            sender.add_reaction(context['message_id'], 'DONE')
    except Exception:
        # 对测试替身或第三方 sender 同样隔离异常。
        import logging
        logging.getLogger(__name__).warning('飞书状态表情更新失败，主流程继续')


def finish_live_reaction(context, completed):
    try:
        client = get_feishu_client()
        if client is not None:
            finish_reaction(context, client.sender, completed)
    except Exception:
        import logging
        logging.getLogger(__name__).warning('飞书状态表情清理失败，主流程继续')


def question_card(row):
    """原生 Card 2.0 表单；取消按钮置于 form 外以免必填验证阻止取消。"""
    from datetime import datetime
    spec = row['payload']
    deadline = datetime.fromtimestamp(row['deadline']).astimezone().isoformat(timespec='minutes')
    form = []
    for i, question in enumerate(spec['questions'], 1):
        if question['kind'] == 'text':
            form.append({'tag': 'input', 'name': f'q{i}', 'label': {'tag': 'plain_text', 'content': question['prompt']},
                         'required': True, 'max_length': 1000, 'width': 'fill'})
        else:
            form.append({'tag': 'markdown', 'content': f"**{i}. {question['prompt']}**"})
            options = [{'text': {'tag': 'plain_text', 'content': text}, 'value': str(j)}
                       for j, text in enumerate(question['options'], 1)]
            options.append({'text': {'tag': 'plain_text', 'content': '以上均不是（请在下方填写）'}, 'value': '0'})
            form.append({'tag': 'select_static' if question['kind'] == 'single' else 'multi_select_static',
                         'name': f'q{i}', 'required': True, 'width': 'fill', 'options': options,
                         'placeholder': {'tag': 'plain_text', 'content': '请选择'}})
            form.append({'tag': 'input', 'name': f'q{i}_other', 'max_length': 1000, 'width': 'fill',
                         'label': {'tag': 'plain_text', 'content': '以上均不是：填写实际内容（选择 0 时必填）'}})
    form.append({'tag': 'button', 'name': f"ask_confirm__{row['question_id']}__{row['nonce']}",
                 'text': {'tag': 'plain_text', 'content': '确定'}, 'type': 'primary_filled',
                 'form_action_type': 'submit'})
    return {'schema': '2.0', 'config': {'update_multi': True, 'enable_forward': False},
            'header': {'template': 'blue', 'title': {'tag': 'plain_text', 'content': '请求用户确认'}},
            'body': {'elements': [
                {'tag': 'markdown', 'content': spec['reason']},
                {'tag': 'markdown', 'content': f"截止时间 {deadline}；超时按取消结束。"},
                {'tag': 'form', 'name': 'ask_form', 'elements': form},
                {'tag': 'button', 'text': {'tag': 'plain_text', 'content': '取消'}, 'type': 'default',
                 'behaviors': [{'type': 'callback', 'value': {'action': 'ask_cancel',
                     'question_id': row['question_id'], 'nonce': row['nonce']}}]}]}}


def question_closed_card(row):
    label = {'confirmed': '已提交，继续执行', 'cancelled': '已取消', 'timeout': '已超时，按取消结束'}.get(row['status'], '等待用户确认')
    elements = [{'tag': 'markdown', 'content': label},
                {'tag': 'div', 'text': {'tag': 'plain_text', 'content': row['payload']['reason']}}]
    answers = (row.get('result') or {}).get('answers', [])
    for i, question in enumerate(row['payload']['questions'], 1):
        lines = [f"{i}. {question['prompt']}"]
        if question['kind'] != 'text':
            lines.extend(f"{j}. {option}" for j, option in enumerate(question['options'], 1))
            lines.append('0. 以上均不是')
        if row['status'] == 'confirmed' and i <= len(answers):
            lines.append('用户答案：' + '、'.join(answers[i - 1]['values']))
        else:
            lines.append('用户答案：未提交')
        elements.append({'tag': 'div', 'text': {'tag': 'plain_text', 'content': '\n'.join(lines)}})
    return {'schema': '2.0', 'config': {'update_multi': True, 'enable_forward': False},
            'header': {'template': 'grey', 'title': {'tag': 'plain_text', 'content': '用户确认状态'}},
            'body': {'elements': elements}}


# 为 30 KB 消息限制预留接收人、UUID 等信封字段空间；按转义后的 UTF-8 字节计量。
_REPLY_CARD_BYTES = 24_000
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def markdown_reply_cards(text: str, event_type: object = None):
    """构造只展示内容的卡片，超长时按顺序分段并保持跨段代码围栏闭合。"""
    from channels.bus.enum import EventType
    if isinstance(event_type, EventType):
        event_type = event_type.value
    label = event_type.strip() if isinstance(event_type, str) and event_type.strip() else '未知'
    # 类型使用 plain_text，避免外部上下文在卡片标题中注入 Markdown/人员提及。
    label = label[:128]

    def card(content, part):
        title = f'事件类型：{label}' + (f' · 续篇 {part}' if part > 1 else '')
        return {'schema': '2.0', 'header': {'template': 'blue', 'title': {'tag': 'plain_text', 'content': title}},
                'body': {'elements': [{'tag': 'markdown', 'content': content}]}}

    def size(content, part):
        payload = json.dumps(card(content, part), ensure_ascii=False)
        return len(json.dumps({'content': payload}, ensure_ascii=False).encode('utf-8'))

    def fence_after(chunk, state):
        for line in chunk.splitlines():
            match = _FENCE.match(line)
            if not match:
                continue
            token, rest = match.groups()
            if state is None:
                state = (token, line)
            elif token[0] == state[0][0] and len(token) >= len(state[0]) and not rest.strip():
                state = None
        return state

    offset, part, state = 0, 1, None
    while offset < len(text):
        prefix = state[1] + '\n' if state else ''
        # 留出闭合围栏的空间；不会截断 Unicode 字符或丢弃原始正文。
        low, high = 0, min(len(text) - offset, _REPLY_CARD_BYTES)
        while low < high:
            mid = (low + high + 1) // 2
            chunk = text[offset:offset + mid]
            after = fence_after(chunk, state)
            suffix = '\n' + after[0] if after else ''
            if size(prefix + chunk + suffix, part) <= _REPLY_CARD_BYTES:
                low = mid
            else:
                high = mid - 1
        if not low:
            raise ValueError('飞书卡片内容无法在消息大小限制内分段')
        end = offset + low
        if end < len(text):
            newline = text.rfind('\n', offset, end)
            if newline >= offset + low // 2:
                end = newline + 1
        chunk = text[offset:end]
        after = fence_after(chunk, state)
        suffix = '\n' + after[0] if after else ''
        yield card(prefix + chunk + suffix, part)
        offset, state, part = end, after, part + 1
