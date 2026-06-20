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

import sys

from channels.device.console import get_console

from channels.ins.base import BaseInChannel
from channels.bus import get_bus, EventType, EventPriority


class TerminalInput(BaseInChannel):
    """
    终端输入通道
    """

    def __init__(self):
        super().__init__()
        self.console = get_console()

    def run(self):
        # 没有 TTY 时（nohup / systemd / docker 不带 -it / 重定向 stdin 等场景）
        # input() 会立刻 EOF，若仍循环读会变成 100% CPU 的死循环并不停打印提示符。
        # 这种情况下直接退出输入循环，让 webhook/cron/feishu 等其他输入通道继续工作。
        if not sys.stdin or not sys.stdin.isatty():
            self.stop()
            return

        while not self.stopped():
            try:
                user_input = self.console.input("[bold green]你[/] > ").strip()
                if not user_input:
                    continue
                self._write_message(user_input)
            except KeyboardInterrupt:
                self.stop()
                break
            except EOFError:
                # 真拿到 EOF 说明 stdin 已关闭，退出循环而不是 continue，
                # 否则会变成空转死循环。
                self.stop()
                break

    def _write_message(self, msg: str, img_urls: list[str] | None = None, context: dict[str, object] = None) -> str:
        bus = get_bus()
        if not context:
            context = {}
        return bus.publish(context=context, event_type=EventType.TERMINAL, content={
            "text": msg,
            "images": img_urls
        }, priority=EventPriority.NORMAL)
