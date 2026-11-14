"""Final Markdown cards, event provenance and bounded multi-card delivery."""
import json
from unittest.mock import MagicMock, patch

import pytest

from channels.bus.enum import EventType
from channels.device.feishu import FeishuMessageSender, markdown_reply_cards, _REPLY_CARD_BYTES
from channels.out.feishu import FeishuOutputChannel


@pytest.mark.parametrize('event', list(EventType))
def test_event_type_is_first_visible_content(event):
    text = '# 标题\n\n**强调** [链接](https://example.com)\n\n```python\nprint("你好")\n```'
    card, = markdown_reply_cards(text, event.value)
    assert card['schema'] == '2.0'
    assert card['header']['title'] == {'tag': 'plain_text', 'content': f'事件类型：{event.value}'}
    assert card['body']['elements'] == [{'tag': 'markdown', 'content': text}]
    assert 'behaviors' not in json.dumps(card)


@pytest.mark.parametrize('event', [None, '', '   ', {}, 123])
def test_missing_event_type_is_unknown(event):
    card, = markdown_reply_cards('回答', event)
    assert card['header']['title']['content'] == '事件类型：未知'


def test_long_unicode_and_code_blocks_preserve_all_content():
    text = '```python\n' + ('print("你好\\n😀")\n' * 8000) + '```'
    cards = list(markdown_reply_cards(text, 'scheduled'))
    assert len(cards) > 2
    original = []
    for index, card in enumerate(cards):
        payload = json.dumps(card, ensure_ascii=False)
        assert len(json.dumps({'content': payload}, ensure_ascii=False).encode()) <= _REPLY_CARD_BYTES
        content = card['body']['elements'][0]['content']
        assert content.startswith('```python\n') and content.endswith('```')
        if index:
            content = content[len('```python\n'):]
        if index < len(cards) - 1:
            content = content[:-len('\n```')]
        original.append(content)
    assert ''.join(original) == text


def test_long_single_line_is_not_lost():
    text = '汉字😀"\\' * 20000
    cards = list(markdown_reply_cards(text, 'webhook'))
    assert ''.join(c['body']['elements'][0]['content'] for c in cards) == text
    for card in cards:
        payload = json.dumps(card, ensure_ascii=False)
        assert len(json.dumps({'content': payload}, ensure_ascii=False).encode()) <= _REPLY_CARD_BYTES


def test_sender_uses_existing_interactive_api():
    sender = object.__new__(FeishuMessageSender)
    sender.client = MagicMock()
    sender.client.im.v1.message.create.return_value.success.return_value = True
    assert sender.send_markdown_card('ou_target', '**最终答复**', 'lark_message')
    request = sender.client.im.v1.message.create.call_args.args[0]
    assert request.receive_id_type == 'open_id'
    assert request.request_body.receive_id == 'ou_target'
    assert request.request_body.msg_type == 'interactive'
    assert json.loads(request.request_body.content)['header']['title']['content'] == '事件类型：lark_message'


def test_partial_delivery_failure_stops_without_resending():
    sender = object.__new__(FeishuMessageSender)
    sender._send = MagicMock(side_effect=[True, False])
    assert not sender.send_markdown_card('ou_target', '字' * 50000, 'custom')
    assert sender._send.call_count == 2


def test_output_channel_keeps_owner_routing_and_hides_context():
    with (patch('channels.out.feishu.get_feishu_client', return_value=None),
          patch('channels.out.feishu.FeishuMessageSender') as sender_cls,
          patch('channels.out.feishu.get_feishu_owner_open_id', return_value='ou_owner')):
        channel = FeishuOutputChannel('ou_other')
        assert channel.write_message('正文', {'_event_type': 'scheduled', 'open_id': 'ou_incoming', 'secret': 'private'})
        sender_cls.return_value.send_markdown_card.assert_called_once_with('ou_owner', '正文', 'scheduled')
        sender_cls.return_value.send_markdown.assert_not_called()
        assert channel.write_message('', {}) is False
