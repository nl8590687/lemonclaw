"""API 缓存用量、本轮与会话累计统计及终端输出。"""

from io import StringIO
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from rich.console import Console

from agent.agent import AgentService
from agent.callback import StreamingCallback
from channels.out.stdout import TerminalOutputChannel


def response(input_tokens, cached=None, raw=None, detail_key='cache_read'):
    usage = {'input_tokens': input_tokens, 'output_tokens': 10, 'total_tokens': input_tokens + 10}
    if cached is not None:
        usage['input_token_details'] = {detail_key: cached}
    return LLMResult(generations=[[ChatGeneration(message=AIMessage(
        content='ok', usage_metadata=usage, response_metadata={'token_usage': raw or {}}))]])


@pytest.mark.parametrize('cached,key,raw,expected', [
    (80, 'cache_read', None, 80), (0, 'cache_read', None, 0),
    (70, 'priority_cache_read', None, 70), (60, 'flex_cache_read', None, 60),
    (None, 'cache_read', {'prompt_cache_hit_tokens': 50}, 50),
    (None, 'cache_read', None, 0),
])
def test_cache_usage(cached, key, raw, expected):
    callback = StreamingCallback()
    callback.on_llm_end(response(100, cached, raw, key))
    assert callback.tokens['cached_prompt_tokens'] == expected
    assert callback.tokens['uncached_prompt_tokens'] == 100 - expected
    assert callback.tokens['prompt_tokens'] == 100
    assert callback.tokens['total_tokens'] == 110
    assert callback.tokens['memory_tokens'] == 110


def test_react_and_session_accumulation_and_print():
    callback = StreamingCallback()
    callback.on_llm_end(response(100, 80))
    callback.on_llm_end(response(200, 150))
    assert callback.tokens['cached_prompt_tokens'] == 230
    assert callback.tokens['uncached_prompt_tokens'] == 70
    service = object.__new__(AgentService)
    service.stats = {
        'context_tokens': {'total_prompt_tokens': 0, 'total_cached_prompt_tokens': 0,
                           'total_uncached_prompt_tokens': 0, 'total_completion_tokens': 0,
                           'context_total_tokens': 0},
        'context_messages': {},
    }
    service.get_memory_stats = MagicMock(return_value=dict.fromkeys(
        ['human_count', 'ai_count', 'tool_count', 'system_count', 'message_count'], 0))
    service._update_stats(callback)
    service._update_stats(callback)
    assert service.stats['context_tokens']['total_cached_prompt_tokens'] == 460
    assert service.stats['context_tokens']['total_uncached_prompt_tokens'] == 140
    output = StringIO()
    channel = object.__new__(TerminalOutputChannel)
    channel.console = Console(file=output, width=240, color_system=None)
    channel._display_token_stats({'tokens': callback.tokens,
                                 'context_tokens': service.stats['context_tokens']})
    text = output.getvalue()
    assert '缓存 230 / 未缓存 70' in text
    assert '缓存 460 / 未缓存 140' in text


def test_print_accepts_older_token_context():
    output = StringIO()
    channel = object.__new__(TerminalOutputChannel)
    channel.console = Console(file=output, width=240, color_system=None)
    channel._display_token_stats({'tokens': {'prompt_tokens': 100}})
    assert '缓存 0 / 未缓存 100' in output.getvalue()
