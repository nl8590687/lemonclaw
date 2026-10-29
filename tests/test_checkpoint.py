"""单库 checkpoint、主会话崩溃恢复及 Workflow 升级兼容回归。"""

import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from typing import TypedDict

import dao.db as db
from agent.agent import AgentService
from agent.checkpoint import PersistentSaver
from agent.workflow.runner import WorkflowRunner


class FakeModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def make_service(responses=None, tools=None):
    config = SimpleNamespace(
        ENABLE_MEMORY=False, ENABLE_SKILLS=False, ENABLE_MCP=False,
        ENABLE_WORKFLOW=False, AGENT_REACT_MAX_ITERATIONS=10,
        CONTEXT_MIN_FULL_MESSAGES=2, MODEL_CONTEXT_LENGTH=10000,
        MODEL_MAX_COMPLETION_TOKEN=1000,
    )
    with (patch('agent.agent.get_global_config', return_value=config),
          patch('agent.agent.create_openai_llm', return_value=FakeModel(
              responses=responses or [AIMessage(content='回答')])),
          patch('agent.agent.create_tool_list', return_value=tools or []),
          patch('agent.agent.get_system_prompt', return_value='测试助手'),
          patch('agent.agent.build_output_channel', return_value=MagicMock())):
        return AgentService()


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(db, '_global_db_path', None)
    return db.get_db_path()


def test_restart_history_and_reset_isolation(database):
    first = make_service()
    first.run('甲的历史', {}, session_key='a')
    first.run('乙的历史', {}, session_key='b')
    first.close()
    second = make_service()
    try:
        result = second.run('甲的新消息', {}, session_key='a')
        assert [m.content for m in result['messages']] == ['甲的历史', '回答', '甲的新消息', '回答']
        second.reset_session()
        assert second._current_messages() == []
        assert second.checkpointer.get_tuple(second._thread_config()) is None
        result = second.run('乙的新消息', {'session_key': 'b'})
        assert [m.content for m in result['messages']] == ['乙的历史', '回答', '乙的新消息', '回答']
        # 无 key 的请求不会意外沿用上一条显式 key。
        result = second.run('默认会话', {})
        assert [m.content for m in result['messages']] == ['默认会话', '回答']
        assert list(database.parent.glob('*.db')) == [database]
        assert second.checkpointer.conn.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        assert second.checkpointer.conn.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
    finally:
        second.close()


class WorkflowState(TypedDict):
    answer: str


def human_graph(saver):
    graph = StateGraph(WorkflowState)
    def ask(state):
        return {'answer': interrupt('是否继续')}
    graph.add_node('ask', ask)
    graph.add_edge(START, 'ask')
    graph.add_edge('ask', END)
    return graph.compile(checkpointer=saver)


@pytest.mark.parametrize('legacy', [False, True])
def test_workflow_restart_resume_and_namespace(database, legacy):
    saver = PersistentSaver()
    graph = human_graph(saver)
    thread_id = 'same' if legacy else 'workflow:same'
    graph.invoke({'answer': ''}, {'configurable': {'thread_id': thread_id}})
    saver.close()
    agent = make_service()
    agent.run('主会话', {}, session_key='same')
    agent.reset_session()
    agent.close()
    saver = PersistentSaver()
    try:
        runner = WorkflowRunner(saver, 25, 2000)
        with patch.object(runner, '_publish'):
            result = runner.resume(human_graph(saver), 'same', 'wf', '同意', {})
        assert result['status'] == 'completed'
        assert result['payload']['result']['answer'] == '同意'
    finally:
        saver.close()


def crash_worker(database_path, marker_path, in_tool):
    """由子进程调用：先落盘完成 turn，再在下一轮阻塞直到被 SIGKILL。"""
    db._global_db_path = Path(database_path)
    service = make_service()
    service.run('崩溃前已完成', {}, session_key='crash')
    service.close()
    marker = Path(marker_path)
    if in_tool:
        @tool
        def side_effect() -> str:
            """模拟不可重复执行的副作用。"""
            marker.write_text('executed', encoding='utf-8')
            while True:
                time.sleep(1)
        service = make_service([AIMessage(content='', tool_calls=[{
            'name': 'side_effect', 'args': {}, 'id': 'call-1', 'type': 'tool_call',
        }])], [side_effect])
        service.run('执行工具', {}, session_key='crash')
    else:
        marker.write_text('completed', encoding='utf-8')
        while True:
            time.sleep(1)


@pytest.mark.skipif(sys.platform == 'win32', reason='SIGKILL 崩溃模拟仅适用于 POSIX')
@pytest.mark.parametrize('in_tool,keep_tools', [(False, False), (True, False), (True, True)])
def test_sigkill_recovery(database, tmp_path, in_tool, keep_tools):
    marker = tmp_path / 'marker'
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join([str(Path(__file__).parent.parent), str(Path(__file__).parent)])
    error_log = (tmp_path / 'worker.stderr').open('w+')
    process = subprocess.Popen([
        sys.executable, '-c',
        'from test_checkpoint import crash_worker; import sys; '
        'crash_worker(sys.argv[1], sys.argv[2], sys.argv[3] == "True")',
        str(database), str(marker), str(in_tool),
    ], env=env, stdout=subprocess.DEVNULL, stderr=error_log)
    try:
        deadline = time.monotonic() + 60
        while (not marker.exists() or not marker.read_text()) and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        error_log.flush()
        error_log.seek(0)
        assert marker.exists() and marker.read_text(), error_log.read() or '子进程未到达崩溃点'
        process.send_signal(signal.SIGKILL)
        process.wait(timeout=10)
        assert process.returncode == -signal.SIGKILL
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)
        error_log.close()
    @tool
    def side_effect() -> str:
        """记录意外重放。"""
        marker.write_text('repeated', encoding='utf-8')
        return '执行完毕'
    service = make_service(tools=[side_effect] if keep_tools else [])
    try:
        if in_tool:
            before = service.checkpointer.get_tuple({'configurable': {'thread_id': 'session:crash'}})
            assert service.run('继续', {}, session_key='crash') is None
            service.default_out_chan.write_system_error.assert_called_once()
            service.trim_msg_history()
            assert service.checkpointer.get_tuple(service._thread_config()) == before
            assert marker.read_text() == 'executed'
            service.reset_session()
            assert service.run('重新开始', {}, session_key='crash') is not None
        else:
            result = service.run('重启后的消息', {}, session_key='crash')
            assert [m.content for m in result['messages']] == ['崩溃前已完成', '回答', '重启后的消息', '回答']
    finally:
        service.close()


def test_failed_model_turn_is_not_automatically_replayed(database):
    class FailingModel(FakeModel):
        def _generate(self, *args, **kwargs):
            raise RuntimeError('模拟模型进程中断')

    service = make_service()
    from agent.agent import _create_agent
    service.agent = _create_agent(FailingModel(responses=[AIMessage(content='')]), [], '测试', service.checkpointer)
    with pytest.raises(RuntimeError, match='模拟模型进程中断'):
        service.run('未完成的请求', {}, session_key='failed')
    service.close()
    restarted = make_service()
    try:
        assert restarted.run('新请求', {}, session_key='failed') is None
        restarted.default_out_chan.write_system_error.assert_called_once()
        restarted.reset_session()
        assert restarted.run('新请求', {}, session_key='failed') is not None
    finally:
        restarted.close()


def test_tool_call_is_durable_before_side_effect(database, monkeypatch):
    """人为延迟工具调用 checkpoint，保证副作用不会抢在落盘之前发生。"""
    from threading import Event

    tool_checked = Event()
    observed = []
    reader = PersistentSaver()

    @tool
    def side_effect() -> str:
        """模拟需要可靠中断保护的外部写操作。"""
        try:
            saved = reader.get_tuple({'configurable': {'thread_id': 'session:durable'}})
            messages = saved.checkpoint['channel_values'].get('messages', []) if saved else []
            observed.append(any(isinstance(msg, AIMessage) and msg.tool_calls for msg in messages))
        finally:
            tool_checked.set()
        return '完成'

    service = make_service([
        AIMessage(content='', tool_calls=[{
            'name': 'side_effect', 'args': {}, 'id': 'durable-call', 'type': 'tool_call',
        }]), AIMessage(content='已完成'),
    ], [side_effect])
    original_put = service.checkpointer.put

    def delayed_put(config, checkpoint, metadata, new_versions):
        if any(isinstance(msg, AIMessage) and msg.tool_calls
               for msg in checkpoint['channel_values'].get('messages', [])):
            # async 时工具先读取旧状态并解除等待；sync 时等待超时后先落盘再执行工具。
            tool_checked.wait(timeout=1)
        return original_put(config, checkpoint, metadata, new_versions)

    monkeypatch.setattr(service.checkpointer, 'put', delayed_put)
    try:
        service.run('执行写操作', {}, session_key='durable')
        assert observed == [True], '副作用执行前，工具调用 checkpoint 必须已提交'
    finally:
        service.close()
        reader.close()
