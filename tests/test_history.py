"""普通续聊前缀稳定、超长检查、阈值摘要及持久状态集成测试。"""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage

from agent.history import protected_boundary, trim_oversized
from tests.test_checkpoint import make_service, database  # noqa: F401


def conversation(payload='结果'):
    return [HumanMessage(content='旧问题', id='h1'),
            AIMessage(content='', id='a1', tool_calls=[{
                'id': 'call1', 'name': 'test_tool', 'args': {'body': payload}, 'type': 'tool_call'}]),
            ToolMessage(content=payload, id='t1', tool_call_id='call1'),
            AIMessage(content='完成', id='a2'),
            HumanMessage(content='最近问题', id='h2'), AIMessage(content='最近答复', id='a3')]


def test_boundary_preserves_parallel_tool_group():
    messages = [HumanMessage(content='q'), AIMessage(content='', tool_calls=[
        {'id': 'x', 'name': 'test_tool', 'args': {}, 'type': 'tool_call'},
        {'id': 'y', 'name': 'test_tool', 'args': {}, 'type': 'tool_call'}]),
        ToolMessage(content='x', tool_call_id='x'), ToolMessage(content='y', tool_call_id='y'),
        AIMessage(content='done')]
    assert protected_boundary(messages, 2) == 1
    assert protected_boundary(messages, 0) == 5
    assert protected_boundary(messages, 100) == 0


def test_only_oversized_old_content_changes_once_without_mutation():
    messages = conversation('x' * 20000)
    before = [msg.model_dump() for msg in messages]
    result = trim_oversized(messages, protected_boundary(messages, 2), 12000)
    assert len(result[2].content) <= 12000
    assert len(result[1].tool_calls[0]['args']['body']) <= 12000
    assert [msg.model_dump() for msg in messages] == before
    assert result[1].tool_calls[0]['id'] == 'call1'
    assert trim_oversized(result, 4, 12000) == result
    assert trim_oversized(messages, 0, 12000) == messages


def test_normal_results_and_multimodal_are_not_age_trimmed():
    messages = conversation('x' * 1000)
    assert trim_oversized(messages, 4, 12000) == messages
    messages[2] = ToolMessage(content=[{'type': 'image_url', 'image_url': {'url': 'data:abc'}}], tool_call_id='call1')
    assert trim_oversized(messages, 4, 12000) == messages
    messages[2] = ToolMessage(content=[{'type': 'text', 'text': 'x' * 20000},
                                      {'type': 'image_url', 'image_url': {'url': 'data:abc'}}],
                              tool_call_id='call1')
    result = trim_oversized(messages, 4, 12000)
    assert len(result[2].content[0]['text']) <= 12000
    assert result[2].content[1] == messages[2].content[1]


def set_history(service, messages):
    service.agent.update_state(service._thread_config(), {'messages': messages}, as_node='model')


def test_below_threshold_no_summary_or_checkpoint_write(database):
    service = make_service()
    try:
        set_history(service, conversation('x' * 1000))
        original = service._current_messages()
        with patch('agent.agent.ContextAgent') as summary, patch.object(service.agent, 'update_state') as update:
            service.trim_msg_history()
        summary.assert_not_called()
        update.assert_not_called()
        assert service._current_messages() == original
    finally:
        service.close()


def test_threshold_summary_order_recent_preserved_restart(database):
    service = make_service()
    old = conversation('x' * 1000)
    service.model_context_length = 2000
    try:
        set_history(service, old)
        service.stats['context_messages']['memory_tokens'] = 1800
        with patch('agent.agent.ContextAgent') as summary:
            summary.return_value.run.return_value = '目标：保留数据库。待办：验证。'
            service.trim_msg_history()
            summary.return_value.run.assert_called_once()
        messages = service._current_messages()
        assert messages[0].additional_kwargs['lemonclaw_summary']
        assert messages[1:] == old[-2:]
        assert service.stats["context_messages"]["memory_tokens"] == 1800
        assert not service._has_interrupted_turn()
    finally:
        service.close()
    restarted = make_service()
    try:
        assert restarted._current_messages() == messages
        with patch('agent.agent.ContextAgent') as summary:
            restarted.trim_msg_history()
        summary.assert_not_called()
    finally:
        restarted.close()


@pytest.mark.parametrize('outcome', ['', RuntimeError('summary failed')])
def test_summary_failure_does_not_delete_history(database, outcome):
    service = make_service()
    try:
        set_history(service, conversation('x' * 1000))
        service.stats['context_messages']['memory_tokens'] = 9000
        original = service._current_messages()
        with patch('agent.agent.ContextAgent') as summary:
            if isinstance(outcome, Exception):
                summary.return_value.run.side_effect = outcome
            else:
                summary.return_value.run.return_value = outcome
            service.trim_msg_history()
        assert service._current_messages() == original
        service.default_out_chan.write_system_error.assert_called_once()
    finally:
        service.close()


def test_recent_oversized_results_remain_intact(database):
    service = make_service()
    try:
        messages = conversation('x' * 20000)
        service.min_full_messages = 100
        set_history(service, messages)
        with patch('agent.agent.ContextAgent') as summary:
            service.trim_msg_history()
        summary.assert_not_called()
        assert service._current_messages() == messages
    finally:
        service.close()


def test_memory_is_real_tool_result_and_not_in_system(database):
    from agent.memory.middleware import MemoryMiddleware
    from agent.tools.memory_tool import RecallMemoryTool
    memory = MagicMock()
    memory.search.return_value = [(MagicMock(id=1, chunk_type='fact', importance=5,
                                              title='记忆', content='仅在工具结果中可见'), 1.0)]
    recall = RecallMemoryTool(memory)
    service = make_service([AIMessage(content='', tool_calls=[{
        'id': 'recall1', 'name': 'recall_memory', 'args': {'query': '记忆'}, 'type': 'tool_call'}]),
        AIMessage(content='已回忆')], [recall])
    try:
        result = service.run('回忆记忆', {})
        outputs = [msg for msg in result['messages'] if isinstance(msg, ToolMessage)]
        assert len(outputs) == 1 and outputs[0].tool_call_id == 'recall1'
        assert '仅在工具结果中可见' in outputs[0].content
        request = MagicMock(messages=[HumanMessage(content='记忆')])
        MemoryMiddleware(memory, 'BASE').wrap_model_call(request, lambda value: value)
        assert request.override.call_args.kwargs['system_message'] == SystemMessage(content='BASE')
        memory.build_context.assert_not_called()
    finally:
        service.close()


def test_end_of_turn_oversized_check_is_idempotent(database):
    service = make_service()
    try:
        service.model_context_length = 100000
        original = conversation('x' * 20000)
        set_history(service, original)
        with patch('agent.agent.ContextAgent') as summary:
            service.trim_msg_history()
        summary.assert_not_called()
        messages = service._current_messages()
        assert len(messages[2].content) <= service.tool_max_chars
        assert service.stats["context_messages"]["memory_tokens"] == 0
        assert messages[-2:] == original[-2:]
        assert not service._has_interrupted_turn()
        with patch.object(service.agent, 'update_state') as update:
            service.trim_msg_history()
        update.assert_not_called()
    finally:
        service.close()


def test_summary_threshold_uses_api_usage(database):
    service = make_service()
    try:
        set_history(service, conversation('x' * 5000))
        service.model_context_length = 1000
        service.stats['context_messages']['memory_tokens'] = 100
        with patch('agent.agent.ContextAgent') as summary:
            service.trim_msg_history()
        summary.assert_not_called()
        assert service.stats['context_messages']['memory_tokens'] == 100
        assert service._current_messages() == conversation('x' * 5000)
    finally:
        service.close()
