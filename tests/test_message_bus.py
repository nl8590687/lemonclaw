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

"""消息总线优先级、FIFO 与容量测试。"""

import threading
import unittest

from channels.bus.enum import EventPriority, EventType
from channels.bus.message_bus import MessageBus, MsgBusCapacityException


class MessageBusTest(unittest.TestCase):
    def test_higher_priority_is_polled_first(self):
        bus = MessageBus(capacity=10)
        priorities = [
            EventPriority.LOW,
            EventPriority.NORMAL,
            EventPriority.HIGH,
            EventPriority.URGENT,
        ]
        for priority in priorities:
            bus.publish({}, EventType.CUSTOM, {"text": priority.name}, priority)

        messages = [bus.get_nowait() for _ in priorities]

        self.assertEqual(
            [message.priority for message in messages],
            [
                EventPriority.URGENT,
                EventPriority.HIGH,
                EventPriority.NORMAL,
                EventPriority.LOW,
            ],
        )

    def test_same_priority_is_fifo(self):
        bus = MessageBus(capacity=10)
        for index in range(10):
            bus.publish({}, EventType.CUSTOM, {"text": str(index)}, EventPriority.NORMAL)

        messages = [bus.get_nowait() for _ in range(10)]

        self.assertEqual([message.content["text"] for message in messages], [str(index) for index in range(10)])

    def test_poll_returns_none_on_timeout(self):
        bus = MessageBus(capacity=1)

        self.assertIsNone(bus.poll(timeout=0.01))

    def test_concurrent_publish_does_not_exceed_capacity(self):
        capacity = 5
        worker_count = 16
        bus = MessageBus(capacity=capacity)
        barrier = threading.Barrier(worker_count)
        result_lock = threading.Lock()
        accepted = 0
        rejected = 0

        def publish(index: int):
            nonlocal accepted, rejected
            barrier.wait()
            try:
                bus.publish({}, EventType.CUSTOM, {"text": str(index)}, EventPriority.NORMAL)
            except MsgBusCapacityException:
                with result_lock:
                    rejected += 1
            else:
                with result_lock:
                    accepted += 1

        threads = [threading.Thread(target=publish, args=(index,)) for index in range(worker_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        self.assertEqual(accepted, capacity)
        self.assertEqual(rejected, worker_count - capacity)
        self.assertEqual(bus.qsize(), capacity)


if __name__ == "__main__":
    unittest.main()