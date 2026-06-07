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
Event Bus Message
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from channels.bus.enum import EventType, EventPriority


@dataclass(order=True)
class EventMessage:
    """
    事件消息数据类
    """
    priority: EventPriority
    timestamp: datetime = field(init=False, compare=True)
    event_id: str = field(init=False, compare=False)
    event_type: EventType = field(compare=False)
    content: dict[str, Any] = field(compare=False)
    context: dict[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self):
        self.timestamp = datetime.now()
        self.event_id = str(uuid4())
