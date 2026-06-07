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
事件总线核心模块

提供线程安全的消息队列、事件定义和消息总线核心功能。
支持多种事件源：终端输入、定时任务、WebHook 等。
"""

import queue
import threading
from typing import Any

from channels.bus.enum import EventType, EventPriority
from channels.bus.event import EventMessage


class MsgBusCapacityException(BaseException):
    def __init__(self, msg: str):
        self.msg = msg


class MessageBus:
    """
    线程安全的消息总线

    特性:
    - 优先级队列：支持高优先级事件优先处理
    - 线程安全：使用锁保护队列操作
    - 事件订阅：支持回调函数订阅特定类型事件
    - 历史记录：保留最近的事件记录
    """

    def __init__(self, capacity: int = 1000):
        self.capacity = capacity
        self._queue: queue.PriorityQueue = queue.PriorityQueue()
        self._lock: threading.Lock = threading.Lock()
        self._condition: threading.Condition = threading.Condition(self._lock)

    def publish(self, context: dict[str, object], event_type: EventType, content: dict[str, Any],
        priority: EventPriority = EventPriority.NORMAL) -> str:
        """
        发布事件到消息总线

        :param context: 上下文
        :param event_type: 事件类型
        :param content: 事件内容数据
        :param priority: 优先级
        :return: 事件ID
        """
        if self._queue.qsize() >= self.capacity:
            raise MsgBusCapacityException(f"Messages in message bus exceeded capacity {self.capacity}")

        msg = EventMessage(
            priority=priority,
            event_type=event_type,
            content=content,
            context=context or {},
        )

        with self._lock:
            self._queue.put(msg)
            self._condition.notify_all()

        return msg.event_id

    def poll(self, timeout: float|None = None):
        """
        从队列获取事件（阻塞直到获取或超时）

        Args:
            timeout: 超时时间（秒），None 表示无限等待

        Returns:
            EventMessage 或 None（超时）
        """
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def get_nowait(self) -> EventMessage|None:
        """
        非阻塞获取事件
        """
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def qsize(self) -> int:
        """获取当前队列长度"""
        return self._queue.qsize()

    def is_empty(self) -> bool:
        """队列是否为空"""
        return self._queue.empty()

    def clear(self):
        """清空队列"""
        with self._lock:
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break


# 全局消息总线单例
_bus_instance: MessageBus|None = None
_bus_lock = threading.Lock()


def get_bus() -> MessageBus:
    """
    获取全局消息总线单例
    """
    global _bus_instance
    if _bus_instance is None:
        with _bus_lock:
            if _bus_instance is None:
                _bus_instance = MessageBus()
    return _bus_instance


def set_bus(bus: MessageBus):
    """设置全局消息总线（用于测试）"""
    global _bus_instance
    with _bus_lock:
        _bus_instance = bus
