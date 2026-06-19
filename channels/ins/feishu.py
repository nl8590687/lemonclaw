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
Feishu Input
"""

from channels.bus import EventPriority, EventType, get_bus
from channels.device.feishu import FeishuClient, set_feishu_client
from channels.ins.base import BaseInChannel


class FeishuInput(BaseInChannel):
    """
    飞书消息输入通道
    """

    def __init__(self):
        super().__init__()
        self.feishu_client = FeishuClient(on_message=self._write_message)
        # 注册为全局单例，供 channels.out.feishu.FeishuOutputChannel 复用 sender
        set_feishu_client(self.feishu_client)

    def run(self):
        self.feishu_client.start()

    def _write_message(self, msg: str, img_urls: list[str] | None = None, context: dict[str, object] = None) -> str:
        bus = get_bus()
        if not context:
            context = {}
        return bus.publish(context=context, event_type=EventType.LARK_MESSAGE, content={
            "text": msg,
            "images": img_urls
        }, priority=EventPriority.HIGH)