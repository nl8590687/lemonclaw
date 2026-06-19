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
Crontab 定时任务设备

包含三部分：

1. ``CronExpression`` / ``parse_cron`` / ``validate_cron`` — Cron 表达式解析
2. ``CronScheduler`` — 后台调度线程，到点回调上层 ``on_trigger``
3. ``CronTaskManager`` — 门面类，封装了 DAO 增删改查 + 调度器联动

任务持久化通过 ``dao.CronTaskDAO`` 写入全局 ``.lemonclaw/lemonclaw.db``。

注意：本设备本身不直接写消息总线，向 ``MessageBus`` 投递事件的逻辑
统一交给 ``channels.ins.crontab.CrontabInput`` 通过回调完成，
与 ``channels/ins/webhook.py`` 的写法保持一致。
"""

import threading
import uuid
from datetime import datetime, timedelta
from typing import Callable, Optional

from dao import CronTask, CronTaskDAO


# 触发回调签名（与 webhook 的 _write_message 保持兼容）：
#   (text, img_urls, context) -> event_id
TriggerCallback = Callable[[str, Optional[list[str]], dict[str, object]], str]


# =====================================================================
# Cron 表达式解析
# =====================================================================

# 预定义的快捷表达式
CRON_PRESETS: dict[str, str] = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@hourly": "0 * * * *",
    "@minutely": "* * * * *",
}


def _parse_cron_field(field: str, min_val: int, max_val: int) -> set[int]:
    """解析单个 cron 字段，支持 ``*``、``a,b``、``a-b``、``*/n``、``a/n``"""
    if field == "*":
        return set(range(min_val, max_val + 1))

    result: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start = int(start_s.strip())
            end = int(end_s.strip())
            result.update(range(start, end + 1))
        elif "/" in part:
            base, step_s = part.split("/", 1)
            step = int(step_s.strip())
            start = min_val if base == "*" else int(base.strip())
            for i in range(start, max_val + 1, step):
                result.add(i)
        else:
            result.add(int(part.strip()))

    return result


class CronExpression:
    """
    简单的 5 字段 Cron 表达式解析器：``分 时 日 月 周``

    周字段 0 表示周日（与 crontab 标准一致）。
    """

    def __init__(self, expression: str):
        self.expression = expression.strip()
        parts = self.expression.split()

        if len(parts) < 5:
            raise ValueError(f"Invalid CRON expression: expecting 5 fields, got {len(parts)}: {expression!r}")

        self.minute = _parse_cron_field(parts[0], 0, 59)
        self.hour = _parse_cron_field(parts[1], 0, 23)
        self.day = _parse_cron_field(parts[2], 1, 31)
        self.month = _parse_cron_field(parts[3], 1, 12)
        # 0=周日
        self.weekday = _parse_cron_field(parts[4], 0, 6)

    def matches(self, dt: datetime) -> bool:
        """检查 dt 是否匹配本表达式"""
        if dt.minute not in self.minute:
            return False
        if dt.hour not in self.hour:
            return False
        if dt.month not in self.month:
            return False

        # 标准 cron 中"日"和"周"是"或"关系
        day_match = dt.day in self.day
        # isoweekday: 1=周一 ... 7=周日；映射为 0=周日，1=周一，...，6=周六
        weekday_match = (dt.isoweekday() % 7) in self.weekday
        return day_match or weekday_match

    def next_run(self, from_dt: Optional[datetime] = None) -> datetime:
        """计算下次运行时间（线性搜索，最长 4 年）"""
        dt = (from_dt or datetime.now()).replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(4 * 366 * 24 * 60):
            if self.matches(dt):
                return dt
            dt += timedelta(minutes=1)
        raise ValueError("No next run time found within 4 years")

    def __str__(self) -> str:
        return self.expression


def parse_cron(expression: str) -> CronExpression:
    """解析 Cron 表达式，支持 ``@daily``/``@hourly`` 等预设"""
    expr = expression.strip().lower()
    if expr in CRON_PRESETS:
        expr = CRON_PRESETS[expr]
    return CronExpression(expr)


def validate_cron(expression: str) -> tuple[bool, str]:
    """验证 Cron 表达式，返回 (是否合法, 错误信息)"""
    try:
        parse_cron(expression)
        return True, ""
    except Exception as e:
        return False, str(e)


# =====================================================================
# 调度器
# =====================================================================

class CronScheduler:
    """
    Cron 任务调度器

    每分钟检查一次内存中持有的任务，匹配则调用 ``on_trigger`` 回调，
    由上层（``CrontabInput``）决定如何投递到消息总线。
    """

    def __init__(self, on_trigger: Optional[TriggerCallback] = None):
        self._tasks: dict[str, tuple[CronTask, CronExpression]] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._on_trigger: Optional[TriggerCallback] = on_trigger
        # 防止同一分钟重复触发的标记，记录上次检查的"分钟"
        self._last_minute_key: str | None = None

    # ---- 回调 ----

    def set_on_trigger(self, on_trigger: Optional[TriggerCallback]) -> None:
        self._on_trigger = on_trigger

    # ---- 任务集合 ----

    def add_task(self, task: CronTask) -> bool:
        try:
            expr = parse_cron(task.cron_expression)
        except Exception:
            return False
        with self._lock:
            self._tasks[task.task_id] = (task, expr)
        return True

    def update_task(self, task: CronTask) -> bool:
        if not task.enabled:
            self.remove_task(task.task_id)
            return True
        return self.add_task(task)

    def remove_task(self, task_id: str) -> None:
        with self._lock:
            self._tasks.pop(task_id, None)

    def get_task(self, task_id: str) -> CronTask | None:
        with self._lock:
            entry = self._tasks.get(task_id)
            return entry[0] if entry else None

    def list_tasks(self) -> list[CronTask]:
        with self._lock:
            return [t for t, _ in self._tasks.values()]

    # ---- 生命周期 ----

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="cron-scheduler"
        )
        self._thread.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)

    def _loop(self) -> None:
        """调度主循环：每秒醒来一次，跨越分钟边界时检查匹配"""
        while self._running and not self._stop_event.is_set():
            now = datetime.now()
            minute_key = now.strftime("%Y%m%d%H%M")
            if minute_key != self._last_minute_key:
                self._last_minute_key = minute_key
                try:
                    self._check_and_run(now)
                except Exception:
                    # 调度器主循环不应被单个任务影响
                    pass
            self._stop_event.wait(timeout=1.0)

    def _check_and_run(self, now: datetime) -> None:
        with self._lock:
            to_run = [
                task for task, expr in self._tasks.values()
                if task.enabled and expr.matches(now)
            ]

        for task in to_run:
            self._fire(task)

    def _fire(self, task: CronTask) -> None:
        """命中后调用上层回调，由调用方决定如何投递事件"""
        if self._on_trigger is None:
            return
        try:
            self._on_trigger(
                task.prompt,
                None,
                {
                    "source": "cron",
                    "task_id": task.task_id,
                    "cron_expression": task.cron_expression,
                },
            )
        except Exception:
            # 单个任务投递失败不应拖垮调度器
            pass


# =====================================================================
# 管理器（门面）
# =====================================================================

class CronTaskManager:
    """
    定时任务管理器（门面模式）

    把 ``CronTaskDAO`` 与 ``CronScheduler`` 组合在一起，对外提供完整的 CRUD
    与启停接口。任务命中时通过 ``on_trigger`` 回调把事件交给上层
    （通常是 ``CrontabInput``）写入消息总线。
    """

    def __init__(self, on_trigger: Optional[TriggerCallback] = None):
        self.dao = CronTaskDAO()
        self.scheduler = CronScheduler(on_trigger=on_trigger)

    # ---- 回调 ----

    def set_on_trigger(self, on_trigger: Optional[TriggerCallback]) -> None:
        self.scheduler.set_on_trigger(on_trigger)

    # ---- 加载/启停 ----

    def load_tasks(self) -> int:
        """从数据库加载所有启用任务到调度器，返回加载条数"""
        tasks = self.dao.list_all(include_disabled=True)
        loaded = 0
        for task in tasks:
            if task.enabled and self.scheduler.add_task(task):
                loaded += 1
        return loaded

    def start(self) -> None:
        self.load_tasks()
        self.scheduler.start()

    def stop(self) -> None:
        self.scheduler.stop()

    # ---- CRUD ----

    def create_task(
        self,
        prompt: str,
        cron_expression: str,
        prompt_original: str = "",
        enabled: bool = True,
    ) -> CronTask:
        """创建任务，cron 表达式非法会抛 ``ValueError``"""
        valid, msg = validate_cron(cron_expression)
        if not valid:
            raise ValueError(f"Invalid CRON expression: {msg}")

        now = datetime.now()
        task = CronTask(
            task_id=f"cron_{uuid.uuid4().hex[:16]}",
            prompt=prompt,
            prompt_original=prompt_original or prompt,
            cron_expression=cron_expression,
            created_at=now,
            updated_at=now,
            enabled=enabled,
        )

        if not self.dao.insert(task):
            raise RuntimeError(f"Failed to insert cron task {task.task_id}")

        if enabled:
            self.scheduler.add_task(task)

        return task

    def update_task(
        self,
        task_id: str,
        prompt: Optional[str] = None,
        cron_expression: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> CronTask | None:
        """更新任务，未找到返回 ``None``，cron 非法抛 ``ValueError``"""
        task = self.dao.get(task_id)
        if not task:
            return None

        if cron_expression is not None:
            valid, msg = validate_cron(cron_expression)
            if not valid:
                raise ValueError(f"Invalid CRON expression: {msg}")
            task.cron_expression = cron_expression
        if prompt is not None:
            task.prompt = prompt
        if enabled is not None:
            task.enabled = enabled
        task.updated_at = datetime.now()

        if not self.dao.update(task):
            return None

        # 同步调度器
        self.scheduler.update_task(task)
        return task

    def delete_task(self, task_id: str) -> bool:
        self.scheduler.remove_task(task_id)
        return self.dao.delete(task_id)

    def enable_task(self, task_id: str) -> bool:
        return self.update_task(task_id, enabled=True) is not None

    def disable_task(self, task_id: str) -> bool:
        return self.update_task(task_id, enabled=False) is not None

    def get_task(self, task_id: str) -> CronTask | None:
        return self.dao.get(task_id)

    def list_tasks(self, include_disabled: bool = True) -> list[CronTask]:
        return self.dao.list_all(include_disabled=include_disabled)

    def mark_run(self, task_id: str) -> None:
        """记录任务执行时间（投递成功后或处理完成后调用）"""
        self.dao.update_last_run(task_id, datetime.now())
