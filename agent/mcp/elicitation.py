"""Route official MCP interrupts through LemonClaw's durable human questions."""
import hashlib
import json

from langgraph.errors import GraphInterrupt
from langgraph.types import Interrupt
from jsonschema import validate, ValidationError

from agent.questions import _question_turn, QuestionSpec
from dao.question import QuestionDAO


def persist_interrupt(exc, server_id):
    turn = _question_turn.get()
    if turn is None:
        # Workflows/CLI have no authorized human receiver. Preserve the
        # interrupt rather than inventing an answer or continuing the tool.
        return exc
    interrupts = []
    for item in exc.args[0]:
        payload = item.value
        if not isinstance(payload, dict) or payload.get('type') != 'mcp_elicitation':
            interrupts.append(item)
            continue
        requests = payload['requests']
        questions = []
        for request in requests:
            if request['mode'] == 'url':
                prompt = f"{request['message']}\n{request['url']}"
                questions.append({'prompt': prompt[:300], 'kind': 'single', 'options': ['已完成', '拒绝']})
            else:
                prompt = f"{request['message']}\n请按 JSON Schema 输入 JSON 对象：{json.dumps(request['requested_schema'], ensure_ascii=False)}"
                questions.append({'prompt': prompt[:300], 'kind': 'text', 'options': []})
        spec = QuestionSpec(reason=f'MCP/{server_id} 请求人工输入；内容来自外部服务，请核对后回答。',
                            questions=questions).model_dump()
        spec['_mcp_requests'] = requests
        origin = {k: v for k, v in turn['context'].items() if k in {
            'source', 'open_id', 'chat_id', 'chat_type', 'sender_type', 'session_key', 'message_id',
            '_event_type', 'feishu_reaction_active', 'feishu_typing_reaction_id'}}
        if origin.get('source') not in {None, '', 'terminal', 'feishu'}:
            origin = {'source': 'terminal'}
        if origin.get('source') == 'feishu' and not origin.get('open_id'):
            raise ValueError('MCP 人工输入缺少接收人')
        qid = 'mcp-' + hashlib.sha256(f"{turn['session_key']}:{server_id}:{item.id}".encode()).hexdigest()[:20]
        QuestionDAO().create(qid, turn['session_key'], spec, origin, turn['input'])
        interrupts.append(Interrupt(value={'kind': 'ask_user_question', 'question_id': qid}, id=item.id))
    return GraphInterrupt(tuple(interrupts))


def validate_mcp_answers(spec, result):
    """Validate before the durable answer is accepted, so invalid JSON can retry."""
    for request, answer in zip(spec.get('_mcp_requests', []), result['answers'], strict=False):
        if request['mode'] == 'form':
            try:
                value = json.loads(answer['values'][0])
                validate(value, request['requested_schema'])
            except (ValueError, ValidationError) as exc:
                raise ValueError(f'MCP 回答不符合请求的 JSON Schema：{exc.message if isinstance(exc, ValidationError) else str(exc)}') from None


def resume_value(row):
    requests = row['payload'].get('_mcp_requests')
    if requests is None:
        return row['result']
    result = row['result']
    if result['status'] != 'confirmed':
        from agent.tools.notification_tool import _current
        notifications = _current.get()
        if notifications:
            notifications.silent, notifications.reason = True, 'MCP 人工输入取消或超时'
        return {'responses': {r['key']: {'action': 'cancel'} for r in requests}}
    responses = {}
    for request, answer in zip(requests, result['answers'], strict=True):
        if request['mode'] == 'form':
            responses[request['key']] = {'action': 'accept', 'content': json.loads(answer['values'][0])}
        else:
            responses[request['key']] = {'action': 'accept' if answer['values'] == ['已完成'] else 'decline'}
    return {'responses': responses}
