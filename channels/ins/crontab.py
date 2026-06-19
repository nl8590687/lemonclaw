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
Crontab Input
"""

from channels.bus import EventPriority, EventType, get_bus
from channels.device.crontab import CronTaskManager
from channels.ins.base import BaseInChannel


class CrontabInput(BaseInChannel):
    """
    Cron 定时任务输入通道
    """

    def __init__(self):
        super().__init__()
        self.manager = CronTaskManager(on_trigger=self._write_message)

    def run(self):
        self.manager.start()

    def _write_message(self, msg: str, img_urls: list[str] | None = None, context: dict[str, object] = None) -> str:
        bus = get_bus()
        if not context:
            context = {}
        return bus.publish(context=context, event_type=EventType.SCHEDULED_TASK, content={
            "text": msg,
            "images": img_urls
        }, priority=EventPriority.NORMAL)