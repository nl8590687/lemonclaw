"""当前主 Agent 轮次的关键通知和显式静默完成。"""
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Lock
from typing import Literal

from langchain_core.tools import tool
from langchain.tools import ToolRuntime
from langchain.agents.middleware import AgentMiddleware, hook_config


@dataclass
class TurnNotifications:
    output: object
    context: dict
    background: bool = False
    sent: set = field(default_factory=set)
    delivered: bool = False
    silent: bool = False
    reason: str = ''
    lock: Lock = field(default_factory=Lock)


_current: ContextVar[TurnNotifications | None] = ContextVar('turn_notifications', default=None)


def begin_notifications(output, context):
    # 飞书用户消息始终按主动请求处理；后台事件由消息总线标记。
    background = context.get('_event_type') in {'webhook', 'system', 'langgraph_loop', 'custom'}
    state = TurnNotifications(output, context, background)
    return state, _current.set(state)


def reset_notifications(token):
    _current.reset(token)


@tool
def notify_progress(message: str, kind: Literal['key_progress', 'delivered_result'] = 'key_progress') -> str:
    """仅在必要时通知当前会话：重要阶段完成、实质阻碍，或完整交付结果。

    简单任务直接最终回复。禁止播报推理、调试信息、每次工具调用或重复内容。
    kind=delivered_result 仅用于已完整满足用户请求的最终交付；普通进度不能标为结果。
    需要用户回答时发送最终提问并结束本轮，不要用本工具假装等待。
    """
    state = _current.get()
    if state is None:
        return '不可用：仅供当前主 Agent 轮次使用。'
    message = message.strip()
    if not message or len(message) > 2000:
        return '未发送：通知须为 1–2000 字。'
    with state.lock:
        if state.silent or message in state.sent or len(state.sent) >= 3:
            return '未发送：本轮已结束、内容重复或已达到三条通知上限。'
        if state.output.write_message(message, state.context) is False:
            return '通知发送失败：未标记为已交付，请处理发送问题并正常反馈。'
        state.sent.add(message)
        state.delivered |= kind == 'delivered_result'
    return '通知已发送。继续执行；最终答复避免重复已交付内容。'


@tool
def finish_silently(reason: str, outcome: Literal['no_action_needed', 'already_delivered'],
                    runtime: ToolRuntime) -> str:
    """完成当前轮次并结束 ReAct，不再发送最终文本。必须单独调用。

    默认事事有回音：用户主动请求必须最终答复。只有以下情况可使用：
    1. 后台事件已检查且无变化、无需用户关注（no_action_needed）。
    2. 已通过 notify_progress(kind=delivered_result) 完整交付（already_delivered）。
    定时推送、用户要求的报告、异常、待确认事项必须正常交付，不可静默跳过。
    reason 为必要的内部完成依据，不包含敏感数据。普通进度或未完成任务不算交付。
    """
    state = _current.get()
    if state is None:
        return '静默结束被拒绝：仅供当前主 Agent 轮次使用。'
    messages = runtime.state.get('messages', [])
    last_ai = next((msg for msg in reversed(messages) if getattr(msg, 'type', None) == 'ai'), None)
    if last_ai is None or len(last_ai.tool_calls) != 1:
        return '静默结束被拒绝：必须单独调用，不能与其他工具并行。'
    if not reason.strip() or len(reason) > 1000:
        return '静默结束被拒绝：必须提供 1–1000 字的完成依据。'
    with state.lock:
        if not ((outcome == 'no_action_needed' and state.background) or
                (outcome == 'already_delivered' and state.delivered)):
            return '静默结束被拒绝：主动请求需要回复，或结果尚未完整交付。请继续完成任务并正常回复。'
        state.silent = True
        state.reason = reason.strip()
    return '本轮已完成，无需重复回复。'


class TurnCompletionMiddleware(AgentMiddleware):
    """工具结果保存后，在下一次模型请求前结束已成功静默的轮次。"""

    @hook_config(can_jump_to=['end'])
    def before_model(self, state, runtime):
        current = _current.get()
        if current is not None and current.silent:
            return {'jump_to': 'end'}
        return None
