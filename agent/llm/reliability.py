"""OpenAI-compatible 调用的重试、流式期限与 provider 熔断。"""

import asyncio
import contextvars
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import logging
import queue
import random
import threading
import time
from urllib.parse import urlsplit

import httpx
from langchain_openai import ChatOpenAI
from pydantic import Field, PrivateAttr

logger = logging.getLogger(__name__)
_slots = threading.BoundedSemaphore(16)
_breakers = {}
_breakers_lock = threading.Lock()


class LLMUnavailableError(RuntimeError):
    """模型暂时不可用；调用状态由现有 checkpoint 保留。"""


class LLMDeadlineError(LLMUnavailableError):
    pass


def retryable(error):
    if isinstance(error, LLMDeadlineError):
        return True
    status = getattr(error, 'status_code', None)
    if status is not None:
        return status == 429 or 500 <= status < 600
    import openai
    return isinstance(error, (openai.APIConnectionError, httpx.TransportError, TimeoutError))


def retry_after(error):
    response = getattr(error, 'response', None)
    value = response.headers.get('retry-after') if response is not None else None
    if not value:
        return 0
    try:
        return max(0, float(value))
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            return max(0, (date - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return 0


class CircuitBreaker:
    def __init__(self):
        self.lock = threading.Lock()
        self.failures = 0
        self.opened = None
        self.probe = False

    def acquire(self, cooldown):
        with self.lock:
            if self.opened is None:
                return True
            if time.monotonic() - self.opened < cooldown or self.probe:
                return False
            self.probe = True
            return True

    def result(self, failed, threshold):
        with self.lock:
            if failed:
                self.failures += 1
                if self.probe or self.failures >= threshold:
                    self.opened = time.monotonic()
            else:
                self.failures = 0
                self.opened = None
            self.probe = False

    def release(self):
        with self.lock:
            self.probe = False


def provider(model):
    endpoint = str(model.openai_api_base or 'https://api.openai.com/v1')
    parsed = urlsplit(endpoint)
    host = parsed.hostname or 'provider'
    if parsed.port:
        host += f':{parsed.port}'
    label = f'{parsed.scheme}://{host}{parsed.path}'
    key = (endpoint, hashlib.sha256(model.openai_api_key.get_secret_value().encode()).hexdigest())
    with _breakers_lock:
        breaker = _breakers.setdefault(key, CircuitBreaker())
    return label, breaker


def check_cancel():
    from agent.workflow.control import check_control
    check_control()


def bounded_call(factory, deadline):
    """在有限容量守护线程读取 SDK，主调用按总期限退出。"""
    if not _slots.acquire(blocking=False):
        raise LLMUnavailableError('未结束的模型请求已达到容量上限')
    results = queue.Queue(maxsize=1)
    stopped = threading.Event()
    ctx = contextvars.copy_context()

    def send(value):
        while not stopped.is_set():
            try:
                results.put(value, timeout=.05)
                return
            except queue.Full:
                pass

    def worker():
        iterator = None
        try:
            check_cancel()
            iterator = iter(factory())
            for value in iterator:
                if stopped.is_set():
                    break
                send((True, value))
            send((True, None))
        except BaseException as ex:
            send((False, ex))
        finally:
            try:
                if iterator is not None and hasattr(iterator, 'close'):
                    iterator.close()
            finally:
                _slots.release()

    threading.Thread(target=ctx.run, args=(worker,), daemon=True, name='llm-request').start()
    try:
        while True:
            check_cancel()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LLMDeadlineError('模型调用超过总耗时上限，会话 checkpoint 已保留')
            try:
                success, value = results.get(timeout=min(.05, remaining))
            except queue.Empty:
                continue
            if not success:
                raise value
            if value is None:
                return
            yield value
    finally:
        stopped.set()


class ReliableChatOpenAI(ChatOpenAI):
    """保留 ChatOpenAI 的工具绑定、消息和 token usage 接口。"""
    retry_count: int = Field(default=10, ge=0)
    retry_base_delay: float = Field(default=1, ge=0, allow_inf_nan=False)
    retry_max_delay: float = Field(default=30, ge=0, allow_inf_nan=False)
    total_timeout: float = Field(default=180, gt=0, allow_inf_nan=False)
    breaker_threshold: int = Field(default=3, ge=1)
    breaker_cooldown: float = Field(default=30, ge=0, allow_inf_nan=False)
    _fallback: ChatOpenAI | None = PrivateAttr(default=None)

    def _attempts(self, messages, stop, streaming, **kwargs):
        deadline = time.monotonic() + self.total_timeout
        last_error = None
        calls = 0
        for role, model in [('primary', self), ('fallback', self._fallback)]:
            if model is None:
                continue
            label, breaker = provider(model)
            limit = self.retry_count + 1
            if role == "primary" and self._fallback is not None and self.retry_count > 0:
                limit -= 1  # 为备用模型保留一次请求，共用总重试预算。
            for attempt in range(limit):
                if calls >= self.retry_count + 1:
                    break
                check_cancel()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise LLMDeadlineError('模型调用超过总耗时上限，会话 checkpoint 已保留') from last_error
                if not breaker.acquire(self.breaker_cooldown):
                    logger.warning('llm role=%s provider=%s model=%s result=circuit_open', role, label, model.model_name)
                    break
                emitted = False
                calls += 1
                try:
                    logger.info('llm role=%s provider=%s model=%s attempt=%s circuit=%s', role, label, model.model_name, attempt + 1, 'half_open' if breaker.probe else 'closed')
                    timeout = model.request_timeout
                    if not isinstance(timeout, (int, float)):
                        timeout = remaining
                    options = dict(kwargs, timeout=min(timeout, remaining))
                    def request():
                        if streaming:
                            return ChatOpenAI._stream(model, messages, stop=stop, run_manager=None, **options)
                        return iter([ChatOpenAI._generate(model, messages, stop=stop, run_manager=None, **options)])
                    for chunk in bounded_call(request, deadline):
                        emitted = True
                        yield chunk
                    breaker.result(False, self.breaker_threshold)
                    logger.info('llm role=%s provider=%s model=%s retries=%s result=success', role, label, model.model_name, attempt)
                    return
                except Exception as ex:
                    can_retry = retryable(ex)
                    breaker.result(can_retry, self.breaker_threshold)
                    logger.warning('llm role=%s provider=%s model=%s attempt=%s result=failed reason=%s status=%s partial=%s', role, label, model.model_name, attempt + 1, type(ex).__name__, getattr(ex, 'status_code', None), emitted)
                    if isinstance(ex, LLMDeadlineError) or not can_retry or emitted:
                        raise
                    last_error = ex
                    if attempt == limit - 1 or calls >= self.retry_count + 1:
                        break
                    delay = max(retry_after(ex), random.uniform(0, min(self.retry_max_delay, self.retry_base_delay * (2 ** attempt))))
                    if delay >= deadline - time.monotonic():
                        raise LLMUnavailableError('模型重试等待超过剩余总时限，会话 checkpoint 已保留') from ex
                    end = time.monotonic() + delay
                    while time.monotonic() < end:
                        check_cancel()
                        time.sleep(min(.05, max(0, end - time.monotonic())))
                except BaseException:
                    breaker.release()
                    raise
        raise LLMUnavailableError('API 接口异常，模型请求未能成功，请稍后重试；会话 checkpoint 已保留') from last_error

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return list(self._attempts(messages, stop, False, **kwargs))[0]

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        for chunk in self._attempts(messages, stop, True, **kwargs):
            if run_manager:
                run_manager.on_llm_new_token(chunk.text, chunk=chunk, logprobs=(chunk.generation_info or {}).get('logprobs'))
            yield chunk

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return await asyncio.to_thread(self._generate, messages, stop, run_manager.get_sync() if run_manager else None, **kwargs)

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        iterator = self._stream(messages, stop, None, **kwargs)
        sentinel = object()
        try:
            while True:
                chunk = await asyncio.to_thread(next, iterator, sentinel)
                if chunk is sentinel:
                    return
                if run_manager:
                    await run_manager.on_llm_new_token(chunk.text, chunk=chunk)
                yield chunk
        finally:
            iterator.close()
