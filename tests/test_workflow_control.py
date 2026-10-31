"""使用真实图和阻塞工具验证取消、超时与重试。"""
import threading
import time
from unittest.mock import MagicMock

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.tools import tool

from agent.workflow.control import RunControl, WorkflowStopped, _current, controlled_node, ControlCallback
from agent.workflow.builder import WorkflowBuilder
from agent.workflow.runner import WorkflowRunner
from dao.workflow import Workflow


def execute(fn, policy=None):
    return controlled_node(fn, policy or {}, 'test')({}, {})


def test_retry_only_failed_node():
    calls = []
    def flaky(state, config):
        calls.append(1)
        if len(calls) < 3:
            raise ValueError('transient')
        return {'out': 'ok'}
    assert execute(flaky, {'max_retries': 2, 'retry_backoff': 0}) == {'out': 'ok'}
    assert len(calls) == 3


def test_continue_and_compensate():
    def broken(state, config):
        raise ValueError('failed')
    assert 'failed' in execute(broken, {'on_error': 'continue', 'output_field': 'out'})['out']
    calls = []
    def undo(state, config):
        calls.append(1)
        return {'out': 'compensated'}
    assert controlled_node(broken, {'on_error': 'compensate'}, 'broken', undo)({}, {}) == {'out': 'compensated'}
    assert calls == [1]


def test_timeout_does_not_retry_and_discards_late_result():
    release = threading.Event()
    calls = []
    def blocked(state, config):
        calls.append(1)
        release.wait(5)
        return {'out': 'late'}
    try:
        from agent.workflow.control import NodeTimeout
        with pytest.raises(NodeTimeout, match='线程仍可能运行'):
            execute(blocked, {'timeout_seconds': .05, 'max_retries': 3})
        assert len(calls) == 1
    finally:
        release.set()


def test_callback_prevents_calls_after_cancel():
    control = RunControl()
    callback = ControlCallback(control)
    control.cancelled.set()
    for method in (callback.on_tool_start, callback.on_chat_model_start, callback.on_llm_start):
        with pytest.raises(WorkflowStopped):
            method()


def test_cancel_during_retry_backoff():
    control = RunControl()
    called = threading.Event()
    def broken(state, config):
        called.set()
        raise ValueError('failed')
    timer = threading.Timer(.1, control.cancelled.set)
    token = _current.set(control)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(WorkflowStopped):
            execute(broken, {'max_retries': 2, 'retry_backoff': 10})
        assert time.monotonic() - started < 2
    finally:
        timer.cancel()
        _current.reset(token)


@pytest.mark.parametrize("mode", ["cancel", "timeout"])
def test_real_graph_cancel_and_worker_release(mode):
    from concurrent.futures import ThreadPoolExecutor
    entered, release = threading.Event(), threading.Event()
    calls = []
    @tool
    def blocking() -> str:
        """等待测试释放。"""
        entered.set()
        release.wait(5)
        calls.append('inflight')
        return 'done'
    @tool
    def following() -> str:
        """记录后续调用。"""
        calls.append('following')
        return 'done'
    cp = MemorySaver()
    builder = WorkflowBuilder(None, {'blocking': blocking, 'following': following}, cp, MagicMock())
    spec = {'state_schema': {'a': 'str', 'b': 'str'}, 'nodes': [
        {'name': 'first', 'kind': 'tool', 'config': {'tool_name': 'blocking', 'output_field': 'a', 'timeout_seconds': .15 if mode == 'timeout' else 5}},
        {'name': 'second', 'kind': 'tool', 'config': {'tool_name': 'following', 'output_field': 'b'}}],
        'edges': [{'src': 'first', 'dst': 'second'}]}
    graph = builder.compile(Workflow('control', 'control', spec=spec))
    runner = WorkflowRunner(cp, 50, 1000)
    runner._publish = MagicMock()
    control = RunControl()
    def run():
        token = _current.set(control)
        try:
            return runner.invoke(graph, 'cancel', 'control', {}, {}, None)
        finally:
            _current.reset(token)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run)
        try:
            assert entered.wait(3)
            if mode == 'cancel':
                control.cancelled.set()
            assert future.result(timeout=2)['status'] == ('cancelled' if mode == 'cancel' else 'error')
            assert pool.submit(lambda: 'free').result(timeout=1) == 'free'
            if mode == "cancel":
                assert not runner._publish.called
            else:
                assert runner._publish.call_args.args[2] == "error"
        finally:
            release.set()
    time.sleep(.1)
    assert 'following' not in calls


def test_real_tool_retry_preserves_successful_predecessor():
    calls = []
    @tool
    def success() -> str:
        """成功步骤。"""
        calls.append('success')
        return 'ok'
    @tool
    def flaky() -> str:
        """暂时失败的步骤。"""
        calls.append('flaky')
        if calls.count('flaky') == 1:
            raise ValueError('transient')
        return 'ok'
    cp = MemorySaver()
    graph = WorkflowBuilder(None, {'success': success, 'flaky': flaky}, cp, MagicMock()).compile(
        Workflow('retry', 'retry', spec={'state_schema': {'a': 'str', 'b': 'str'}, 'nodes': [
            {'name': 'a', 'kind': 'tool', 'config': {'tool_name': 'success', 'output_field': 'a'}},
            {'name': 'b', 'kind': 'tool', 'config': {'tool_name': 'flaky', 'output_field': 'b', 'max_retries': 1, 'retry_backoff': 0}}],
            'edges': [{'src': 'a', 'dst': 'b'}]}))
    assert graph.invoke({}, {'configurable': {'thread_id': 'retry'}})['b'] == 'ok'
    assert calls == ['success', 'flaky', 'flaky']


def test_real_tool_and_model_callback_blocks_invocation():
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage
    calls = []
    @tool
    def effect() -> str:
        """记录副作用。"""
        calls.append(1)
        return 'ok'
    control = RunControl()
    control.cancelled.set()
    config = {'callbacks': [ControlCallback(control)]}
    with pytest.raises(WorkflowStopped):
        effect.invoke({}, config=config)
    model = FakeMessagesListChatModel(responses=[AIMessage(content='ok')])
    with pytest.raises(WorkflowStopped):
        model.invoke('test', config=config)
    assert calls == []


def test_timeout_graph_reports_error_and_no_completion():
    from agent.workflow.control import NodeTimeout
    parent = RunControl()
    runner = WorkflowRunner(MemorySaver(), 10, 100)
    runner._publish = MagicMock()
    graph = MagicMock()
    graph.invoke.side_effect = NodeTimeout('节点超时；线程仍可能运行')
    token = _current.set(parent)
    try:
        result = runner.invoke(graph, 'timeout', 'wf', {}, {}, None)
    finally:
        _current.reset(token)
    assert result['status'] == 'error'
    assert runner._publish.call_args.args[2] == 'error'


def test_real_compensation_tool_runs_once():
    calls = []
    @tool
    def failed() -> str:
        """模拟失败。"""
        calls.append('failed')
        raise ValueError('failed')
    @tool
    def undo() -> str:
        """执行补偿。"""
        calls.append('undo')
        return 'compensated'
    graph = WorkflowBuilder(None, {'failed': failed, 'undo': undo}, MemorySaver(), MagicMock()).compile(
        Workflow('compensate', 'compensate', spec={'state_schema': {'out': 'str'}, 'nodes': [
            {'name': 'step', 'kind': 'tool', 'config': {'tool_name': 'failed', 'output_field': 'out',
             'on_error': 'compensate', 'compensation': {'tool_name': 'undo', 'args': {}}}}]}))
    assert graph.invoke({}, {'configurable': {'thread_id': 'compensate'}})['out'] == 'compensated'
    assert calls == ['failed', 'undo']
