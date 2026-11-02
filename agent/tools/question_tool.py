"""主 Agent 显式 HITL 提问工具。"""
import hashlib
from typing import Annotated
from pydantic import Field

from langchain.tools import ToolRuntime
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.types import interrupt

from agent.questions import QuestionSpec, UserQuestion, _question_turn
from agent.tools.notification_tool import _current
from dao.question import QuestionDAO


@tool
def ask_user_question(reason: str, questions: list[UserQuestion], runtime: ToolRuntime,
                      timeout_seconds: Annotated[int, Field(ge=1200, le=86400, strict=True)] = 3600) -> dict:
    """关键决策缺少用户信息或授权时，向用户提问并持久暂停当前轮次。仅主 Agent 使用，必须单独调用。

    reason 说明为何需要用户决定；questions 每题包含 prompt、kind(single/multiple/text)、options。
    选择题自动增加 0=以上均不是并允许自填。单个选择题终端直接输入 1 或 1,2；
    文本/多题输入 1:小明,2:28岁。只问无法合理推断且影响任务的关键问题，勿对已授权操作反复确认。
    timeout_seconds 默认 3600，允许 1200–86400 秒。取消/超时按取消处理并结束本轮，不自行猜选项。
    Workflow 的 human 节点可由主 Agent 代问，只有 confirmed 才允许调用 workflow_resume。
    """
    turn = _question_turn.get()
    if turn is None or runtime.config.get('configurable', {}).get('thread_id') != f"session:{turn['session_key']}":
        return {'status': 'error', 'message': '仅供当前主 Agent 使用'}
    calls = next((m.tool_calls for m in reversed(runtime.state.get('messages', [])) if getattr(m, 'type', None) == 'ai'), [])
    if len(calls) != 1:
        return {'status': 'error', 'message': '必须单独调用 ask_user_question，不可并行其他工具'}
    spec = QuestionSpec(reason=reason, questions=questions, timeout_seconds=timeout_seconds).model_dump()
    origin = {k: v for k, v in turn['context'].items() if k in {
        'source', 'open_id', 'chat_id', 'chat_type', 'sender_type', 'session_key', 'message_id',
        '_event_type', 'feishu_reaction_active', 'feishu_typing_reaction_id'}}
    if origin.get('source') not in {None, '', 'terminal', 'feishu'}:
        # 无人值守事件由本机用户在终端接管；不猜测飞书收件人。
        origin = {'source': 'terminal'}
    if origin.get('source') == 'feishu' and not origin.get('open_id'):
        return {'status': 'error', 'message': '缺少人工确认接收人，无法发送飞书问题'}
    qid = 'ask-' + hashlib.sha256(f"{turn['session_key']}:{runtime.tool_call_id}".encode()).hexdigest()[:20]
    store = QuestionDAO()
    store.create(qid, turn['session_key'], spec, origin, turn['input'])
    result = interrupt({'kind': 'ask_user_question', 'question_id': qid})
    # 只相信经过原子提交的持久结果，模型不能伪造 resume 内容。
    row = store.get(qid)
    if not isinstance(result, dict) or row['status'] == 'pending' or result != row['result']:
        raise ValueError('人工回答未通过持久状态校验')
    if result['status'] in {'cancelled', 'timeout'}:
        notifications = _current.get()
        if notifications is not None:
            notifications.silent = True
            notifications.reason = '人工确认超时，按取消结束' if result['status'] == 'timeout' else '用户取消，本轮结束'
    return result



class QuestionCallGuard(AgentMiddleware):
    """一旦把提问与其他工具混用，整批拒绝，避免确认之前产生副作用。"""

    def wrap_tool_call(self, request, handler):
        calls = next((m.tool_calls for m in reversed(request.state.get('messages', []))
                      if getattr(m, 'type', None) == 'ai'), [])
        if len(calls) > 1 and any(c['name'] == 'ask_user_question' for c in calls):
            return ToolMessage(content='本批工具未执行：ask_user_question 必须单独调用，请先提问再决定后续操作。',
                               tool_call_id=request.tool_call['id'], name=request.tool_call['name'], status='error')
        return handler(request)
