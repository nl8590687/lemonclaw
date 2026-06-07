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
        while True:
            try:
                user_input = self.console.input("[bold green]你[/] > ").strip()
                if not user_input:
                    continue
                self._write_message(user_input)
            except KeyboardInterrupt as ex:
                self.console.print("\n\n[warning]再见！[/warning]")
                break
            except EOFError as ex:
                continue

    def _write_message(self, msg: str, img_urls: list[str] | None = None, context: dict[str, object] = None) -> str:
        bus = get_bus()
        if not context:
            context = {}
        return bus.publish(context=context, event_type=EventType.TERMINAL, content={
            "text": msg,
            "images": img_urls
        }, priority=EventPriority.NORMAL)
