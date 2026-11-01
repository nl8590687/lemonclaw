"""机器人用户消息表情状态与异常隔离。"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

import channels.device.feishu as feishu
from channels.device.feishu import finish_reaction, reaction_eligible
from tests.test_feishu_file_receive import _event


@pytest.fixture
def receiver(monkeypatch):
    from config import get_global_config
    monkeypatch.setattr(get_global_config(), 'ENABLE_FEISHU', True)
    monkeypatch.setattr(feishu, 'bind_feishu_owner_open_id', lambda _: 'ou_1')
    monkeypatch.setattr(feishu, 'is_feishu_owner', lambda *args: True)
    monkeypatch.setattr(feishu, 'get_state', lambda _: None)
    monkeypatch.setattr(feishu, 'delete_state', lambda _: None)
    calls = []
    client = feishu.FeishuClient(app_id='app', app_secret='secret', on_message=lambda *args: calls.append(args))
    client._sender = MagicMock()
    client.sender.add_reaction.return_value = 'typing-id'
    return client, calls


def user_event(text, sender_type='user'):
    event = _event('text', {'text': text})
    event.event.sender.sender_type = sender_type
    return event


def test_receiver_marks_typing_then_done(receiver):
    client, calls = receiver
    client._handle_message(user_event('你好'))
    client.sender.add_reaction.assert_called_once_with('om_1', 'Typing')
    context = calls[0][2]
    assert context['feishu_typing_reaction_id'] == 'typing-id'
    finish_reaction(context, client.sender, True)
    assert client.sender.method_calls[-2:] == [
        ('delete_reaction', ('om_1', 'typing-id'), {}), ('add_reaction', ('om_1', 'DONE'), {})]
    before = len(client.sender.method_calls)
    finish_reaction(context, client.sender, True)
    assert len(client.sender.method_calls) == before


@pytest.mark.parametrize('text,sender_type', [('/help','user'),('/tokens','user'),('/upload','user'),('/image','user'),('你好','bot'),('你好',None)])
def test_commands_and_nonuser_do_not_react(receiver, text, sender_type):
    client, calls = receiver
    client._handle_message(user_event(text, sender_type))
    assert calls
    client.sender.add_reaction.assert_not_called()


def test_enqueue_failure_cleans_typing(receiver):
    client, _ = receiver
    def fail(*args):
        raise RuntimeError('queue full')
    client.on_message = fail
    client._handle_message(user_event('hello'))
    client.sender.delete_reaction.assert_called_once_with('om_1', 'typing-id')
    assert client.sender.add_reaction.call_count == 1


def test_typing_failure_preserves_request(receiver):
    client, calls = receiver
    client.sender.add_reaction.side_effect = OSError('offline')
    client._handle_message(user_event('hello'))
    assert calls and calls[0][0] == 'hello'


@pytest.mark.parametrize('result,raises,done', [
    ({'messages':[AIMessage(content='ok')]},False,True),
    ({'messages': [], 'completed': True, 'reply_required': False},False,True),
    (None,False,False), ({'messages':[AIMessage(content='')]},False,False),
    (None,True,False),
])
def test_loop_completes_or_cleans_original_message(receiver, monkeypatch, result, raises, done):
    import loop
    from channels.bus import EventType
    client, calls = receiver
    client._handle_message(user_event('hello'))
    context = calls[0][2]
    events = [SimpleNamespace(event_type=EventType.LARK_MESSAGE, context=context, content={'text':'hello'}),
              SimpleNamespace(event_type=EventType.TERMINAL, context={}, content={'text':'/quit'})]
    service = MagicMock()
    service.memory = None
    service.run.return_value = result
    if raises:
        service.run.side_effect = RuntimeError('model failed')
    bus = MagicMock()
    bus.poll.side_effect = events
    monkeypatch.setattr(loop, 'AgentService', lambda: service)
    monkeypatch.setattr(loop, 'get_bus', lambda: bus)
    monkeypatch.setattr(loop, 'get_output_channel', lambda _: MagicMock())
    monkeypatch.setattr(loop, 'stop_event_source', lambda: None)
    monkeypatch.setattr(loop, 'handle_command', lambda *args, **kwargs: False)
    monkeypatch.setattr(feishu, 'get_feishu_client', lambda: client)
    loop.loop_forever()
    client.sender.delete_reaction.assert_called_once_with('om_1', 'typing-id')
    assert any(call.args == ('om_1','DONE') for call in client.sender.add_reaction.call_args_list) == done


def test_sdk_reaction_requests_and_api_failure():
    sender = object.__new__(feishu.FeishuMessageSender)
    sender.client = MagicMock()
    api = sender.client.im.v1.message_reaction
    api.create.return_value = SimpleNamespace(success=lambda:True, data=SimpleNamespace(reaction_id='id'))
    api.delete.return_value = SimpleNamespace(success=lambda:True)
    assert sender.add_reaction('message', 'Typing') == 'id'
    request = api.create.call_args.args[0]
    assert request.message_id == 'message'
    assert request.request_body.reaction_type.emoji_type == 'Typing'
    assert sender.delete_reaction('message','id')
    assert api.delete.call_args.args[0].reaction_id == 'id'
    api.create.return_value = SimpleNamespace(success=lambda:False, code=999)
    assert sender.add_reaction('message','DONE') is None
    api.delete.side_effect = OSError('offline')
    assert sender.delete_reaction('message','id') is False


def test_disabled_or_non_feishu_not_eligible(receiver, monkeypatch):
    from config import get_global_config
    context = {'source':'feishu','sender_type':'user','message_id':'m'}
    assert reaction_eligible(context)
    assert not reaction_eligible(dict(context, source='terminal'))
    monkeypatch.setattr(get_global_config(), 'ENABLE_FEISHU', False)
    assert not reaction_eligible(context)
