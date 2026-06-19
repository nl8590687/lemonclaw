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
import threading
import uuid
from typing import Any, Callable, Optional

from config import get_global_config


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


# 收到飞书消息时的回调签名（与 webhook 的 _write_message 保持兼容）：
#   (text, img_urls, context) -> event_id
MessageCallback = Callable[[str, Optional[list[str]], dict[str, object]], str]


# =====================================================================
# Markdown -> Post 富文本
# =====================================================================

def md_to_lark_post(md_text: str) -> str:
    """
    把 Markdown 文本转成飞书 Post 富文本格式。

    飞书的 Post 不支持完整 Markdown，这里逐行转成 ``md`` 标签，
    在大部分客户端能正确渲染。

    :param md_text: Markdown 文本
    :return: 飞书 Post JSON 字符串
    """
    return json.dumps({
        "zh-cn": {
            "content": [
                [{"tag": "md", "text": line} for line in md_text.splitlines()]
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

    def _send(self, receive_id: str, msg_type: str, content: str,
              receive_id_type: str = "open_id") -> bool:
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
            return False
        return True

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
            message_type = message.message_type
            message_content = message.content

            # 解析消息内容
            try:
                content_json = json.loads(message_content)
            except json.JSONDecodeError:
                content_json = {"raw": message_content}

            # 提取用户文本
            if message_type == "text" and "text" in content_json:
                user_text = content_json["text"]
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


def get_feishu_client() -> FeishuClient | None:
    """获取全局飞书客户端实例（未设置则返回 None）"""
    return _feishu_client


def set_feishu_client(client: FeishuClient) -> None:
    """设置全局飞书客户端实例"""
    global _feishu_client
    with _feishu_lock:
        _feishu_client = client