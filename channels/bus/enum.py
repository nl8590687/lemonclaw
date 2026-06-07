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
Event Enums
"""

import enum

class EventType(enum.Enum):
    """
    事件类型枚举
    """
    TERMINAL = "terminal"            # 用户终端输入
    SCHEDULED_TASK = "scheduled"     # 定时任务触发
    WEBHOOK = "webhook"              # WebHook 回调
    SYSTEM = "system"                # 系统内部事件
    LARK_MESSAGE = "lark_message"    # 飞书消息
    CUSTOM = "custom"                # 自定义扩展事件


class EventPriority(enum.IntEnum):
    """
    事件优先级（越大优先级越高）
    """
    LOW = 10
    NORMAL = 50
    HIGH = 100
    URGENT = 200
