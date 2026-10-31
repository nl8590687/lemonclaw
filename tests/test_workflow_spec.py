"""声明式 Workflow 定义校验与兼容性。"""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import MemorySaver

from agent.workflow.builder import WorkflowBuilder
from agent.workflow.spec import validate_spec
from dao.workflow import Workflow


def legacy():
    return {"state_schema": {"answer": "str"}, "nodes": [
        {"name": "ask", "kind": "human", "question": "继续？", "output_key": "answer"}], "edges": []}


def builder():
    return WorkflowBuilder(None, {}, MemorySaver(), SimpleNamespace(get_workflow=lambda _: None))


@pytest.mark.parametrize("change,match", [
    (lambda s: s.update(nodes=[]), "nodes"),
    (lambda s: s['nodes'].append(deepcopy(s['nodes'][0])), "节点名重复"),
    (lambda s: s.update(edges=[{'src': 'missing', 'dst': 'ask'}]), "edges"),
    (lambda s: s['nodes'][0].update(kind='python'), "kind"),
    (lambda s: s.update(state_schema={'answer': 'invalid'}), "answer"),
    (lambda s: s.update(conditionals=[{'src': 'ask', 'mapping': {}}]), "mapping"),
    (lambda s: s.update(conditionals=[{'src': 'ask', 'router': {'field': 'missing'}, 'mapping': {'ok': 'END'}}]), "router.field"),
    (lambda s: s.update(conditionals=[{'src': 'ask', 'mapping': {'ok': 'missing'}}]), "mapping"),
    (lambda s: s['nodes'][0].update(kind='tool', tool_name='missing'), "tool_name"),
    (lambda s: s['nodes'][0].update(kind='subagent', tools=['missing']), "tools"),
    (lambda s: s['nodes'][0].update(kind='subgraph', sub_workflow_id='missing'), "sub_workflow_id"),
    (lambda s: s.update(spec_version=2), "spec_version"),
])
def test_invalid(change, match):
    spec = legacy()
    change(spec)
    with pytest.raises(ValueError, match=match):
        validate_spec(spec, builder(), 'test')


def test_migration_compiles_and_is_idempotent():
    wf = Workflow('test', 'test', spec=legacy())
    b = builder()
    b.compile(wf)
    assert wf.spec['spec_version'] == 1
    assert wf.spec['nodes'][0]['config']['output_field'] == 'answer'
    assert validate_spec(wf.spec, b, 'test') == wf.spec


def test_limits(monkeypatch):
    from config import get_global_config
    cfg = get_global_config()
    monkeypatch.setattr(cfg, 'WORKFLOW_MAX_NODES', 0)
    with pytest.raises(ValueError, match='nodes'):
        validate_spec(legacy(), builder(), 'test')
    monkeypatch.setattr(cfg, 'WORKFLOW_MAX_NODES', 50)
    monkeypatch.setattr(cfg, 'WORKFLOW_MAX_BRANCHES', 1)
    spec = legacy()
    spec['conditionals'] = [{'src': 'ask', 'router': {'field': 'answer'}, 'mapping': {'a': 'END', 'b': 'ask'}}]
    with pytest.raises(ValueError, match='分支上限'):
        validate_spec(spec, builder(), 'test')


def test_nested_cycle_and_depth():
    b = builder()
    spec = legacy()
    spec['nodes'][0].update(kind='subgraph', sub_workflow_id='test')
    b.manager.get_workflow = lambda _: Workflow('test', 'test', spec=spec)
    with pytest.raises(ValueError, match='循环引用'):
        validate_spec(spec, b, 'test')
    with pytest.raises(ValueError, match='5 层'):
        validate_spec(legacy(), b, 'test', tuple(str(i) for i in range(8)))


def test_boolean_routes_require_both_branches():
    spec = legacy()
    spec['state_schema']['ready'] = 'bool'
    spec['conditionals'] = [{'src': 'ask', 'router': {'field': 'ready'}, 'mapping': {'True': 'END'}}]
    with pytest.raises(ValueError, match='True/False'):
        validate_spec(spec, builder(), 'test')


def test_json_schema_and_json_args_compatibility():
    spec = legacy()
    spec['state_schema'] = {'type': 'object', 'properties': {'answer': {'type': 'string'}}}
    spec['nodes'] = [{'name': 't', 'kind': 'tool', 'config': {
        'tool_name': 'echo', 'args': '{"text": "hi"}', 'output_field': 'answer'}}]
    b = builder()
    b.tools['echo'] = object()
    normalized = validate_spec(spec, b, 'test')
    assert normalized['nodes'][0]['config']['args'] == {'text': 'hi'}
    assert normalized['state_schema'][0]['type'] == 'string'
