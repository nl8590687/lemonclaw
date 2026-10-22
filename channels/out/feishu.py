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
Feishu Output
"""

import io

from rich.console import Console

from channels.device.feishu import (
    FeishuMessageSender,
    get_feishu_client,
    get_feishu_owner_open_id,
)
from channels.out.base import BaseOutChannel


def _render_text(content: object) -> str:
    """把 rich 渲染对象（Table/Panel 等）转成适合飞书发送的纯文本。"""
    buffer = io.StringIO()
    console = Console(file=buffer, width=120, no_color=True, highlight=False)
    try:
        console.print(content)
        return buffer.getvalue()
    except Exception:
        return str(content)


class FeishuOutputChannel(BaseOutChannel):
    """
    飞书消息输出通道

    通过 ``FeishuMessageSender`` 把回复发送给指定 ``open_id`` 的飞书用户。
    个人专用模式下，收件人固定为自动绑定的首个飞书用户：

    1. 首个向机器人发消息的飞书用户（自动绑定并持久化）
    2. 尚未完成绑定时，回退到 ``context`` 或构造时传入的 ``open_id``

    这样终端 / Webhook / Cron 触发的输出也能同步发到飞书。

    工具调用 / 流式打印等中间过程在飞书场景下没有展示价值，
    统一作为静默 no-op 处理；只有 ``write_message`` / 错误 / 菜单类
    输出会真正发往飞书。
    """

    def __init__(self, open_id: str | None = None):
        super().__init__()
        # sender 优先复用 ins.feishu 启动时注册的全局 client，
        # 否则按全局配置自行实例化（仍走同一个 app_id/secret）。
        self._open_id: str | None = open_id
        self._sender: FeishuMessageSender | None = None

        try:
            client = get_feishu_client()
            self._sender = client.sender if client is not None else FeishuMessageSender()
        except Exception:
            self._sender = None

    def write_message(self, msg: str, context: dict[str, object]):
        open_id = self._resolve_open_id(context)
        if not open_id or not self._sender or not msg:
            return
        self._sender.send_markdown(open_id, msg)

    def print(self, msg: str):
        # 飞书侧不做流式增量输出，整体回复由 write_message 统一发送。
        return

    def write_tool_calling(self, tool_name: str, param_str: str):
        # 工具调用过程对终端用户不可见，no-op。
        return

    def write_tool_result(self, output: object):
        # 工具结果对终端用户不可见，no-op。
        return

    def write_tool_error(self, error: BaseException):
        open_id = self._resolve_open_id(None)
        if not open_id or not self._sender:
            return
        self._sender.send_text(open_id, f"⚠️ 工具错误: {error}")

    def write_menu_content(self, content: object):
        open_id = self._resolve_open_id(None)
        if not open_id or not self._sender:
            return
        self._sender.send_markdown(open_id, _render_text(content))

    def write_system_error(self, content: str):
        open_id = self._resolve_open_id(None)
        if not open_id or not self._sender:
            return
        self._sender.send_text(open_id, f"❌ 系统错误: {content}")

    # ---- 内部辅助（沿用 channels/ins/webhook.py 的下划线私有约定） ----

    def _resolve_open_id(self, context: dict[str, object] | None) -> str | None:
        owner_open_id = get_feishu_owner_open_id()
        if owner_open_id:
            return owner_open_id
        if isinstance(context, dict):
            value = context.get("open_id")
            if isinstance(value, str) and value:
                return value
        return self._open_id
