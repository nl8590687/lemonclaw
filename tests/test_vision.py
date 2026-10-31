"""多图引用、真实 SDK 请求、命令、飞书和 checkpoint 回归。"""
import base64
import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from PIL import Image
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

import dao.db as db
from dao.attachment import AttachmentDAO
from agent.media.images import register_image, image_message, adapt_messages, REFS
from agent.media.commands import media_command
from agent.llm.reliability import ReliableChatOpenAI, LLMUnavailableError, _breakers


@pytest.fixture
def media(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(db, '_global_db_path', None)
    import channels.device.feishu as feishu
    directory = tmp_path / 'upload'
    directory.mkdir()
    monkeypatch.setattr(feishu, 'received_dir', lambda: directory)
    from config import get_global_config
    monkeypatch.setattr(get_global_config(), 'ENABLE_VISION', True)
    _breakers.clear()
    return tmp_path


def png(path, color='red'):
    Image.new('RGB', (4, 3), color).save(path, format='PNG')
    return path


def attachment(path, context=None, index=0, message_id=None):
    return register_image({'path': str(path), 'message_id': message_id}, context or {}, index)


def test_multi_image_request_copy_and_mime(media):
    first = attachment(png(media / 'misnamed.jpg'))
    second = attachment(png(media / 'b.png', 'blue'))
    message = image_message('比较', [first['attachment_id'], second['attachment_id']], {})
    adapted, has_images = adapt_messages([message], True)
    assert has_images
    blocks = adapted[0].content
    images = [b['image_url']['url'] for b in blocks if b['type'] == 'image_url']
    assert len(images) == 2 and images[0].startswith('data:image/png;base64,')
    assert base64.b64decode(images[0].split(',')[1]) == (media / 'misnamed.jpg').read_bytes()
    assert isinstance(message.content, str)
    assert 'base64' not in message.model_dump_json()
    disabled, has_images = adapt_messages([message], False)
    assert not has_images and '视觉功能关闭' in disabled[0].content


def test_scope_dedup_ttl_and_selection(media):
    context = {'source': 'feishu', 'chat_id': 'chat', 'open_id': 'owner'}
    item = attachment(png(media / 'a.png'), context, message_id='message')
    again = attachment(media / 'a.png', context, message_id='message')
    assert item['attachment_id'] == again['attachment_id']
    dao = AttachmentDAO()
    with pytest.raises(ValueError, match='当前会话'):
        dao.get(item['attachment_id'], dict(context, chat_id='other'))
    assert len(dao.for_message('message', context)) == 1
    dao.mark([item['attachment_id']], context, 'stored')
    assert dao.pending(context) == []
    assert dao.get(item['attachment_id'], context)
    with db.get_connection() as conn:
        conn.execute("UPDATE attachments SET selection_state='pending', pending_expires_at=0")
    assert dao.pending(context) == []
    assert dao.get(item['attachment_id'], context)


def test_file_changed_and_missing(media):
    path = png(media / 'a.png')
    item = attachment(path)
    message = image_message('test', [item['attachment_id']], {})
    png(path, 'blue')
    with pytest.raises(ValueError, match='已变更'):
        adapt_messages([message], True)
    path.unlink()
    with pytest.raises(FileNotFoundError):
        adapt_messages([message], True)


def test_cli_commands_and_disabled(media, monkeypatch):
    path = png(media / 'space name.png')
    text, selected, receipt = media_command(f'/image "{path}" -- 看这张图', {})
    assert text == '看这张图' and len(selected) == 1 and receipt is None
    assert selected[0]['vision_selected']
    assert media_command('/image', {})[2].startswith('用法')
    ids = selected[0]['attachment_id']
    assert '仅保存' in media_command('/upload ' + ids, {})[2]
    assert AttachmentDAO().pending({}) == []
    from config import get_global_config
    monkeypatch.setattr(get_global_config(), 'ENABLE_VISION', False)
    with pytest.raises(ValueError, match='未开启'):
        media_command('/image ' + ids, {})
    with pytest.raises(ValueError, match='仅供命令行'):
        media_command(f'/upload "{path}"', {'source': 'feishu'})


def sdk_reply(request):
    return httpx.Response(200, json={'id': 'test', 'model': 'vision', 'object': 'chat.completion',
        'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': '看到两张图'}, 'finish_reason': 'stop'}],
        'usage': {'prompt_tokens': 20, 'completion_tokens': 5, 'total_tokens': 25}})


def llm(handler, **kwargs):
    return ReliableChatOpenAI(model='vision', api_key='fake', base_url='https://vision.test/v1', streaming=False,
        max_retries=0, retry_count=1, retry_base_delay=0, retry_max_delay=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)


def test_actual_sdk_images_and_fallback_capability(media):
    item = attachment(png(media / 'a.png'))
    message = image_message('describe', [item['attachment_id']], {})
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return sdk_reply(request)
    model = llm(handler)
    assert model.invoke([message]).usage_metadata['input_tokens'] == 20
    assert requests[0]['messages'][0]['content'][-1]['type'] == 'image_url'
    assert REFS not in json.dumps(requests[0])
    _breakers.clear()
    def failed(request):
        return httpx.Response(503, json={'error': {'message': 'busy'}})
    model = llm(failed)
    model._fallback = ChatOpenAI(model='backup', api_key='backup', base_url='https://backup.test/v1', max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(LLMUnavailableError, match='支持视觉'):
        model.invoke([message])
    assert len(requests) == 1
    model.fallback_vision_enabled = True
    assert model.invoke([message]).content == '看到两张图'
    assert requests[-1]['messages'][0]['content'][-1]['type'] == 'image_url'


def test_checkpoint_and_summary_use_references(media):
    from tests.test_checkpoint import make_service
    from agent.agent import _create_agent
    from agent.context_agent import ContextAgent
    item = attachment(png(media / 'a.png'))
    payloads = []
    def handler(request):
        payloads.append(json.loads(request.content))
        return sdk_reply(request)
    model = llm(handler)
    first = make_service()
    first.llm = model
    first.agent = _create_agent(model, [], 'test', first.checkpointer)
    try:
        result = first.run('看看', {}, attachments=[dict(item, vision_selected=True)])
        assert result['messages'][-1].content == '看到两张图'
        stored = first._current_messages()
        assert any(m.additional_kwargs.get(REFS) for m in stored)
        assert all('data:image' not in m.model_dump_json() for m in stored)
        with patch('agent.context_agent.create_openai_llm', return_value=model):
            assert ContextAgent().run(stored) == '看到两张图'
        assert any(isinstance(m.get('content'), list) for m in payloads[-1]['messages'])
    finally:
        first.close()
    second = make_service()
    try:
        assert adapt_messages(second._current_messages(), True)[1]
    finally:
        second.close()


def test_invalid_image_and_count_limit(media):
    broken = media / 'bad.png'
    broken.write_text('not an image')
    with pytest.raises(ValueError, match='图片损坏'):
        attachment(broken)
    items = [attachment(png(media / f'{i}.png')) for i in range(9)]
    with pytest.raises(ValueError, match='1 至 8'):
        image_message('test', [item['attachment_id'] for item in items], {})


def test_workflow_explicit_image_selection(media):
    from agent.workflow.nodes import make_node
    item = attachment(png(media / 'a.png'))
    model = MagicMock()
    model.invoke.return_value.content = 'done'
    node = make_node('llm', {'prompt': 'describe', 'image_ids_field': 'images'}, model, {}, None)
    assert node({'images': [item['attachment_id']]}, {}) == {'output': 'done'}
    assert model.invoke.call_args.args[0][0].additional_kwargs[REFS]
    manager = MagicMock()
    node = make_node('subagent', {'image_ids': [item['attachment_id']], 'task': 'describe'}, model, {}, manager)
    node({}, {})
    assert manager.run_subagent_inline.call_args.args[2]['vision_image_ids'] == [item['attachment_id']]


def test_feishu_selection_and_plaintext_pending(media, monkeypatch):
    import channels.device.feishu as feishu
    from tests.test_feishu_file_receive import _event
    store = {}
    monkeypatch.setattr(feishu, 'get_state', lambda key: store.get(key))
    monkeypatch.setattr(feishu, 'set_state', lambda key, value: store.__setitem__(key, value))
    monkeypatch.setattr(feishu, 'delete_state', lambda key: store.pop(key, None))
    monkeypatch.setattr(feishu, 'bind_feishu_owner_open_id', lambda _: 'ou_1')
    monkeypatch.setattr(feishu, 'is_feishu_owner', lambda *args: True)
    path = png(media / 'source.png')
    data = path.read_bytes()
    sender = MagicMock()
    sender.download_message_resource.return_value = (data, 'photo.png', None)
    received = []
    client = feishu.FeishuClient(app_id='app', app_secret='secret', on_message=lambda *args: received.append(args))
    client._sender = sender
    client._handle_message(_event('image', {'image_key': 'key'}, message_id='image-1'))
    assert received == []
    context = {'source': 'feishu', 'chat_id': 'oc_1', 'open_id': 'ou_1'}
    first = AttachmentDAO().pending(context)[0]
    assert first['attachment_id'] in sender.send_text.call_args.args[1]
    client._handle_message(_event('text', {'text': '普通文字'}, message_id='text-1'))
    assert not received[-1][2]['attachments'][0].get('vision_selected')
    quote = _event('text', {'text': '看这张图'}, message_id='text-2')
    quote.event.message.parent_id = 'image-1'
    client._handle_message(quote)
    assert received[-1][2]['attachments'][0]['vision_selected']
    assert received[-1][2]['attachments'][0]['attachment_id'] == first['attachment_id']
    client._handle_message(_event('post', {'content': [[{'tag': 'text', 'text': '看图'}, {'tag': 'img', 'image_key': 'key2'}]]}, message_id='post-1'))
    assert received[-1][2]['attachments'][0]['vision_selected']
    # 回执失败不能吞掉有效的富文本输入。
    sender.send_text.side_effect = OSError('offline')
    before = len(received)
    client._handle_message(_event('post', {'content': [[{'tag': 'text', 'text': '看图'}, {'tag': 'img', 'image_key': 'key3'}]]}, message_id='post-2'))
    assert len(received) == before + 1
    media_command('/upload', context)
    assert AttachmentDAO().pending(context) == []
    assert feishu.load_pending_attachments('ou_1', 'oc_1') == []


def test_quote_fetch_checks_chat_and_downloads_images(media):
    import channels.device.feishu as feishu
    sender = MagicMock()
    client = feishu.FeishuClient(app_id='app', app_secret='secret')
    client._sender = sender
    context = {'source': 'feishu', 'chat_id': 'chat', 'open_id': 'owner'}
    target = SimpleNamespace(message_id='quoted', chat_id='other', msg_type='image',
                             body=SimpleNamespace(content=json.dumps({'image_key': 'key'})))
    sender.client.im.v1.message.get.return_value = SimpleNamespace(success=lambda: True, data=SimpleNamespace(items=[target]))
    with pytest.raises(ValueError, match='当前聊天'):
        client._quoted_images('quoted', context)
    sender.download_message_resource.assert_not_called()
    target.chat_id = 'chat'
    path = png(media / 'quoted.png')
    sender.download_message_resource.return_value = (path.read_bytes(), 'quoted.png', None)
    images = client._quoted_images('quoted', context)
    assert images[0]['attachment_id']
    sender.download_message_resource.assert_called_once_with('quoted', 'key', 'image')
    assert client._quoted_images('quoted', context)[0]['attachment_id'] == images[0]['attachment_id']


def test_loop_routes_image_and_upload_without_unknown_command(media, monkeypatch):
    import loop
    from channels.bus import EventType
    item = attachment(png(media / 'loop.png'))
    def event(text):
        return SimpleNamespace(event_type=EventType.TERMINAL, context={}, content={'text': text})
    bus = MagicMock()
    bus.poll.side_effect = [event(f'/image {item["attachment_id"]} -- 看图'),
                            event(f'/upload {item["attachment_id"]}'), event('/quit')]
    service = MagicMock()
    service.memory = None
    out = MagicMock()
    monkeypatch.setattr(loop, 'AgentService', lambda: service)
    monkeypatch.setattr(loop, 'get_bus', lambda: bus)
    monkeypatch.setattr(loop, 'get_output_channel', lambda _: out)
    monkeypatch.setattr(loop, 'stop_event_source', lambda: None)
    monkeypatch.setattr(loop, 'handle_command', lambda *args, **kwargs: False)
    loop.loop_forever()
    service.run.assert_called_once()
    assert service.run.call_args.args[0] == '看图'
    assert service.run.call_args.kwargs['attachments'][0]['vision_selected']
    assert '仅保存' in out.write_message.call_args.args[0]


def test_size_budget_and_disabled_missing_reference(media, monkeypatch):
    import agent.media.images as images
    path = png(media / 'budget.png')
    item = attachment(path)
    message = image_message('test', [item['attachment_id']], {})
    monkeypatch.setattr(images, 'MAX_TOTAL_BYTES', 1)
    with pytest.raises(ValueError, match='总大小'):
        image_message('test', [item['attachment_id']], {})
    with pytest.raises(ValueError, match='请求大小'):
        adapt_messages([message], True)
    path.unlink()
    assert '视觉功能关闭' in adapt_messages([message], False)[0][0].content


@pytest.mark.parametrize('source', ['feishu', 'webhook', 'cron'])
def test_remote_input_cannot_select_local_path(media, source):
    path = png(media / 'local.png')
    with pytest.raises(ValueError, match='仅供命令行'):
        media_command(f'/image "{path}" -- 查看', {'source': source})


def test_shared_legacy_history_cannot_send_other_origin_images(media):
    from tests.test_checkpoint import make_service
    item = attachment(png(media / 'origin.png'))
    service = make_service()
    try:
        service.run('看图', {}, attachments=[dict(item, vision_selected=True)])
        with pytest.raises(ValueError, match='其他来源'):
            service.run('再看看', {'source': 'feishu', 'chat_id': 'other', 'open_id': 'owner'})
    finally:
        service.close()


def test_quote_fetch_failure_keeps_regular_text_processing(media, monkeypatch):
    import channels.device.feishu as feishu
    from tests.test_feishu_file_receive import _event
    monkeypatch.setattr(feishu, 'bind_feishu_owner_open_id', lambda _: 'ou_1')
    monkeypatch.setattr(feishu, 'is_feishu_owner', lambda *args: True)
    monkeypatch.setattr(feishu, 'get_state', lambda _: None)
    monkeypatch.setattr(feishu, 'delete_state', lambda _: None)
    received = []
    client = feishu.FeishuClient(app_id='app', app_secret='secret', on_message=lambda *args: received.append(args))
    client._sender = MagicMock()
    client._sender.client.im.v1.message.get.side_effect = OSError('offline')
    event = _event('text', {'text': '继续之前的讨论'})
    event.event.message.parent_id = 'unavailable'
    client._handle_message(event)
    assert received and received[0][0].startswith('继续之前的讨论')
    assert '未附加' in received[0][0]
    assert not any(item.get('vision_selected') for item in received[0][2]['attachments'])
