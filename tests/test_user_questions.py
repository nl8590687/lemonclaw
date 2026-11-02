"""主 Agent HITL：终端协议、持久恢复、超时取消及飞书回调。"""
import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import ValidationError
from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTrigger

from agent.questions import QuestionSpec, parse_terminal, validate_answers
from agent.tools.question_tool import ask_user_question
from dao.question import QuestionDAO
from tests.test_checkpoint import make_service, database  # noqa: F401


def spec(kind='single', fields=1, timeout=1200):
    return QuestionSpec(reason='需要确定负责人', timeout_seconds=timeout, questions=[
        {'prompt': f'问题{i}', 'kind': kind, 'options': [] if kind == 'text' else ['小明', '小王', '小李', '小赵', '小张']}
        for i in range(fields)]).model_dump()


def ask_message(payload=None, call_id='ask1'):
    return AIMessage(content='', tool_calls=[{'name': 'ask_user_question', 'args': payload or spec(), 'id': call_id}])


@pytest.mark.parametrize('kind,text,expected', [
    ('single','1',['小明']), ('single','3',['小李']), ('single',' 0 : 实际是小王 ',['实际是小王']),
    ('multiple','1,2',['小明','小王']), ('multiple','2,3,5',['小王','小李','小张']),
    ('multiple','0:实际是另一个小王',['实际是另一个小王'])])
def test_terminal_choices(kind, text, expected):
    assert parse_terminal(spec(kind), text)['answers'][0]['values'] == expected


@pytest.mark.parametrize('text', ['1:小明,2:28岁',' 1: 小明, 2 :18岁 '])
def test_terminal_text_fields(text):
    result = parse_terminal(spec('text', 2), text)
    assert result['answers'][0]['values'] == ['小明']
    assert result['answers'][1]['values'][0] in {'28岁','18岁'}


@pytest.mark.parametrize('text', ['0','0: ','1,2','6','-1','1,1','hello'])
def test_invalid_choice(text):
    with pytest.raises(ValueError):
        parse_terminal(spec(), text)


@pytest.mark.parametrize('timeout', [1199, 86401, 1200.5, True])
def test_timeout_bounds(timeout):
    with pytest.raises(ValidationError):
        spec(timeout=timeout)


def test_text_commas_and_mixed_questions():
    assert parse_terminal(spec('text'), '1: 北京,朝阳')['answers'][0]['values'] == ['北京,朝阳']
    payload = spec('multiple', 2)
    assert len(parse_terminal(payload, '1:1,2,2:0: 其他')['answers']) == 2
    with pytest.raises(ValueError):
        parse_terminal(spec('text',2),'1:a,1:b')


def test_resume_checkpoint_and_no_side_effect_replay(database):
    from langchain_core.tools import tool
    calls = []
    @tool
    def effect() -> str:
        """一次性操作。"""
        calls.append('once')
        return 'ok'
    start = AIMessage(content='', tool_calls=[{'name':'effect','args':{},'id':'effect1'}])
    first = make_service(responses=[start, ask_message()], tools=[effect, ask_user_question])
    waiting = first.run('请处理', {})
    assert waiting['awaiting_user'] and not waiting['completed']
    qid = waiting['question_id']
    assert first.questions.get(qid)['presented']
    first.close()
    second = make_service(responses=[AIMessage(content='已根据答案完成')], tools=[effect, ask_user_question])
    try:
        result = second.run(' 2 ', {})
        assert result['completed'] and result['messages'][-1].content == '已根据答案完成'
        answer = next(m for m in result['messages'] if isinstance(m, ToolMessage) and m.name == 'ask_user_question')
        assert json.loads(answer.content)['answers'][0]['values'] == ['小王']
        assert calls == ['once']
        assert second.questions.get(qid)['finished']
        assert not second.agent.get_state(second._thread_config()).next
    finally:
        second.close()


@pytest.mark.parametrize('cancel', [True,False])
def test_cancel_and_timeout_end_without_model(database, cancel):
    service = make_service(responses=[ask_message(), AIMessage(content='绝不应执行')], tools=[ask_user_question])
    try:
        waiting = service.run('处理', {})
        row = service.questions.get(waiting['question_id'])
        if cancel:
            result = service.run('/cancel', {})
        else:
            service.questions.ready(now=row['deadline']+1)
            result = service.run('[人工确认结果]', dict(row['origin'], _event_type='system', _question_ready_id=row['question_id']))
        assert result['completed'] and not result['reply_required']
        assert result['question_status'] == ('cancelled' if cancel else 'timeout')
        assert isinstance(result['messages'][-1], ToolMessage)
        assert '绝不应执行' not in str(result)
        assert not service.agent.get_state(service._thread_config()).next
        assert service.run('新任务', {})['messages'][-1].content == '绝不应执行'
    finally:
        service.close()


def test_invalid_answer_and_wrong_origin_remain_pending(database):
    service = make_service(responses=[ask_message()], tools=[ask_user_question])
    try:
        waiting = service.run('处理', {})
        assert service.run('hello', {})['awaiting_user']
        assert service.run('1', {'source':'feishu', 'open_id':'intruder','sender_type':'user'})['awaiting_user']
        assert service.questions.get(waiting['question_id'])['status'] == 'pending'
        service.run('/question', {})
        assert service.default_out_chan.write_message.call_count == 2
        service.reset_session()
        assert service.questions.get(waiting['question_id'])['finished']
    finally:
        service.close()


def card_event(row, fields=None, cancel=False, user='owner', message=None):
    action = {'tag':'button','name':f"ask_confirm__{row['question_id']}__{row['nonce']}", 'form_value': fields or {}}
    if cancel:
        action = {'tag':'button','value':{'action':'ask_cancel','question_id':row['question_id'],'nonce':row['nonce']}}
    return P2CardActionTrigger({'event': {'operator':{'open_id':user},
        'context':{'open_message_id':message or row['message_id'],'open_chat_id':'chat'}, 'action':action}})


def card_row(database, kind='single'):
    store = QuestionDAO()
    row = store.create('ask-test','session-default',spec(kind),
                       {'source':'feishu','open_id':'owner','chat_id':'chat','sender_type':'user'}, '处理')
    store.present(row['question_id'],'card1')
    return store,store.get(row['question_id'])


def test_native_card_and_callbacks(database):
    from channels.device.feishu import FeishuClient, question_card
    store,row = card_row(database,'multiple')
    client = FeishuClient(app_id='app',app_secret='secret')
    card = question_card(row)
    assert card['schema'] == '2.0'
    form = card['body']['elements'][2]
    assert form['tag'] == 'form'
    assert any(c['tag']=='multi_select_static' for c in form['elements'])
    assert form['elements'][-1]['form_action_type'] == 'submit'
    assert 'behaviors' not in form['elements'][-1]
    assert card['body']['elements'][-1]['behaviors'][0]['value']['action'] == 'ask_cancel'
    assert client._handle_question_action(card_event(row,{'q1':['0'],'q1_other':' 实际是小王 '})).toast.type == 'success'
    assert store.get(row['question_id'])['result']['answers'][0]['values'] == ['实际是小王']
    assert client._handle_question_action(card_event(row,{'q1':['1']})).toast.type == 'error'
    assert len(store.ready()) == 1


@pytest.mark.parametrize('what',['actor','message','empty_other','late','mixed_other'])
def test_callback_security_validation(database, what):
    from channels.device.feishu import FeishuClient
    store,row = card_row(database,'multiple')
    client = FeishuClient(app_id='app',app_secret='secret')
    kwargs = {'fields':{'q1':['1']}}
    if what=='actor': kwargs['user']='intruder'
    if what=='message': kwargs['message']='another-card'
    if what=='empty_other': kwargs['fields']={'q1':['0']}
    if what=='mixed_other': kwargs['fields']={'q1':['0','1'],'q1_other':'other'}
    if what=='late':
        from dao.db import get_connection
        with get_connection() as conn: conn.execute('UPDATE user_questions SET deadline=?',(time.time()-1,))
    assert client._handle_question_action(card_event(row,**kwargs)).toast.type == 'error'
    assert store.get(row['question_id'])['status'] == ('timeout' if what=='late' else 'pending')


def test_cancel_button_ignores_required_fields(database):
    from channels.device.feishu import FeishuClient
    store,row = card_row(database)
    client = FeishuClient(app_id='app',app_secret='secret')
    assert client._handle_question_action(card_event(row,cancel=True)).toast.type == 'success'
    assert store.get(row['question_id'])['result'] == {'status':'cancelled','action':'cancel','answers':[]}


def test_only_one_submission_wins(database):
    from concurrent.futures import ThreadPoolExecutor
    store,row = card_row(database)
    value = validate_answers(row['payload'],{'1':['1']})
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: store.submit(row['question_id'],value),range(4)))
    assert sum(results) == 1


@pytest.mark.parametrize('timeout', [False, True])
def test_loop_receives_question_result_and_updates_original_reaction(database, monkeypatch, timeout):
    import loop
    from channels.bus import EventType
    from channels.device.feishu import FeishuClient
    from dao.db import get_connection
    origin = {'source':'feishu','sender_type':'user','open_id':'owner','chat_id':'chat',
              'message_id':'original','feishu_reaction_active':True,'feishu_typing_reaction_id':'typing'}
    service = make_service(responses=[ask_message(), AIMessage(content='处理完成')], tools=[ask_user_question])
    client = FeishuClient(app_id='app',app_secret='secret')
    client._sender = MagicMock()
    client.sender.send_question.return_value = 'card1'
    monkeypatch.setattr('channels.device.feishu.get_feishu_client',lambda:client)
    count = 0
    def poll(**kwargs):
        nonlocal count
        count += 1
        if count == 1:
            return SimpleNamespace(event_type=EventType.LARK_MESSAGE,context=origin,content={'text':'处理'})
        if count == 2:
            with get_connection() as conn:
                qid = conn.execute('SELECT question_id FROM user_questions').fetchone()[0]
                if timeout: conn.execute('UPDATE user_questions SET deadline=?',(time.time()-1,))
            if not timeout:
                response = client._handle_question_action(card_event(service.questions.get(qid),{'q1':'2'}))
                assert response.toast.type == 'success'
            return None
        return SimpleNamespace(event_type=EventType.TERMINAL,context={},content={'text':'/quit'})
    bus = MagicMock()
    bus.poll.side_effect = poll
    monkeypatch.setattr(loop,'AgentService',lambda:service)
    monkeypatch.setattr(loop,'get_bus',lambda:bus)
    monkeypatch.setattr(loop,'get_output_channel',lambda _:service.default_out_chan)
    monkeypatch.setattr(loop,'handle_command',lambda *a,**k:False)
    monkeypatch.setattr(loop,'stop_event_source',lambda:None)
    loop.loop_forever()
    client.sender.delete_reaction.assert_called_once_with('original','typing')
    client.sender.add_reaction.assert_called_once_with('original','DONE')
    client.sender.close_question.assert_called_once()
    if timeout:
        service.default_out_chan.write_message.assert_not_called()
    else:
        service.default_out_chan.write_message.assert_called_once()
    with get_connection() as conn:
        assert conn.execute('SELECT finished FROM user_questions').fetchone()[0] == 1


def test_question_must_be_solo_tool(database):
    parallel = ask_message()
    parallel = AIMessage(content='', tool_calls=[*parallel.tool_calls,
        {'name':'ask_user_question','args':spec(),'id':'ask2'}])
    service = make_service(responses=[parallel,AIMessage(content='正常回复')],tools=[ask_user_question])
    try:
        assert service.run('处理', {})['messages'][-1].content == '正常回复'
        from dao.db import get_connection
        with get_connection() as conn:
            assert conn.execute('SELECT COUNT(*) FROM user_questions').fetchone()[0] == 0
    finally:
        service.close()


def test_overdue_question_survives_restart(database):
    first = make_service(responses=[ask_message()], tools=[ask_user_question])
    waiting = first.run('处理', {})
    row = first.questions.get(waiting['question_id'])
    first.close()
    from dao.db import get_connection
    with get_connection() as conn: conn.execute('UPDATE user_questions SET deadline=?',(time.time()-1,))
    second = make_service(responses=[AIMessage(content='不可运行')], tools=[ask_user_question])
    try:
        ready = second.questions.ready()
        assert ready[0]['status'] == 'timeout'
        result = second.run('[人工确认结果]', {'_event_type':'system','_question_ready_id':row['question_id']})
        assert result['question_status'] == 'timeout'
        assert not result['reply_required']
        assert second.questions.ready() == []
    finally:
        second.close()


def test_submit_twice_recovery_and_duplicate_ready_event(database):
    service = make_service(responses=[ask_message(), AIMessage(content='处理完成')], tools=[ask_user_question])
    try:
        waiting = service.run('处理', {})
        qid = waiting['question_id']
        row = service.questions.get(qid)
        result = parse_terminal(row['payload'], '1')
        assert service.questions.submit(qid,result)
        assert not service.questions.submit(qid,result)
        context = {'_event_type':'system','_question_ready_id':qid}
        assert service.run('[人工确认结果]',context)['completed']
        assert service.run('[重复人工确认结果]',context) is None
        assert service.default_out_chan.write_message.call_count == 2  # 问题 + 最终回复
    finally:
        service.close()


def test_webhook_cannot_answer_terminal_even_with_missing_source(database):
    service = make_service(responses=[ask_message()], tools=[ask_user_question])
    try:
        waiting = service.run('处理', {})
        assert service.run('1', {'_event_type':'webhook'})['awaiting_user']
        assert service.questions.get(waiting['question_id'])['status'] == 'pending'
    finally:
        service.close()


def test_card_senders_use_native_sdk_shape(database):
    from channels.device.feishu import FeishuMessageSender
    store,row = card_row(database)
    sender = object.__new__(FeishuMessageSender)
    sender.client = MagicMock()
    api = sender.client.im.v1.message
    api.create.return_value = SimpleNamespace(success=lambda:True,data=SimpleNamespace(message_id='new-card'))
    assert sender.send_question(row) == 'new-card'
    req = api.create.call_args.args[0]
    assert req.receive_id_type == 'chat_id'
    assert req.request_body.receive_id == 'chat'
    card = json.loads(req.request_body.content)
    assert card['header']['title']['content'] == '请求用户确认'
    api.patch.return_value = SimpleNamespace(success=lambda:True)
    sender.close_question(dict(row,status='timeout'))
    assert '已超时' in api.patch.call_args.args[0].request_body.content


def test_send_failure_does_not_create_unbounded_wait(database):
    service = make_service(responses=[ask_message()],tools=[ask_user_question])
    try:
        service.default_out_chan.write_message.side_effect = OSError('unavailable')
        waiting = service.run('处理', {})
        row = service.questions.get(waiting['question_id'])
        assert not row['presented'] and row['deadline'] > time.time()
        service.questions.ready(now=row['deadline']+1)
        result = service.run('[人工确认结果]',{'_event_type':'system','_question_ready_id':row['question_id']})
        assert result['question_status'] == 'timeout'
    finally:
        service.close()


def test_resume_does_not_refresh_deadline(database):
    service = make_service(responses=[ask_message()],tools=[ask_user_question])
    try:
        waiting = service.run('处理', {})
        before = service.questions.get(waiting['question_id'])
        service.run('/question', {})
        after = service.questions.get(waiting['question_id'])
        assert before['deadline'] == after['deadline']
    finally:
        service.close()


def test_other_session_runs_while_question_is_waiting(database):
    service = make_service(responses=[ask_message(), AIMessage(content='其他会话完成'), AIMessage(content='原会话完成')],
                           tools=[ask_user_question])
    try:
        waiting = service.run('处理', {}, session_key='a')
        assert waiting['awaiting_user']
        assert service.run('其他任务', {}, session_key='b')['messages'][-1].content == '其他会话完成'
        assert service.run('1', {}, session_key='a')['messages'][-1].content == '原会话完成'
    finally:
        service.close()


def test_mixed_question_batch_cannot_execute_side_effect(database):
    from langchain_core.tools import tool
    calls = []
    @tool
    def effect() -> str:
        """有副作用操作。"""
        calls.append('unsafe')
        return 'ok'
    question = ask_message()
    parallel = AIMessage(content='',tool_calls=[*question.tool_calls,{'name':'effect','args':{},'id':'unsafe'}])
    service = make_service(responses=[parallel,AIMessage(content='需要先确定问题')],tools=[ask_user_question,effect])
    try:
        assert service.run('处理', {})['completed']
        assert calls == []
    finally:
        service.close()
