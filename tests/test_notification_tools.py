"""通知节制、主图直接结束、checkpoint 配对和状态表情回归。"""
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from agent.tools.notification_tool import (notify_progress, finish_silently,
                                          begin_notifications, reset_notifications)
from channels.device.feishu import turn_completed
from tests.test_checkpoint import make_service, database  # noqa: F401


def call(name, args, identifier='finish'):
    return AIMessage(content='', tool_calls=[{'name': name, 'args': args, 'id': identifier}])


def test_background_silent_stops_model_and_can_continue(database):
    service = make_service(responses=[
        call('finish_silently', {'reason': '已检查，没有需要通知的变化', 'outcome': 'no_action_needed'}),
        AIMessage(content='下一轮正常回复')], tools=[notify_progress, finish_silently])
    try:
        result = service.run('状态事件', {'_event_type': 'webhook'})
        assert result['completed'] and not result['reply_required']
        assert isinstance(result['messages'][-1], ToolMessage)
        assert not service.agent.get_state(service._thread_config()).next
        assert not service._has_interrupted_turn(service.agent.get_state(service._thread_config()))
        service.default_out_chan.write_message.assert_not_called()
        service.default_out_chan.write_system_error.assert_not_called()
        assert turn_completed(result)
        assert service.run('你好', {})['messages'][-1].content == '下一轮正常回复'
    finally:
        service.close()


@pytest.mark.parametrize('context', [{}, {'_event_type': 'lark_message'}, {'_event_type': 'scheduled'}])
def test_user_and_scheduled_silence_denied(database, context):
    service = make_service(responses=[call('finish_silently', {
        'reason': '不想回复', 'outcome': 'no_action_needed'}), AIMessage(content='正常交付报告')], tools=[finish_silently])
    try:
        result = service.run('请给我报告', context)
        assert result['reply_required']
        assert service.default_out_chan.write_message.call_args.args[0] == '正常交付报告'
    finally:
        service.close()


def test_progress_then_delivery_and_silent_completion(database):
    service = make_service(responses=[
        call('notify_progress', {'message': '关键数据已核实'}, 'p'),
        call('notify_progress', {'message': '报告已完整交付：结果如下。', 'kind': 'delivered_result'}, 'd'),
        call('finish_silently', {'reason': '完整报告已发送，避免重复', 'outcome': 'already_delivered'})
    ], tools=[notify_progress, finish_silently])
    try:
        result = service.run('请调查', {'source': 'feishu'})
        assert result['completed'] and not result['reply_required']
        assert service.default_out_chan.write_message.call_count == 2
        assert turn_completed(result)
        assert len([m for m in result['messages'] if isinstance(m, ToolMessage)]) == 3
    finally:
        service.close()


def test_limits_failures_and_no_cross_turn_state():
    output = MagicMock()
    state, token = begin_notifications(output, {})
    try:
        assert '未发送' in notify_progress.invoke({'message': ' '})
        for text in ['a', 'a', 'b', 'c', 'd']:
            notify_progress.invoke({'message': text})
        assert output.write_message.call_count == 3
        assert not state.silent
    finally:
        reset_notifications(token)
    assert '不可用' in notify_progress.invoke({'message': '其他执行'})
    output.write_message.side_effect = OSError('发送失败')
    state, token = begin_notifications(output, {})
    try:
        with pytest.raises(OSError):
            notify_progress.invoke({'message': '结果', 'kind': 'delivered_result'})
        assert not state.delivered
    finally:
        reset_notifications(token)


def test_parallel_finish_and_progress_cannot_silence(database):
    parallel = AIMessage(content='', tool_calls=[
        {'name': 'finish_silently', 'args': {'reason': '无变化', 'outcome': 'no_action_needed'}, 'id': 'f'},
        {'name': 'notify_progress', 'args': {'message': '检查已完成'}, 'id': 'p'}])
    service = make_service(responses=[parallel, AIMessage(content='正常回复')],
                           tools=[notify_progress, finish_silently])
    try:
        result = service.run('事件', {'_event_type': 'webhook'})
        assert result['reply_required'] and result['completed']
        assert any(isinstance(m, ToolMessage) and '必须单独调用' in str(m.content)
                   for m in result['messages'])
        assert service.default_out_chan.write_message.call_args.args[0] == '正常回复'
    finally:
        service.close()


def test_progress_is_not_delivery_and_delivery_does_not_leak(database):
    service = make_service(responses=[
        call('notify_progress', {'message': '核实中'}, 'p'),
        call('finish_silently', {'reason': '只有进度', 'outcome': 'already_delivered'}, 'f'),
        AIMessage(content='完整结果'),
        call('finish_silently', {'reason': '前一轮已回复', 'outcome': 'already_delivered'}, 'f2'),
        AIMessage(content='本轮结果')], tools=[notify_progress, finish_silently])
    try:
        assert service.run('调查', {})['reply_required']
        assert service.run('新任务', {})['messages'][-1].content == '本轮结果'
    finally:
        service.close()


def test_failed_channel_does_not_allow_silent_delivery():
    from channels.out.fanout import FanoutOutputChannel
    good, bad = MagicMock(), MagicMock()
    good.write_message.return_value = None
    bad.write_message.return_value = False
    output = FanoutOutputChannel([good, bad])
    state, token = begin_notifications(output, {})
    try:
        assert '发送失败' in notify_progress.invoke({'message': '结果', 'kind': 'delivered_result'})
        assert not state.delivered and not state.sent
    finally:
        reset_notifications(token)


def test_completion_check_preserves_react_round_budget(database):
    responses = [call('notify_progress', {'message': str(i)}, str(i)) for i in range(7)]
    service = make_service(responses=[*responses, AIMessage(content='完成')], tools=[notify_progress])
    try:
        assert service.run('多步任务', {})['messages'][-1].content == '完成'
    finally:
        service.close()
