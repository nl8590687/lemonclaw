"""WebUI tests use a private temporary copy of the existing singleton database."""

import io
import os
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage
from pydantic import SecretStr

from config import runtime
from config.config import GlobalConfig
from channels.webui import state
from channels.webui.api import create_app


@pytest.fixture
def web(tmp_path, monkeypatch):
    import config.config as config_module
    import dao.db as db

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(db, "_global_db_path", tmp_path / "lemonclaw.db")
    monkeypatch.setattr(os, "environ", dict(os.environ))
    cfg = GlobalConfig(
        OPENAI_API_KEY="provider-secret",
        MODEL_NAME="fake",
        ENABLE_FEISHU=False,
        ENABLE_MEMORY=False,
        ENABLE_MCP=False,
        ENABLE_SKILLS=False,
        WEBUI_AUTH_KEY=SecretStr("test-owner-key"),
        FEISHU_RECEIVED_DIR=str(tmp_path / "files"),
    )
    monkeypatch.setattr(config_module, "_global_config", cfg)
    monkeypatch.setattr(runtime, "revision", 0)
    state.busy.clear()
    monkeypatch.setattr(state, "enabled", False)
    import agent.skill as skills
    import agent.workflow as workflows
    import agent.memory as memory
    import agent.mcp as mcp
    import channels.device.crontab as cron

    for module, attr in [
        (skills, "_global_skill_manager"),
        (workflows, "_workflow_manager"),
        (memory, "_global_memory_manager"),
        (mcp, "_global_mcp_manager"),
        (cron, "_manager_instance"),
    ]:
        if hasattr(module, attr):
            monkeypatch.setattr(module, attr, None)
    monkeypatch.setattr(
        state, "service", SimpleNamespace(_current_messages=lambda: [HumanMessage(content="shared history")], tools=[])
    )
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>test frontend</html>")
    (dist / "assets").mkdir()
    (dist / "assets" / "app.js").write_text("window.loaded=true")
    client = TestClient(create_app(dist), headers={"Origin": "http://testserver"})
    yield client
    state.busy.clear()


def unlock(client):
    response = client.post("/api/v1/auth/login", json={"key": "test-owner-key"})
    assert response.status_code == 200, response.text
    return response


def test_protected_context_and_static_fallback(web):
    assert web.get("/api/v1/conversation/context").status_code == 401
    assert web.get("/settings").status_code == 200
    assert web.get("/assets/missing.js").status_code == 404
    assert web.get("/api/v1/missing").status_code == 401
    response = unlock(web)
    assert "HttpOnly" in response.headers["set-cookie"]
    assert web.get("/api/v1/conversation/context").json()["messages"][0]["content"] == "shared history"
    assert web.get("/api/v1/missing").status_code == 404


def test_auth_origin_logout_and_rotation(web):
    assert (
        web.post(
            "/api/v1/auth/login", json={"key": "test-owner-key"}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert web.post("/api/v1/auth/login", json={"key": "wrong"}).status_code == 401
    assert web.post("/api/v1/auth/login", json={"key": "错误的密钥"}).status_code == 401
    unlock(web)
    assert web.patch("/api/v1/settings", json={"changes": {"WEBUI_AUTH_KEY": "new-owner-key"}}).status_code == 200
    assert web.get("/api/v1/bootstrap").status_code == 401
    assert web.post("/api/v1/auth/login", json={"key": "new-owner-key"}).status_code == 200
    assert web.post("/api/v1/auth/logout", json={}).status_code == 200
    assert web.get("/api/v1/bootstrap").status_code == 401


def test_generated_key_persisted_and_reused(web):
    cfg = runtime.get_global_config()
    cfg.WEBUI_AUTH_KEY = SecretStr("")
    from channels.webui.api import ensure_key

    key = ensure_key()
    assert len(key) >= 40
    assert key in runtime.env_path().read_text()
    assert ensure_key() == key


def test_settings_defaults_and_unknown_variables(web):
    unlock(web)
    path = runtime.env_path()
    path.write_text("# keep comment\nUNKNOWN=old\n", encoding="utf-8")
    result = web.get("/api/v1/settings").json()
    assert any(f["name"] == "TEMPERATURE" and f["default"] == 0.7 for f in result["fields"])
    assert next(f for f in result["fields"] if f["name"] == "OPENAI_API_KEY")["value"] is None
    assert result["custom"][0]["name"] == "UNKNOWN"
    response = web.patch("/api/v1/settings", json={"revision": result["revision"], "changes": {"TEMPERATURE": 0.3}})
    assert response.status_code == 200
    assert runtime.get_global_config().TEMPERATURE == 0.3
    assert "# keep comment" in path.read_text() and "UNKNOWN=old" in path.read_text()
    assert (
        web.patch(
            "/api/v1/settings", json={"revision": result["revision"], "changes": {"TEMPERATURE": 0.4}}
        ).status_code
        == 409
    )
    assert web.patch("/api/v1/settings", json={"changes": {"WEBUI_PORT": -1}}).status_code == 409
    secret = "quotes' spaces\\and\nlines#literal"
    assert web.patch("/api/v1/settings", json={"custom": True, "changes": {"MY_SKILL_KEY": secret}}).status_code == 200
    from dotenv import dotenv_values

    assert dotenv_values(path)["MY_SKILL_KEY"] == secret
    assert secret not in web.get("/api/v1/settings").text
    assert os.environ["MY_SKILL_KEY"] == secret
    assert web.patch("/api/v1/settings", json={"custom": True, "changes": {"MY_SKILL_KEY": None}}).status_code == 200
    assert "MY_SKILL_KEY" not in dotenv_values(path)


def test_request_deduplication_and_shared_session(web, monkeypatch):
    from channels.bus import get_bus

    calls = []
    monkeypatch.setattr(get_bus(), "publish", lambda **kwargs: calls.append(kwargs))
    unlock(web)
    payload = {"text": "hello", "request_id": "unique-request"}
    assert web.post("/api/v1/conversation/messages", json=payload).status_code == 202
    assert web.post("/api/v1/conversation/messages", json=payload).status_code == 202
    assert len(calls) == 1
    assert calls[0]["context"]["session_key"] == "session-default"
    assert web.get("/api/v1/requests/unique-request").json()["status"] == "queued"


def test_upload_registered_files_and_reject_corrupt_images(web):
    unlock(web)
    response = web.post(
        "/api/v1/attachments",
        content=b"hello",
        headers={"X-File-Name": "../../example.txt", "Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 200, response.text
    attachment = response.json()
    assert attachment["name"] == "example.txt"
    assert web.get("/api/v1/attachments/" + attachment["attachment_id"]).content == b"hello"
    bad = web.post(
        "/api/v1/attachments", content=b"bad image", headers={"X-File-Name": "evil.png", "Content-Type": "image/png"}
    )
    assert bad.status_code == 409


def test_cross_channel_question_single_winner(web):
    from dao.question import QuestionDAO

    unlock(web)
    store = QuestionDAO()
    store.create(
        "question-test",
        "session-default",
        dict(
            reason="confirm",
            timeout_seconds=3600,
            questions=[dict(prompt="Continue?", kind="single", options=["yes", "no"])],
        ),
        dict(source="feishu", open_id="owner"),
        "task",
    )
    a = web.post("/api/v1/questions/question-test/answers", json={"fields": {"1": ["1"]}})
    assert a.status_code == 200, a.text
    assert a.json()["status"] == "confirmed"
    b = web.post("/api/v1/questions/question-test/cancel", json={})
    assert b.json()["status"] == "confirmed"
    assert store.get("question-test")["result"]["answers"][0]["values"] == ["yes"]
    from agent.questions import actor_matches
    from channels.webui.api import OWNER

    ui_row = dict(origin=OWNER)
    assert actor_matches(ui_row, {"_event_type": "terminal"})
    assert not actor_matches(ui_row, {"source": "webui", "_webui_owner": True, "_event_type": "webhook"})


def archive(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return output.getvalue()


@pytest.mark.parametrize("name", ["../escape", "/absolute", "folder/../../escape", "C:/escape"])
def test_skill_archive_rejects_traversal(web, name):
    from channels.webui.packages import stage

    with pytest.raises(ValueError):
        stage(archive({name: "danger"}))


def test_skill_upload_only_stages_validated_package(web):
    from channels.webui.packages import stage

    package = stage(
        archive(
            {
                "demo/SKILL.md": "---\nname: demo\ndescription: Test\n---\nDo something\n",
                "demo/package.json": '{"scripts":{"postinstall":"danger"}}',
            }
        )
    )
    assert package["name"] == "demo"
    assert package["dependencies"]
    assert not Path(".lemonclaw/skills/demo").exists()


def test_configuration_multiline_replacement(web):
    runtime.save({"EXTRA": "first\nold-line"}, custom=True)
    runtime.save({"EXTRA": "second"}, custom=True)
    from dotenv import dotenv_values

    assert dotenv_values(runtime.env_path())["EXTRA"] == "second"
    assert "old-line" not in runtime.env_path().read_text()


def test_management_cron_memory_and_workflow_roundtrip(web):
    unlock(web)
    response = web.post(
        "/api/v1/manage/cron", json={"prompt": "hello", "cron_expression": "0 9 * * *", "enabled": False}
    )
    assert response.status_code == 200, response.text
    task = response.json()
    assert any(x["task_id"] == task["task_id"] for x in web.get("/api/v1/manage/cron").json())
    assert web.delete("/api/v1/manage/cron/" + task["task_id"]).json()["deleted"]
    assert (
        web.post(
            "/api/v1/manage/memory",
            json={"type": "core", "memory_type": "preference", "key": "color", "value": "green"},
        ).status_code
        == 200
    )
    assert web.get("/api/v1/manage/memory").json()["core"][0]["value"] == "green"
    assert web.delete("/api/v1/manage/memory/core:preference:color").json()["deleted"]
    spec = dict(
        state_schema=[dict(name="answer", type="str")],
        nodes=[dict(name="approval", kind="human", config=dict(question="Ready?", output_field="answer"))],
        edges=[dict(src="START", dst="approval"), dict(src="approval", dst="END")],
    )
    data = dict(name="approval", description="A human workflow", spec=spec, layout={"approval": {"x": 70, "y": 90}})
    result = web.post("/api/v1/manage/workflows", json=data)
    assert result.status_code == 200, result.text
    workflow = result.json()
    detail = web.get("/api/v1/manage/workflows/" + workflow["workflow_id"]).json()
    assert detail["layout"] == data["layout"] and detail["spec"]["nodes"][0]["kind"] == "human"
    data["version"] = workflow["version"]
    data["spec"]["nodes"][0]["config"]["question"] = "Changed"
    assert web.put("/api/v1/manage/workflows/" + workflow["workflow_id"], json=data).status_code == 200
    assert web.put("/api/v1/manage/workflows/" + workflow["workflow_id"], json=data).status_code == 409
    assert web.delete("/api/v1/manage/workflows/" + workflow["workflow_id"]).json()["deleted"]
    from agent.workflow import get_workflow_manager

    get_workflow_manager().executor.shutdown()


def test_skill_install_replace_delete_uses_same_registry(web):
    from channels.webui.packages import stage, install, delete
    from agent.skill import get_skill_manager, _get_skill_dir

    package = stage(archive({"SKILL.md": "---\nname: demo\ndescription: Example skill\n---\nInstructions\n"}))
    assert install(package["id"])["installed"]
    assert get_skill_manager().get_skill("demo") is not None
    second = stage(archive({"SKILL.md": "---\nname: demo\ndescription: Revised skill\n---\nUpdated\n"}))
    with pytest.raises(ValueError, match="explicit replacement"):
        install(second["id"])
    assert install(second["id"], replace=True)["installed"]
    assert delete("demo")["deleted"]
    assert not Path(_get_skill_dir()).joinpath("demo").exists()


def test_nested_workflow_snapshot_survives_edit_and_restart(web):
    import time
    from agent.workflow import get_workflow_manager
    from agent.workflow.manager import WorkflowManager

    manager = get_workflow_manager()
    child_spec = dict(
        state_schema=[dict(name="answer", type="str")],
        nodes=[dict(name="human", kind="human", config=dict(question="Original question", output_field="answer"))],
        edges=[dict(src="START", dst="human"), dict(src="human", dst="END")],
    )
    child = manager.define_workflow("child", "", child_spec)
    parent_spec = dict(
        state_schema=[dict(name="answer", type="str")],
        nodes=[dict(name="child", kind="subgraph", config=dict(sub_workflow_id=child.workflow_id))],
        edges=[dict(src="START", dst="child"), dict(src="child", dst="END")],
    )
    parent = manager.define_workflow("parent", "", parent_spec)
    rid, result = manager.start_run(parent.workflow_id, {"answer": ""}, {})
    assert rid, result

    def wait(owner, status):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            row = owner.dao.get_run(rid)
            if row.status in (status, "error"):
                assert row.status == status, row.error
                return row
            time.sleep(0.05)
        raise AssertionError(owner.inspect_run(rid))

    wait(manager, "paused")
    child_spec["nodes"][0]["config"]["question"] = "New question"
    manager.define_workflow("child", "", child_spec)
    from dao.webui import WebStore

    assert (
        WebStore().layout("run:" + rid)["definitions"][child.workflow_id]["spec"]["nodes"][0]["config"]["question"]
        == "Original question"
    )
    manager.executor.shutdown()
    restarted = WorkflowManager()
    try:
        assert restarted.resume_run(rid, "Approved", {})["status"] == "resuming"
        wait(restarted, "completed")
        assert WebStore().layout("nodes:" + rid)
    finally:
        restarted.executor.shutdown()


def test_parallel_wait_all_join_is_executed_once(web):
    import time
    from types import SimpleNamespace
    from langgraph.checkpoint.memory import MemorySaver
    from langchain_core.tools import tool
    from agent.workflow.builder import WorkflowBuilder

    @tool
    def echo(value: str) -> str:
        """Return a value, delaying one parallel branch."""
        if value == "slow":
            time.sleep(0.1)
        return value

    calls = []

    @tool
    def joined() -> str:
        """Run after both branches."""
        calls.append(1)
        return "joined"

    spec = dict(
        state_schema=[dict(name=x, type="str") for x in ["a", "b", "result"]],
        nodes=[
            dict(name="fast", kind="tool", config=dict(tool_name="echo", args={"value": "fast"}, output_field="a")),
            dict(name="slow", kind="tool", config=dict(tool_name="echo", args={"value": "slow"}, output_field="b")),
            dict(name="join", kind="tool", config=dict(tool_name="joined", output_field="result")),
        ],
        edges=[
            dict(src="START", dst="fast"),
            dict(src="START", dst="slow"),
            dict(src=["fast", "slow"], dst="join"),
            dict(src="join", dst="END"),
        ],
    )
    wf = SimpleNamespace(spec=spec, workflow_id="parallel", version=1)
    graph = WorkflowBuilder(None, {"echo": echo, "joined": joined}, MemorySaver(), None).compile(wf)
    result = graph.invoke({}, {"configurable": {"thread_id": "parallel-join"}})
    assert result == {"a": "fast", "b": "slow", "result": "joined"}
    assert calls == [1]


def test_live_model_configuration_changes_at_next_call(web, monkeypatch):
    from agent.runtime_middleware import RuntimeConfigurationMiddleware
    from agent.agent import _create_agent
    from langchain_core.tools import tool
    from langchain_core.messages import AIMessage, HumanMessage
    from langgraph.checkpoint.memory import MemorySaver
    from tests.test_checkpoint import FakeModel

    @tool
    def change_temperature() -> str:
        """Update configuration during a model turn."""
        runtime.save({"TEMPERATURE": 0.2})
        return "updated"

    old = FakeModel(
        responses=[
            AIMessage(content="", tool_calls=[{"name": "change_temperature", "args": {}, "id": "settings1"}]),
            AIMessage(content="old model"),
        ]
    )
    fresh = FakeModel(responses=[AIMessage(content="new model")])

    def factory():
        assert runtime.get_global_config().TEMPERATURE == 0.2
        return fresh

    monkeypatch.setattr("agent.llm.create_openai_llm", factory)
    graph = _create_agent(
        old, [change_temperature], "System", MemorySaver(), middleware=[RuntimeConfigurationMiddleware()]
    )
    result = graph.invoke(
        {"messages": [HumanMessage(content="Update and continue")]}, {"configurable": {"thread_id": "live-update"}}
    )
    assert result["messages"][-1].content == "new model"
    assert [m.content for m in result["messages"] if m.type == "tool"] == ["updated"]


def test_unstarted_request_recovery_and_changed_id_rejection(web, monkeypatch):
    from dao.webui import WebStore
    from channels.bus import get_bus

    calls = []
    monkeypatch.setattr(get_bus(), "publish", lambda **kwargs: calls.append(kwargs))
    store = WebStore()
    payload = {"text": "not started", "attachments": []}
    assert store.create_request("recover-me", payload)
    state.recover_requests()
    assert len(calls) == 1 and calls[0]["context"]["request_id"] == "recover-me"
    assert store.claim("recover-me")
    assert not store.claim("recover-me")
    state.recover_requests()
    assert len(calls) == 1
    assert store.request("recover-me")["status"] == "interrupted"
    with pytest.raises(ValueError, match="different message"):
        store.create_request("recover-me", {"text": "changed"})


def test_mcp_configuration_preserves_hidden_credentials(web, monkeypatch):
    from agent.mcp import get_mcp_manager

    manager = get_mcp_manager()
    monkeypatch.setattr(manager, "connect", lambda server_id: (True, ""))
    unlock(web)
    url = "/api/v1/manage/mcp"
    revision = web.get(url).json()["revision"]
    value = {
        "transport": "stdio",
        "command": "node",
        "args": ["service.js"],
        "env": {"API_KEY": "mcp-hidden-secret"},
        "auto_connect": False,
    }
    response = web.post(url + "/demo", json={"revision": revision, "config": value})
    assert response.status_code == 200, response.text
    view = web.get(url)
    assert "mcp-hidden-secret" not in view.text
    revision = view.json()["revision"]
    assert (
        web.put(
            url + "/demo",
            json={
                "revision": revision,
                "config": {"transport": "stdio", "command": "node", "args": ["new.js"], "auto_connect": False},
            },
        ).status_code
        == 200
    )
    assert manager._load_mcp_json()["demo"]["env"]["API_KEY"] == "mcp-hidden-secret"
    current = web.get(url).json()["revision"]
    assert web.request("DELETE", url + "/demo", json={"revision": revision}).status_code == 409
    assert web.request("DELETE", url + "/demo", json={"revision": current}).json()["saved"]
    assert manager._load_mcp_json() == {}


def test_disabled_feishu_uses_web_question_without_stale_client(web, monkeypatch):
    from unittest.mock import MagicMock
    from agent.agent import AgentService
    from dao.question import QuestionDAO
    from channels.webui.api import OWNER

    owner = MagicMock(return_value="existing-owner")
    client = MagicMock()
    monkeypatch.setattr(state, "enabled", True)
    monkeypatch.setattr("channels.device.feishu.get_feishu_owner_open_id", owner)
    monkeypatch.setattr("channels.device.feishu.get_feishu_client", client)
    store = QuestionDAO()
    store.create(
        "disabled-feishu-question",
        "session-default",
        dict(
            reason="Confirm",
            timeout_seconds=3600,
            questions=[dict(prompt="Continue?", kind="single", options=["yes", "no"])],
        ),
        OWNER,
        "tool",
    )
    service = object.__new__(AgentService)
    service.questions = store
    output = MagicMock()
    service._present_question(store.get("disabled-feishu-question"), output)
    owner.assert_not_called()
    client.assert_not_called()
    output.write_message.assert_called_once()
    assert store.get("disabled-feishu-question")["presented"]
