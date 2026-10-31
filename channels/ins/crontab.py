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
from channels.device.crontab import get_cron_manager
from channels.ins.base import BaseInChannel


class CrontabInput(BaseInChannel):
    """
    Cron 输入：绑定的 Workflow 后台启动，提示词任务投递消息总线。
    """

    def __init__(self):
        super().__init__()
        # 复用全局单例，保证 Agent 工具 / /cron 指令与本调度器操作同一实例
        self.manager = get_cron_manager()
        self.manager.set_on_trigger(self._write_message)

    def run(self):
        self.manager.start()

    def _write_message(self, msg: str, img_urls: list[str] | None = None, context: dict[str, object] = None) -> str:
        if context and context.get("workflow_id"):
            from agent.workflow import get_workflow_manager
            manager = get_workflow_manager()
            if manager is None:
                raise ValueError("Workflow 未启用")
            wf = manager.get_workflow(context["workflow_id"])
            if wf is None or (wf.spec or {}).get("one_shot"):
                raise ValueError("周期任务需要可复用的 Workflow 定义")
            from agent.workflow.context import origin_context
            origin = origin_context({"configurable": {"origin_context": context.get("origin_context", {})}})
            origin.update({key: context[key] for key in ("task_id", "cron_expression") if key in context})
            run_id, info = manager.start_run(wf.workflow_id, context.get("workflow_input", {}), origin)
            if run_id is None:
                raise ValueError(f"启动周期 Workflow 失败: {info.get('error')}")
            return run_id
        bus = get_bus()
        if not context:
            context = {}
        return bus.publish(context=context, event_type=EventType.SCHEDULED_TASK, content={
            "text": msg,
            "images": img_urls
        }, priority=EventPriority.NORMAL)