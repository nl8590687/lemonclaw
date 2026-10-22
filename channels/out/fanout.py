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
Fanout Output

把一个输出事件同时分发给多个已启用的输出通道（终端、飞书等）。
单个通道异常不会中断其他通道的输出。
"""

import logging

from channels.out.base import BaseOutChannel


logger = logging.getLogger(__name__)


class FanoutOutputChannel(BaseOutChannel):
    """
    聚合输出通道

    持有若干子通道，所有输出方法都会按顺序广播给每个子通道。
    """

    def __init__(self, channels: list[BaseOutChannel]):
        super().__init__()
        self.channels = list(channels)

    def write_message(self, msg: str, context: dict[str, object]):
        self._fanout("write_message", msg, context)

    def print(self, msg: str):
        self._fanout("print", msg)

    def write_tool_calling(self, tool_name: str, param_str: str):
        self._fanout("write_tool_calling", tool_name, param_str)

    def write_tool_result(self, output: object):
        self._fanout("write_tool_result", output)

    def write_tool_error(self, error: BaseException):
        self._fanout("write_tool_error", error)

    def write_menu_content(self, content: object):
        self._fanout("write_menu_content", content)

    def write_system_error(self, content: str):
        self._fanout("write_system_error", content)

    def _fanout(self, method_name: str, *args, **kwargs):
        for channel in self.channels:
            try:
                getattr(channel, method_name)(*args, **kwargs)
            except Exception:
                logger.exception(
                    "output channel %s.%s failed",
                    type(channel).__name__,
                    method_name,
                )
