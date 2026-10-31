"""Workflow spec 结构校验、旧格式迁移及引用检查。"""

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent.workflow.state import REDUCERS, TYPE_MAP


class SpecModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class StateField(SpecModel):
    name: str = Field(min_length=1, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    type: str = "Any"
    reducer: str | None = None


class NodeConfig(SpecModel):
    timeout_seconds: float = Field(default=300, gt=0, allow_inf_nan=False)
    max_retries: int = Field(default=0, ge=0, le=10)
    retry_backoff: float = Field(default=1, ge=0, le=300, allow_inf_nan=False)
    on_error: Literal["fail", "continue", "compensate"] = "fail"
    compensation: dict[str, Any] | None = None
    image_ids: list[str] = Field(default_factory=list)
    image_ids_field: str = ""
    output_field: str | None = None
    prompt: str = ""
    tool_name: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    type: str = "general"
    system_prompt: str = "你是一个专注的子 Agent，完成分配给你的子任务。"
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    task: str = ""
    task_template: str = ""
    summary: str = ""
    question: str = ""
    handler: str = "interactive"
    sub_workflow_id: str = ""


class Node(SpecModel):
    name: str = Field(min_length=1, pattern=r"^[A-Za-z_][A-Za-z0-9_-]*$")
    kind: Literal["llm", "tool", "subagent", "main_agent", "human", "subgraph"]
    config: NodeConfig = Field(default_factory=NodeConfig)


class Edge(SpecModel):
    src: str
    dst: str


class Router(SpecModel):
    kind: Literal["state_field", "llm"] = "state_field"
    field: str = ""


class Conditional(SpecModel):
    src: str
    router: Router = Field(default_factory=Router)
    mapping: dict[str, str] = Field(min_length=1)


class WorkflowSpec(SpecModel):
    spec_version: Literal[1] = 1
    one_shot: bool = False
    state_schema: list[StateField] = Field(default_factory=list)
    nodes: list[Node] = Field(min_length=1)
    edges: list[Edge] = Field(default_factory=list)
    conditionals: list[Conditional] = Field(default_factory=list)


def validate_spec(raw: dict, builder, workflow_id: str, ancestors: tuple[str, ...] = ()) -> dict:
    """迁移旧字段后检查完整图及子图，返回可保存的标准 spec。"""
    from config import get_global_config
    cfg = get_global_config()
    if workflow_id in ancestors or len(ancestors) > cfg.WORKFLOW_NESTING_MAX:
        raise ValueError(f"subgraph {workflow_id}: 循环引用或嵌套超过 {cfg.WORKFLOW_NESTING_MAX} 层")
    data = dict(raw)
    fields = data.get("state_schema", [])
    if isinstance(fields, dict):
        if "properties" not in fields and any(not isinstance(v, str) for v in fields.values()):
            raise ValueError("state_schema: 字段类型必须是字符串")
        fields = builder._normalize_state_schema(fields)
        aliases = {"array": "list", "object": "dict"}
        fields = [dict(f, type=aliases.get(f["type"], f["type"])) for f in fields]
    data["state_schema"] = fields
    nodes = []
    for nd in data.get("nodes", []):
        if not isinstance(nd, dict):
            nodes.append(nd)
            continue
        if "config" in nd and set(nd) - {"name", "kind", "config"}:
            raise ValueError(f"nodes.{nd.get('name')}: config 外存在未知字段")
        nc = builder._normalize_node_config(nd)
        if isinstance(nc.get("args"), str):
            nc["args"] = json.loads(nc["args"])
        nodes.append({"name": nd.get("name"), "kind": nd.get("kind"), "config": nc})
    data["nodes"] = nodes
    spec = WorkflowSpec.model_validate(data)
    if len(spec.nodes) > cfg.WORKFLOW_MAX_NODES:
        raise ValueError(f"nodes: 超过上限 {cfg.WORKFLOW_MAX_NODES}")
    names = [n.name for n in spec.nodes]
    if len(set(names)) != len(names) or set(names) & {"START", "END", "__start__", "__end__"}:
        raise ValueError("nodes.name: 节点名重复或使用保留名称")
    fields_by_name = {f.name: f for f in spec.state_schema}
    if len(fields_by_name) != len(spec.state_schema):
        raise ValueError("state_schema.name: 字段名重复")
    for f in spec.state_schema:
        if f.type not in TYPE_MAP or (f.reducer is not None and f.reducer not in REDUCERS):
            raise ValueError(f"state_schema.{f.name}: 非法 type/reducer")
    for n in spec.nodes:
        nc = n.config
        output = nc.output_field or {"human": "user_input", "subagent": "agent_reply", "main_agent": "agent_reply"}.get(n.kind, "output")
        if n.kind != "subgraph" and output not in fields_by_name:
            raise ValueError(f"nodes.{n.name}.config.output_field: 未声明 state 字段 {output}")
        if nc.image_ids or nc.image_ids_field:
            if n.kind not in {"llm", "subagent"}:
                raise ValueError(f"nodes.{n.name}.config.image_ids: 仅 llm/subagent 节点支持")
            if nc.image_ids_field and (nc.image_ids_field not in fields_by_name or fields_by_name[nc.image_ids_field].type != "list"):
                raise ValueError(f"nodes.{n.name}.config.image_ids_field: 必须引用 list 状态字段")
        if nc.on_error == "compensate":
            cp = nc.compensation
            if not cp or cp.get("tool_name") not in builder.tools or not isinstance(cp.get("args", {}), dict):
                raise ValueError(f"nodes.{n.name}.config.compensation: 需要有效 tool_name 与 args 对象")
        if nc.compensation and nc.on_error != "compensate":
            raise ValueError(f"nodes.{n.name}.config.compensation: 需设置 on_error=compensate")
        if n.kind == "tool" and nc.tool_name not in builder.tools:
            raise ValueError(f"nodes.{n.name}.config.tool_name: 工具不存在 {nc.tool_name}")
        if n.kind == "subagent":
            for tool in nc.tools:
                if tool not in builder.tools or tool.startswith("workflow_") or tool in {"load_skill", "unload_skill"}:
                    raise ValueError(f"nodes.{n.name}.config.tools: 工具不可用 {tool}")
        if n.kind == "subgraph":
            child = builder.manager.get_workflow(nc.sub_workflow_id)
            if child is None or not child.enabled or child.last_error:
                raise ValueError(f"nodes.{n.name}.config.sub_workflow_id: 子工作流不可用 {nc.sub_workflow_id}")
            validate_spec(child.spec, builder, child.workflow_id, (*ancestors, workflow_id))
    for i, e in enumerate(spec.edges):
        if e.src not in ["START", *names] or e.dst not in ["END", *names]:
            raise ValueError(f"edges.{i}: 悬空或非法边 {e.src}->{e.dst}")
    sources = set()
    for i, c in enumerate(spec.conditionals):
        if c.src not in names or c.src in sources:
            raise ValueError(f"conditionals.{i}.src: 非法或重复源节点 {c.src}")
        sources.add(c.src)
        if len(c.mapping) > cfg.WORKFLOW_MAX_BRANCHES:
            raise ValueError(f"conditionals.{i}.mapping: 超过分支上限 {cfg.WORKFLOW_MAX_BRANCHES}")
        if any(not k or v not in ["END", *names] for k, v in c.mapping.items()):
            raise ValueError(f"conditionals.{i}.mapping: 分支目标不存在或分支名为空")
        if c.router.kind == "state_field":
            f = fields_by_name.get(c.router.field)
            if f is None:
                raise ValueError(f"conditionals.{i}.router.field: 未声明字段 {c.router.field}")
            if f.type in {"bool", "boolean"} and not {"True", "False"} <= c.mapping.keys():
                raise ValueError(f"conditionals.{i}.mapping: bool 路由需要 True/False 分支")
    # 只保存显式配置，保留各类节点的运行时默认值。
    return spec.model_dump(exclude_unset=True) | {"spec_version": 1}
