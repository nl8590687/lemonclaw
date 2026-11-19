"""Management actions reuse existing managers and validators."""

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict

from fastapi import HTTPException

from agent.mcp import get_mcp_manager
from agent.memory import get_memory_manager
from agent.skill import get_skill_manager
from agent.workflow import get_workflow_manager
from agent.workflow.spec import NodeConfig, WorkflowSpec, validate_spec
from channels.device.crontab import get_cron_manager, parse_cron
from channels.webui import state
from channels.webui.packages import delete
from config import get_global_config
from config.runtime import touch
from dao.db import get_connection, get_db_path
from dao.webui import WebStore


def workflow_references(wid):

    manager = get_workflow_manager()
    if manager is None:
        return []
    refs = [
        w.name
        for w in manager.list_workflows()
        if w.workflow_id != wid
        and any(n.get("config", {}).get("sub_workflow_id") == wid for n in w.spec.get("nodes", []))
    ]
    for run in manager.list_runs(status="active", limit=10000):
        if wid in WebStore().layout("run:" + run.run_id).get("definitions", {}):
            refs.append(run.run_id)
    refs += [x.task_id for x in get_cron_manager().list_tasks() if (x.metadata or {}).get("workflow_id") == wid]
    return refs


def operation(kind, item_id, method, data):

    if kind == "catalog":

        tools = state.service.tools if state.service else []
        tools = list(tools.values()) if isinstance(tools, dict) else list(tools)
        tool_catalog = []
        for tool in tools:
            schema = tool.tool_call_schema
            tool_catalog.append(dict(
                name=tool.name,
                description=tool.description,
                schema=schema if isinstance(schema, dict) else schema.model_json_schema(),
            ))
        return dict(
            tools=tool_catalog,
            node_schema=NodeConfig.model_json_schema(),
            workflow_schema=WorkflowSpec.model_json_schema(),
            skills=[s.to_dict() for s in get_skill_manager().list_skills()],
        )
    if kind == "workflows":

        manager = get_workflow_manager()
        if manager is None:
            raise ValueError("Enable workflows in settings first")
        if method == "GET":
            if not item_id:
                return [w.to_dict() for w in manager.list_workflows()]
            wf = manager.get_workflow(item_id)
            if not wf:
                raise HTTPException(404)
            return dict(wf.to_dict(), layout=WebStore().layout(wf.workflow_id))
        if method == "DELETE":
            refs = workflow_references(item_id)
            if refs:
                raise ValueError("Workflow is referenced by: " + ", ".join(refs))
            ok, message = manager.delete_workflow(item_id)
            if not ok:
                raise ValueError(message)
            return dict(deleted=True)
        if data.get("action") == "run":
            rid, result = manager.start_run(
                item_id, data.get("input", {}), dict(source="webui", session_key="session-default")
            )
            if not rid:
                raise ValueError(str(result))
            return dict(run_id=rid, **result)
        current = manager.get_workflow(item_id) if item_id else None
        if current and data.get("version") != current.version:
            raise ValueError("Workflow version conflict; refresh")
        spec = validate_spec(data["spec"], manager._make_builder(), item_id or data["name"])
        name = data.get("name", current.name if current else "").strip()
        if not name:
            raise ValueError("Name is required")
        if current:
            duplicate = manager.dao.get_workflow_by_name(name)
            if duplicate and duplicate.workflow_id != current.workflow_id:
                raise ValueError("Name already exists")
            current.name, current.spec = name, spec
            current.description = data.get("description", "")
            current.enabled = bool(data.get("enabled", current.enabled))
            current.version += 1
            current.last_error = None
            manager._make_builder().compile(current)
            manager.dao.upsert_workflow(current)
            manager.reload_workflow(current.workflow_id)
            wf = current
        else:
            if manager.dao.get_workflow_by_name(name):
                raise ValueError("Workflow already exists")
            wf = manager.define_workflow(name, data.get("description", ""), spec)
            if wf.last_error:
                raise ValueError(wf.last_error)
        if not current and "enabled" in data:
            wf.enabled = bool(data["enabled"])
            manager.dao.upsert_workflow(wf)
        WebStore().layout(wf.workflow_id, data.get("layout", {}))
        return wf.to_dict()
    if kind == "runs":
        manager = get_workflow_manager()
        if manager is None:
            raise ValueError("Enable workflows in settings first")
        if method == "GET":
            if not item_id:
                return [x.to_dict() for x in manager.list_runs(limit=100)]
            info = manager.inspect_run(item_id)
            if not info:
                raise HTTPException(404)
            return dict(
                run=info, snapshot=WebStore().layout("run:" + item_id), nodes=WebStore().layout("nodes:" + item_id)
            )
        if data.get("action") == "cancel":
            ok, message = manager.cancel_run(item_id)
            if not ok:
                raise ValueError(message)
            return {"cancelled": True}
        return manager.resume_run(item_id, data.get("value"), dict(source="webui", session_key="session-default"))
    if kind == "cron":
        manager = get_cron_manager()
        if method == "GET":
            tasks = manager.list_tasks()

            return [dict(x.to_dict(), next_run=str(parse_cron(x.cron_expression).next_run())) for x in tasks]
        if method == "DELETE":
            return dict(deleted=manager.delete_task(item_id))
        args = {k: data[k] for k in ("prompt", "cron_expression", "enabled", "metadata") if k in data}
        wid = args.get("metadata", {}).get("workflow_id")
        if wid and (get_workflow_manager() is None or not get_workflow_manager().get_workflow(wid)):
            raise ValueError("Workflow does not exist")
        task = manager.update_task(item_id, **args) if item_id else manager.create_task(**args)
        if not task:
            raise HTTPException(404)
        return task.to_dict()
    if kind == "mcp":

        path = get_db_path().parent / "mcp.json"
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or any(not isinstance(value, dict) for value in raw.values()):
                raise ValueError("MCP configuration must contain server objects")
        manager = get_mcp_manager()
        if manager is None:
            raise ValueError("MCP manager is unavailable")
        config = manager._load_mcp_json()
        revision = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        if method == "GET":
            return dict(
                revision=revision,
                servers=[
                    dict(
                        x.to_dict(),
                        headers={},
                        config={
                            k: v for k, v in config.get(x.server_id, {}).items() if k not in ("headers", "env", "auth")
                        },
                        tools=[dict(name=t.name, description=t.description) for t in manager.list_tools(x.server_id)],
                    )
                    for x in manager.list_servers()
                ],
            )
        if data.get("action") in ("enable", "disable", "reconnect"):

            if data["action"] != "disable" and not get_global_config().ENABLE_MCP:
                raise ValueError("Enable MCP in settings before connecting")
            result = getattr(manager, data["action"] + ("_server" if data["action"] != "reconnect" else ""))(
                item_id, preserve_active=True
            )
            if isinstance(result, tuple) and not result[0]:
                raise ValueError(result[1])

            touch()
            return {"result": result}
        if data.get("revision") != revision:
            raise ValueError("MCP configuration conflict; refresh")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", item_id):
            raise ValueError("Invalid server ID")
        if method == "DELETE":
            for wf in get_workflow_manager().list_workflows():
                if "mcp__" + item_id + "__" in json.dumps(wf.spec):
                    raise ValueError("Server referenced by workflow: " + wf.name)
            config.pop(item_id, None)
        else:
            value = data["config"]
            if not isinstance(value, dict) or value.get("transport", "http") not in (
                "http",
                "sse",
                "stdio",
                "streamable_http",
            ):
                raise ValueError("Invalid transport")
            previous = config.get(item_id, {})
            for sensitive in ("headers", "env", "auth"):
                if sensitive not in value and sensitive in previous:
                    value[sensitive] = previous[sensitive]
            if value.get("transport") == "stdio":
                if not value.get("command"):
                    raise ValueError("stdio command required")
            elif not str(value.get("url", "")).startswith(("https://", "http://")):
                raise ValueError("HTTP URL required")
            config[item_id] = value
        path = manager.config_path
        fd, tmp = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        manager.reload(preserve_active=True)

        touch()
        return dict(saved=True)
    if kind == "skills":
        manager = get_skill_manager()
        if method == "GET":
            return [
                dict(x.to_dict(), dependencies=manager.deps_status(x.name), active=manager.is_active(x.name))
                for x in manager.list_skills()
            ]
        if method == "DELETE":

            return delete(item_id)
        action = data.get("action")
        if action not in ("enable", "disable", "reload", "setup_deps", "unload_skill"):
            raise ValueError("Unknown action")
        return dict(result=getattr(manager, action)(item_id) if action != "reload" else manager.reload())
    if kind == "memory":

        manager = get_memory_manager()
        if method == "GET":
            return dict(
                core=[asdict(x) for x in manager.list_core_memory()],
                chunks=[asdict(x) for x in manager.list_chunks(limit=200)],
            )
        if method == "DELETE":
            if item_id.startswith("core:"):
                _, memory_type, key = item_id.split(":", 2)
                return dict(deleted=manager.forget(memory_type, key))
            return dict(deleted=manager.delete_chunk(int(item_id)))
        if data.get("type") == "core":
            return dict(
                saved=manager.remember(data["key"], data["value"], data["memory_type"], data.get("description", ""))
            )
        if item_id:

            with get_connection() as c:
                c.execute(
                    "UPDATE memory_chunks SET title=?,content=? WHERE id=?",
                    (data["title"], data["content"], int(item_id)),
                )
            manager._load_chunks_to_searcher()
            return dict(saved=True)
        return dict(saved=manager.add_chunk(data["chunk_type"], data["title"], data["content"]))
    raise HTTPException(404)
