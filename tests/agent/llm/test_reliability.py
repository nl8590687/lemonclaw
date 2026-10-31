"""通过 SDK 的假 HTTP provider 验证重试、fallback 与工具调用。"""
import json
import threading
import time

import httpx
import openai
import pytest
from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from agent.llm.reliability import ReliableChatOpenAI, CircuitBreaker, LLMUnavailableError, _breakers, retry_after


@pytest.fixture(autouse=True)
def clear_breakers():
    _breakers.clear()


def model(handler, **kwargs):
    return ReliableChatOpenAI(model='primary', api_key='test-key', base_url='https://primary.test/v1',
        http_client=httpx.Client(transport=httpx.MockTransport(handler)), max_retries=0,
        retry_count=2, retry_base_delay=0, retry_max_delay=0, streaming=True, stream_usage=True, **kwargs)


def answer(request, message=None):
    payload = json.loads(request.content)
    message = message or {'content': 'ok'}
    if payload.get('stream'):
        delta = dict(message)
        if 'tool_calls' in delta:
            delta['tool_calls'] = [dict(c, index=i) for i, c in enumerate(delta['tool_calls'])]
        chunk = {'id': 'fake', 'object': 'chat.completion.chunk', 'model': payload['model'],
                 'choices': [{'index': 0, 'delta': dict(role='assistant', **delta),
                              'finish_reason': 'tool_calls' if 'tool_calls' in delta else 'stop'}]}
        return httpx.Response(200, text='data: ' + json.dumps(chunk) + '\n\ndata: [DONE]\n\n',
                              headers={'content-type': 'text/event-stream'})
    return httpx.Response(200, json={'id': 'fake', 'object': 'chat.completion', 'model': payload['model'],
        'choices': [{'index': 0, 'message': dict(role='assistant', **message), 'finish_reason': 'stop'}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12}})


def test_rate_limit_then_success(caplog):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(429, headers={'retry-after': '0'}, json={'error': {'message': 'limited'}}) if len(requests) == 1 else answer(request)
    llm = model(handler)
    assert llm.invoke('hello').content == 'ok'
    assert len(requests) == 2
    assert 'status=429' in caplog.text
    assert 'test-key' not in caplog.text


@pytest.mark.parametrize('status', [400, 401, 403, 404, 422])
def test_permanent_error_never_retries_or_falls_back(status):
    count = []
    def handler(request):
        count.append(1)
        return httpx.Response(status, json={'error': {'message': 'bad request'}})
    llm = model(handler)
    llm._fallback = ChatOpenAI(model='backup', api_key='backup', base_url='https://backup.test/v1')
    with pytest.raises(openai.APIStatusError):
        llm.invoke('hello')
    assert count == [1]


def test_fallback_with_actual_agent_tool_call():
    calls, payloads = [], []
    def primary(request):
        return httpx.Response(503, json={'error': {'message': 'busy'}})
    def backup(request):
        payloads.append(json.loads(request.content))
        if len(payloads) == 1:
            return answer(request, {'tool_calls': [{'id': 'call_1', 'type': 'function', 'function': {'name': 'effect', 'arguments': '{}'}}]})
        return answer(request)
    @tool
    def effect() -> str:
        """记录一次工具执行。"""
        calls.append(1)
        return 'done'
    llm = model(primary, breaker_threshold=1)
    llm._fallback = ChatOpenAI(model='backup', api_key='backup', base_url='https://backup.test/v1',
        http_client=httpx.Client(transport=httpx.MockTransport(backup)), max_retries=0, streaming=True)
    result = create_agent(llm, tools=[effect]).invoke({'messages': [('user', 'execute')]})
    assert result['messages'][-1].content == 'ok'
    assert calls == [1]
    assert len(payloads) == 2
    assert all(p['model'] == 'backup' and p['tools'][0]['function']['name'] == 'effect' for p in payloads)


def test_total_deadline_releases_caller():
    release = threading.Event()
    def handler(request):
        release.wait(3)
        return answer(request)
    llm = model(handler, total_timeout=.05)
    start = time.monotonic()
    try:
        with pytest.raises(LLMUnavailableError, match='总耗时'):
            llm.invoke('hello')
        assert time.monotonic() - start < 1
    finally:
        release.set()


def test_retry_after_and_breaker_states(monkeypatch):
    error = openai.RateLimitError('limited', response=httpx.Response(429, headers={'retry-after': '2'}, request=httpx.Request('POST', 'https://fake.test')), body=None)
    assert retry_after(error) == 2
    breaker = CircuitBreaker()
    assert breaker.acquire(10)
    breaker.result(True, 1)
    assert not breaker.acquire(10)
    breaker.opened -= 11
    assert breaker.acquire(10)
    assert not breaker.acquire(10)
    breaker.result(False, 1)
    assert breaker.acquire(10)


def test_nonstream_preserves_usage_and_closes_probe():
    llm = model(answer)
    llm.streaming = False
    result = llm.invoke('hello')
    assert result.content == 'ok'
    assert result.usage_metadata['input_tokens'] == 10


def test_read_timeout_then_success():
    count = []
    def handler(request):
        count.append(1)
        if len(count) == 1:
            raise httpx.ReadTimeout('timeout', request=request)
        return answer(request)
    assert model(handler).invoke('hello').content == 'ok'
    assert len(count) == 2


def test_partial_stream_is_not_replayed():
    requests = []
    class InterruptedStream(httpx.SyncByteStream):
        def __iter__(self):
            chunk = {'id': 'partial', 'object': 'chat.completion.chunk', 'model': 'primary',
                     'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': 'partial'}, 'finish_reason': None}]}
            yield ('data: ' + json.dumps(chunk) + '\n\n').encode()
            raise httpx.ReadError('disconnected')
    def handler(request):
        requests.append(1)
        return httpx.Response(200, stream=InterruptedStream(), headers={'content-type': 'text/event-stream'})
    llm = model(handler)
    llm._fallback = ChatOpenAI(model='backup', api_key='backup', base_url='https://backup.test/v1')
    iterator = llm.stream('hello')
    assert next(iterator).content == 'partial'
    with pytest.raises(httpx.ReadError):
        list(iterator)
    assert requests == [1]


def test_retry_after_waits_before_next_request():
    times = []
    def handler(request):
        times.append(time.monotonic())
        if len(times) == 1:
            return httpx.Response(429, headers={'retry-after': '.05'}, json={'error': {'message': 'limited'}})
        return answer(request)
    assert model(handler).invoke('hello').content == 'ok'
    assert times[1] - times[0] >= .045


def test_async_invocation():
    import asyncio
    llm = model(answer)
    assert asyncio.run(llm.ainvoke('hello')).content == 'ok'


def test_timeout_checkpoint_survives_restart(tmp_path, monkeypatch):
    import dao.db as db
    from agent.agent import _create_agent
    from tests.test_checkpoint import make_service
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(db, '_global_db_path', None)
    release = threading.Event()
    def handler(request):
        release.wait(3)
        return answer(request)
    llm = model(handler, total_timeout=.05)
    first = make_service()
    first.llm = llm
    first.agent = _create_agent(llm, [], 'test', first.checkpointer)
    try:
        with pytest.raises(LLMUnavailableError):
            first.run('保留这条请求', {}, session_key='timeout')
        assert first._has_interrupted_turn()
    finally:
        release.set()
        first.close()
    second = make_service()
    second.session_id = 'timeout'
    try:
        assert second._has_interrupted_turn()
        assert second._current_messages()[0].content == '保留这条请求'
    finally:
        second.close()


def test_provider_open_skip_then_half_open_recovery():
    calls = []
    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503, json={'error': {'message': 'busy'}})
        return answer(request)
    llm = model(handler, breaker_threshold=1)
    with pytest.raises(LLMUnavailableError):
        llm.invoke('hello')
    with pytest.raises(LLMUnavailableError):
        llm.invoke('hello')
    assert len(calls) == 1
    breaker = next(iter(_breakers.values()))
    breaker.opened -= 31
    assert llm.invoke('hello').content == 'ok'
    assert breaker.opened is None and not breaker.probe
    assert len(calls) == 2


@pytest.mark.parametrize("with_fallback", [False, True])
def test_ten_retries_are_bounded_across_primary_and_fallback(with_fallback):
    calls = []
    def failed(request):
        calls.append(request.url.host)
        return httpx.Response(503, json={'error': {'message': 'busy'}})
    llm = model(failed, breaker_threshold=100)
    llm.retry_count = 10
    if with_fallback:
        llm._fallback = ChatOpenAI(model='backup', api_key='backup', base_url='https://backup.test/v1',
            http_client=httpx.Client(transport=httpx.MockTransport(failed)), max_retries=0, streaming=True)
    with pytest.raises(LLMUnavailableError, match='API 接口异常'):
        llm.invoke('hello')
    assert len(calls) == 11  # 首次请求 + 最多十次重试，包含备用模型。
    assert calls[-1] == ('backup.test' if with_fallback else 'primary.test')
