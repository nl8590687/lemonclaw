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
运行层：WorkflowRunner

跑图 + 中断检测 + LangGraphLoop 事件发布。
worker 跑到 interrupt -> checkpoint 落 SqliteSaver -> 发 LangGraphLoop 普通消息事件到总线 -> worker 结束。
"""

import logging
from typing import Any

from langgraph.types import Command

from channels.bus import get_bus, EventType

logger = logging.getLogger(__name__)


class WorkflowRunner:
    """跑图 + 中断检测 + LangGraphLoop 事件发布"""

    def __init__(self, checkpointer, recursion_limit: int, result_max_chars: int):
        self.checkpointer = checkpointer
        self.recursion_limit = recursion_limit
        self.result_max_chars = result_max_chars

    def invoke(self, graph, run_id: str, workflow_id: str, input: dict,
               context: dict, dao) -> dict:
        """graph.invoke(input, thread_id=run_id) -> 处理返回（interrupt/completed/error）。
        返回 {status, loop_kind, payload}。"""
        config = {"configurable": {"thread_id": run_id},
                  "recursion_limit": self.recursion_limit}
        try:
            graph.invoke(input, config=config)
        except Exception as ex:
            # GraphInterrupt 或其他异常
            ex_str = str(ex)
            if "GraphInterrupt" in type(ex).__name__ or "interrupt" in ex_str.lower():
                pass  # interrupt 是预期的，下面检测
            else:
                logger.exception("workflow invoke error: %s", run_id)
                self._publish(run_id, workflow_id, "error", {"error": ex_str},
                              f"[工作流 {run_id} 出错] {ex_str}", context)
                return {"status": "error", "loop_kind": "error", "payload": {"error": ex_str}}

        # 检测中断
        interrupt_info = self._detect_interrupt(graph, config)
        if interrupt_info:
            loop_kind = interrupt_info.get("kind", "need_human")
            payload = interrupt_info
            text = self._make_text(run_id, workflow_id, loop_kind, payload)
            self._publish(run_id, workflow_id, loop_kind, payload, text, context)
            return {"status": "paused", "loop_kind": loop_kind, "payload": payload}

        # 完成
        state = graph.get_state(config)
        result = state.values if state else {}
        result_text = self._make_text(run_id, workflow_id, "completed", {"result": result})
        self._publish(run_id, workflow_id, "completed", {"result": result}, result_text, context)
        return {"status": "completed", "loop_kind": "completed", "payload": {"result": result}}

    def resume(self, graph, run_id: str, workflow_id: str, value, context: dict) -> dict:
        """graph.invoke(Command(resume=value), thread_id=run_id) -> 同 invoke 处理。"""
        config = {"configurable": {"thread_id": run_id},
                  "recursion_limit": self.recursion_limit}
        try:
            graph.invoke(Command(resume=value), config=config)
        except Exception as ex:
            ex_str = str(ex)
            if "GraphInterrupt" in type(ex).__name__ or "interrupt" in ex_str.lower():
                pass
            else:
                logger.exception("workflow resume error: %s", run_id)
                self._publish(run_id, workflow_id, "error", {"error": ex_str},
                              f"[工作流 {run_id} 出错] {ex_str}", context)
                return {"status": "error", "loop_kind": "error", "payload": {"error": ex_str}}

        interrupt_info = self._detect_interrupt(graph, config)
        if interrupt_info:
            loop_kind = interrupt_info.get("kind", "need_human")
            payload = interrupt_info
            text = self._make_text(run_id, workflow_id, loop_kind, payload)
            self._publish(run_id, workflow_id, loop_kind, payload, text, context)
            return {"status": "paused", "loop_kind": loop_kind, "payload": payload}

        state = graph.get_state(config)
        result = state.values if state else {}
        result_text = self._make_text(run_id, workflow_id, "completed", {"result": result})
        self._publish(run_id, workflow_id, "completed", {"result": result}, result_text, context)
        return {"status": "completed", "loop_kind": "completed", "payload": {"result": result}}

    def _detect_interrupt(self, graph, config) -> dict | None:
        """从 graph.get_state(config).tasks 读 interrupts[0].value。"""
        try:
            state = graph.get_state(config)
            if state and state.tasks:
                for task in state.tasks:
                    if hasattr(task, "interrupts") and task.interrupts:
                        return task.interrupts[0].value
            # 某些版本 state.next 非空也表示暂停
            if state and state.next:
                # 尝试从 state 取中断信息
                vals = state.values or {}
                if "__interrupt__" in vals:
                    return vals["__interrupt__"]
        except Exception:
            logger.exception("detect interrupt failed")
        return None

    def _make_text(self, run_id: str, workflow_id: str, loop_kind: str, payload: dict) -> str:
        """构造给主 Agent 的消息文本。"""
        if loop_kind == "need_human":
            q = payload.get("question", "")
            return f"[工作流 {run_id} 需人工] {q}\n回复时请带上 {run_id}。"
        if loop_kind == "need_main_agent":
            task = payload.get("task", "")
            return f"[工作流 {run_id} 回调主 Agent] 任务: {task}\n处理后请调 workflow_resume({run_id}, 回复)。"
        if loop_kind == "completed":
            result = payload.get("result", {})
            rstr = str(result)
            if len(rstr) > self.result_max_chars:
                half = self.result_max_chars // 2
                rstr = rstr[:half] + "\n[... 结果已截断 ...]\n" + rstr[-half:]
            return f"[工作流 {run_id} 已完成] 结果: {rstr}"
        if loop_kind == "error":
            return f"[工作流 {run_id} 出错] {payload.get('error','')}"
        return f"[工作流 {run_id}] {loop_kind}"

    def _publish(self, run_id: str, workflow_id: str, loop_kind: str,
                 payload: dict, text: str, context: dict):
        """发 LangGraphLoop 普通消息事件到总线。"""
        try:
            bus = get_bus()
            bus.publish(
                context or {},
                EventType.LANGGRAPH_LOOP,
                {
                    "run_id": run_id,
                    "workflow_id": workflow_id,
                    "loop_kind": loop_kind,
                    "payload": payload,
                    "text": text,
                },
            )
        except Exception:
            logger.exception("publish LangGraphLoop failed: %s", run_id)
