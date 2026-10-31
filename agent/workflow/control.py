"""工作流运行控制：协作取消、节点期限和失败重试。"""

import contextvars
import queue
import threading
import time

from langchain_core.callbacks import BaseCallbackHandler
from langgraph.errors import GraphBubbleUp


class WorkflowStopped(BaseException):
    """在工具异常处理之外传播运行停止信号。"""


class NodeTimeout(WorkflowStopped):
    pass


class RunControl:
    def __init__(self, parent=None, timeout=None, name=""):
        self.name = name
        self.parent = parent
        self.cancelled = threading.Event()
        self.lock = threading.RLock()
        self.failure = None
        self.deadline = time.monotonic() + timeout if timeout else None

    def fail(self, error):
        if self.parent:
            self.parent.fail(error)
        else:
            self.failure = error

    def check(self):
        if self.parent:
            self.parent.check()
        if self.failure is not None:
            raise self.failure
        if self.cancelled.is_set():
            raise WorkflowStopped("工作流已取消")
        if self.deadline and time.monotonic() >= self.deadline:
            raise NodeTimeout(f"节点 {self.name} 超时；阻塞调用线程仍可能运行，已阻止后续调用")


_current = contextvars.ContextVar("workflow_control", default=None)
# 未结束的阻塞调用占用容量，防止重复超时耗尽进程资源。
_slots = threading.BoundedSemaphore(32)


def current_control():
    return _current.get()


def check_control():
    control = current_control()
    if control:
        control.check()


class ControlCallback(BaseCallbackHandler):
    raise_error = True

    def __init__(self, control):
        self.control = control

    def on_tool_start(self, *args, **kwargs):
        self.control.check()

    def on_chat_model_start(self, *args, **kwargs):
        self.control.check()

    def on_llm_start(self, *args, **kwargs):
        self.control.check()


def controlled_node(fn, nc, name, compensation=None):
    """每次仅重试当前失败节点；已完成节点由图的 checkpoint 保留。"""
    def run(state, config=None):
        parent = current_control()
        for attempt in range(nc.get("max_retries", 0) + 1):
            if parent:
                parent.check()
            control = RunControl(parent, nc.get("timeout_seconds", 300), name)
            control.propagate_errors = any(k in nc for k in ("max_retries", "on_error", "timeout_seconds"))
            result = queue.Queue(maxsize=1)
            if not _slots.acquire(blocking=False):
                raise RuntimeError("后台阻塞节点达到容量上限，请等待未结束调用释放")
            ctx = contextvars.copy_context()

            def invoke():
                token = _current.set(control)
                try:
                    control.check()
                    result.put((True, fn(state, config)))
                except BaseException as ex:
                    result.put((False, ex))
                finally:
                    _current.reset(token)
                    _slots.release()

            thread = threading.Thread(target=ctx.run, args=(invoke,), daemon=True, name=f"wf-node-{name}")
            thread.start()
            try:
                while True:
                    control.check()
                    try:
                        success, value = result.get(timeout=0.05)
                        break
                    except queue.Empty:
                        continue
                control.check()
                if success:
                    return value
                # GraphInterrupt 等 BaseException 必须交还 LangGraph 处理。
                if isinstance(value, GraphBubbleUp) or not isinstance(value, Exception):
                    raise value
                raise value
            except GraphBubbleUp:
                raise
            except NodeTimeout as ex:
                if parent:
                    parent.fail(ex)
                # 超时调用可能已经产生副作用，禁止重试或补偿重放。
                raise
            except Exception as ex:
                if attempt < nc.get("max_retries", 0):
                    end = time.monotonic() + nc.get("retry_backoff", 1) * (2 ** attempt)
                    while time.monotonic() < end:
                        if parent:
                            parent.check()
                        time.sleep(min(0.05, max(0, end - time.monotonic())))
                    continue
                if nc.get("on_error") == "compensate" and compensation:
                    return controlled_node(compensation, {"timeout_seconds": nc.get("timeout_seconds", 300)}, name + "-compensate")(state, config)
                if nc.get("on_error", "fail") == "continue":
                    output = nc.get("output_field", {"human": "user_input", "subagent": "agent_reply", "main_agent": "agent_reply"}.get(nc.get("kind"), "output"))
                    return {output: f"❌ 节点 {name} 执行出错: {ex}"}
                if parent:
                    parent.fail(ex)
                raise
    return run
