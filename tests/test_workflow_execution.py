"""Workflow 选择契约、来源、周期绑定和 Skill 正文回归。"""

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver

from agent.workflow.builder import WorkflowBuilder
from agent.workflow.manager import WorkflowManager
from agent.workflow.tools import create_workflow_tools
from agent.tools.cron_tool import CreateCronTaskTool, UpdateCronTaskTool, GetCronTaskTool
from channels.device.crontab import CronTaskManager
from channels.ins.crontab import CrontabInput
from tests.test_checkpoint import database, make_service, FakeModel  # noqa: F401

ORIGIN = {'source': 'feishu', 'open_id': 'ou_test', 'chat_id': 'oc_test', 'session_key': 'feishu:test'}
CONFIG = {'configurable': {'origin_context': {**ORIGIN, 'secret': 'excluded'}}}


def workflow():
    return SimpleNamespace(workflow_id='daily', enabled=True, last_error=None, spec={})


def test_workflow_tools_hide_config_and_keep_origin():
    manager = MagicMock()
    manager.start_run.return_value = ('run1', {'status': 'running'})
    manager.resume_run.return_value = {'status': 'resuming'}
    manager.inject_run.return_value = {'status': 'resuming'}
    tools = {t.name: t for t in create_workflow_tools(manager)}
    for name in ['workflow_execute', 'workflow_resume', 'workflow_inject']:
        assert 'config' not in tools[name].tool_call_schema.model_json_schema()['properties']
    tools['workflow_execute'].invoke({'workflow_id': 'daily', 'input': '{"city":"北京"}'}, config=CONFIG)
    manager.start_run.assert_called_once_with('daily', {'city': '北京'}, ORIGIN)
    tools['workflow_resume'].invoke({'run_id': 'run1', 'value': '同意'}, config=CONFIG)
    manager.resume_run.assert_called_once_with('run1', '同意', ORIGIN)
    tools['workflow_inject'].invoke({'run_id': 'run1', 'message': '继续'}, config=CONFIG)
    manager.inject_run.assert_called_once_with('run1', '继续', ORIGIN)


@pytest.mark.parametrize('data', ['{bad', '[]', 'null', '"x"'])
def test_bad_workflow_input_is_not_started(data):
    manager = MagicMock()
    tools = {t.name: t for t in create_workflow_tools(manager)}
    assert '❌' in tools['workflow_execute'].invoke({'workflow_id': 'daily', 'input': data})
    manager.start_run.assert_not_called()
    assert '❌' in tools['workflow_define'].invoke({'name': 'test', 'description': 'test', 'spec': data})
    manager.define_workflow.assert_not_called()


def test_cron_binding_update_clear_and_restart(database):
    manager = CronTaskManager()
    wf_manager = MagicMock()
    wf_manager.get_workflow.return_value = workflow()
    with patch('agent.workflow.get_workflow_manager', return_value=wf_manager):
        create = CreateCronTaskTool(manager)
        assert 'config' not in create.tool_call_schema.model_json_schema()['properties']
        result = create.invoke({'prompt': '每日天气', 'cron_expression': '0 9 * * *',
                                'workflow_id': '每日天气', 'workflow_input': '{"city":"北京"}'}, config=CONFIG)
        assert '创建成功' in result
        task = manager.list_tasks()[0]
        assert task.metadata == {'workflow_id': 'daily', 'workflow_input': {'city': '北京'},
                                 'origin_context': ORIGIN}
        restarted = CronTaskManager()
        assert restarted.get_task(task.task_id).metadata == task.metadata
        assert restarted.load_tasks() == 1
        assert restarted.scheduler.get_task(task.task_id).metadata == task.metadata
        detail = GetCronTaskTool(restarted).invoke({'task_id': task.task_id})
        assert 'daily' in detail and '北京' in detail
        update = UpdateCronTaskTool(manager)
        assert '更新成功' in update.invoke({'task_id': task.task_id, 'workflow_input': '{"city":"上海"}'})
        assert manager.get_task(task.task_id).metadata['workflow_input'] == {'city': '上海'}
        update.invoke({'task_id': task.task_id, 'prompt': '新说明'})
        assert manager.get_task(task.task_id).metadata['workflow_id'] == 'daily'
        update.invoke({'task_id': task.task_id, 'workflow_id': ''})
        assert manager.get_task(task.task_id).metadata == {}


@pytest.mark.parametrize('wf', [None, SimpleNamespace(enabled=False), SimpleNamespace(enabled=True, last_error='bad'),
                               SimpleNamespace(enabled=True, last_error=None, spec={'one_shot': True})])
def test_invalid_periodic_workflow_rejected(database, wf):
    manager = CronTaskManager()
    wm = MagicMock()
    wm.get_workflow.return_value = wf
    with patch('agent.workflow.get_workflow_manager', return_value=wm):
        result = CreateCronTaskTool(manager).invoke({'prompt': '周期', 'cron_expression': '@daily', 'workflow_id': 'x'})
    assert '失败' in result
    assert manager.list_tasks() == []


def wait_for(predicate):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    assert predicate()


def test_periodic_runs_background_hitl_and_origin(database):
    with patch('agent.llm.create_openai_llm', return_value=MagicMock()):
        wm = WorkflowManager()
    wm._tools_dict = {}
    wm.runner._publish = MagicMock()
    wm.define_workflow('daily', '周期审批', {
        'state_schema': [{'name': 'answer', 'type': 'str'}],
        'nodes': [{'name': 'ask', 'kind': 'human', 'config': {'question': '继续？', 'output_field': 'answer'}}],
    })
    cron = CronTaskManager()
    wm_get = patch('agent.workflow.get_workflow_manager', return_value=wm)
    try:
        with wm_get:
            CreateCronTaskTool(cron).invoke({'prompt': '周期', 'cron_expression': '@daily',
                                            'workflow_id': 'daily'}, config=CONFIG)
            task = cron.list_tasks()[0]
            channel = object.__new__(CrontabInput)
            cron.set_on_trigger(channel._write_message)
            with patch('channels.ins.crontab.get_bus') as bus:
                cron.scheduler._fire(task)
                cron.scheduler._fire(task)
            bus.assert_not_called()
        wait_for(lambda: len(wm.list_runs(status='paused')) == 2)
        runs = wm.list_runs(status='paused')
        assert len({r.run_id for r in runs}) == 2
        assert all(r.origin_context['chat_id'] == 'oc_test' for r in runs)
        run = runs[0]
        assert wm.resume_run(run.run_id, '同意', {'source': 'terminal'})['status'] == 'resuming'
        wait_for(lambda: wm.inspect_run(run.run_id)['status'] == 'completed')
        assert wm.inspect_run(run.run_id)['output']['answer'] == '同意'
        assert wm.runner._publish.call_args.args[-1]['chat_id'] == 'oc_test'
    finally:
        wm.executor.shutdown()
        wm.checkpointer.close()


def test_legacy_cron_still_publishes_prompt(database):
    cron = CronTaskManager()
    task = cron.create_task('提醒喝水', '@daily')
    channel = object.__new__(CrontabInput)
    cron.set_on_trigger(channel._write_message)
    with patch('channels.ins.crontab.get_bus') as get_bus, patch('agent.workflow.get_workflow_manager') as wm:
        cron.scheduler._fire(task)
    wm.assert_not_called()
    assert get_bus.return_value.publish.call_args.kwargs['content']['text'] == '提醒喝水'


def test_skill_body_and_availability():
    builder = WorkflowBuilder(None, {}, MemorySaver(), MagicMock())
    sm = MagicMock()
    sm.is_available.return_value = True
    sm.registry.get_full_content.return_value = '# 必须遵循完整技能指令\n使用 ${API_KEY}'
    with patch('agent.skill.get_skill_manager', return_value=sm), patch('config.get_global_config', return_value=SimpleNamespace(ENABLE_SKILLS=True)):
        result = builder._resolve_skills(['research'])
        assert '完整技能指令' in result and '${API_KEY}' in result
        sm.get_skill.assert_not_called()
        sm.is_available.return_value = False
        with pytest.raises(ValueError, match='技能不可用'):
            builder._resolve_skills(['research'])


def test_subagent_refresh_is_per_run():
    from langchain.agents import create_agent
    wm = object.__new__(WorkflowManager)
    wm.llm = FakeModel(responses=[AIMessage(content='done')])
    wm.checkpointer = MemorySaver()
    wm._subagents = {}
    wm._tools_dict = {}
    sm = MagicMock()
    sm.is_available.return_value = True
    sm.registry.get_full_content.return_value = 'original body'
    with (patch('agent.skill.get_skill_manager', return_value=sm),
          patch('config.get_global_config', return_value=SimpleNamespace(ENABLE_SKILLS=True)),
          patch('agent.workflow.subagents.create_agent', wraps=create_agent) as build):
        wm._make_builder()._build_subagent('sa', {'skills': ['research'], 'system_prompt': 'BASE'}, 'step')
        agent = wm._subagents['sa']
        original_prompt = agent.system_prompt
        sm.registry.get_full_content.return_value = 'current body'
        assert wm.run_subagent_inline('sa', '任务') == 'done'
        assert build.call_args.kwargs['system_prompt'] == 'BASE\n\n## 技能: research\ncurrent body'
        assert agent.system_prompt == original_prompt
        sm.is_available.return_value = False
        with pytest.raises(ValueError, match='技能不可用'):
            wm.run_subagent_inline('sa', '任务')
        sm.load_skill.assert_not_called()
        sm.unload_skill.assert_not_called()


def test_tool_node_passes_hidden_config():
    from agent.workflow.nodes import make_node
    from langchain_core.runnables import RunnableConfig
    @tool
    def inspect_origin(config: RunnableConfig) -> str:
        """返回隐式来源。"""
        return config['configurable']['origin_context']['chat_id']
    node = make_node('tool', {'tool_name': 'inspect_origin'}, None, {'inspect_origin': inspect_origin}, None)
    assert node({}, CONFIG)['output'] == 'oc_test'


def test_main_agent_passes_origin_to_workflow(database):
    manager = MagicMock()
    manager.start_run.return_value = ('run1', {'status': 'running'})
    tools = create_workflow_tools(manager)
    service = make_service([
        AIMessage(content='', tool_calls=[{'id': 'start1', 'name': 'workflow_execute',
                   'args': {'workflow_id': 'daily'}, 'type': 'tool_call'}]),
        AIMessage(content='已后台启动'),
    ], tools)
    try:
        service.run('后台调研', {**ORIGIN, 'secret': 'excluded'})
        manager.start_run.assert_called_once_with('daily', {}, ORIGIN)
    finally:
        service.close()


def test_workflow_worker_does_not_block_and_retains_feishu_context(database):
    from threading import Event
    from langchain_core.runnables import RunnableConfig
    from agent.tools.feishu_tool import get_feishu_turn
    entered, release = Event(), Event()
    seen = []
    @tool
    def background_job(config: RunnableConfig) -> str:
        """模拟后台长任务。"""
        seen.append((get_feishu_turn().chat_id, config['configurable']['origin_context']))
        entered.set()
        assert release.wait(timeout=5)
        return 'done'
    with patch('agent.llm.create_openai_llm', return_value=MagicMock()):
        wm = WorkflowManager()
    wm._tools_dict = {'background_job': background_job}
    wm.runner._publish = MagicMock()
    try:
        wm.define_workflow('background', '后台测试', {
            'state_schema': [{'name': 'result', 'type': 'str'}],
            'nodes': [{'name': 'job', 'kind': 'tool', 'config': {
                'tool_name': 'background_job', 'output_field': 'result'}}],
        })
        run_id, result = wm.start_run('background', {}, ORIGIN)
        assert result['status'] == 'running'
        assert entered.wait(timeout=5)
        assert wm.inspect_run(run_id)['status'] == 'running'
        assert seen == [('oc_test', ORIGIN)]
        release.set()
        wait_for(lambda: wm.inspect_run(run_id)['status'] == 'completed')
    finally:
        release.set()
        wm.executor.shutdown()
        wm.checkpointer.close()


def test_removed_periodic_definition_logs_without_prompt_fallback(database):
    cron = CronTaskManager()
    task = cron.create_task('周期报告', '@daily', metadata={'workflow_id': 'removed', 'workflow_input': {}})
    channel = object.__new__(CrontabInput)
    cron.set_on_trigger(channel._write_message)
    wm = MagicMock()
    wm.get_workflow.return_value = None
    with patch('agent.workflow.get_workflow_manager', return_value=wm), patch('channels.ins.crontab.get_bus') as bus:
        cron.scheduler._fire(task)
    bus.assert_not_called()
    wm.start_run.assert_not_called()
    assert cron.get_task(task.task_id).last_run_at is None


@pytest.mark.parametrize('data', ['[1]', '{bad', 'null'])
def test_bad_periodic_input_does_not_create_task(database, data):
    cron = CronTaskManager()
    wm = MagicMock()
    wm.get_workflow.return_value = workflow()
    with patch('agent.workflow.get_workflow_manager', return_value=wm):
        result = CreateCronTaskTool(cron).invoke({'prompt': '报告', 'cron_expression': '@daily',
                                                'workflow_id': 'daily', 'workflow_input': data})
    assert '失败' in result
    assert cron.list_tasks() == []


def test_background_registry_uses_declared_skills():
    wm = object.__new__(WorkflowManager)
    wm._tools_dict = None
    tools = [SimpleNamespace(name=name) for name in
             ['workflow_execute', 'load_skill', 'unload_skill', 'recall_memory']]
    with patch('agent.tools.create_tool_list', return_value=tools):
        assert list(wm._get_tools_dict()) == ['recall_memory']
