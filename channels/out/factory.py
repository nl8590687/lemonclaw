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
Output Channel Factory
"""

from channels.out.base import BaseOutChannel
from channels.out.fanout import FanoutOutputChannel
from channels.out.feishu import FeishuOutputChannel
from channels.out.stdout import TerminalOutputChannel
from config import get_global_config


def build_output_channels(context: dict[str, object] | None = None) -> list[BaseOutChannel]:
    """
    按配置构造所有启用的输出通道。

    终端始终启用；``ENABLE_FEISHU=true`` 时追加飞书输出通道。
    传入 ``context`` 时，飞书通道会优先回复该上下文中的 ``open_id``。
    """
    channels: list[BaseOutChannel] = [TerminalOutputChannel()]
    if get_global_config().ENABLE_FEISHU:
        open_id = context.get("open_id") if isinstance(context, dict) else None
        channels.append(
            FeishuOutputChannel(open_id if isinstance(open_id, str) and open_id else None)
        )
    return channels


def build_output_channel(context: dict[str, object] | None = None) -> BaseOutChannel:
    """构造聚合输出通道：一次输出广播到所有启用的输出通道。"""
    return FanoutOutputChannel(build_output_channels(context))
