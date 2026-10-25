# Copyright 2026 LemonClaw Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""飞书文件发送工具测试。"""

import json
import os
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

import agent.tools as tools_pkg
import agent.tools.feishu_tool as feishu_tool
from agent.tools.feishu_tool import FeishuSendFileTool, feishu_enabled
from channels.device import feishu as feishu_module


class _FakeSender:
    def __init__(self):
        self.calls = []

    def send_file(self, path, receive_id, receive_id_type):
        self.calls.append((path, receive_id, receive_id_type))
        return {"message_id": "om_sent", "msg_type": "file"}


@pytest.fixture
def safe_root(tmp_path):
    return tmp_path


def _tool(monkeypatch, safe_root, max_mb=1):
    sender = _FakeSender()
    monkeypatch.setattr(feishu_tool, "_create_sender", lambda: sender)
    monkeypatch.setattr(feishu_tool, "get_feishu_owner_open_id", lambda: "ou_owner")
    monkeypatch.setattr(
        feishu_tool,
        "get_global_config",
        lambda: SimpleNamespace(FEISHU_MAX_SEND_FILE_MB=max_mb),
    )
    return FeishuSendFileTool([str(safe_root)]), sender


def test_send_file_within_safe_dir(monkeypatch, safe_root):
    target = safe_root / "report.pdf"
    target.write_bytes(b"demo")
    tool, sender = _tool(monkeypatch, safe_root)

    result = json.loads(tool._run(path=str(target)))

    assert result["success"] is True
    assert result["receiver"] == {"id": "ou_owner", "id_type": "open_id"}
    assert sender.calls == [(str(target.resolve()), "ou_owner", "open_id")]


def test_send_file_outside_safe_dir_rejected(monkeypatch, safe_root, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    tool, sender = _tool(monkeypatch, safe_root)

    result = json.loads(tool._run(path=str(outside)))

    assert result["success"] is False
    assert result["code"] == "unsafe_path"
    assert sender.calls == []


def test_send_file_symlink_rejected(monkeypatch, safe_root):
    target = safe_root / "real.txt"
    target.write_text("demo", encoding="utf-8")
    link = safe_root / "link.txt"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不支持创建符号链接")
    tool, sender = _tool(monkeypatch, safe_root)

    result = json.loads(tool._run(path=str(link)))

    assert result["success"] is False
    assert result["code"] == "unsafe_path"
    assert sender.calls == []


def test_send_file_too_large_rejected(monkeypatch, safe_root):
    target = safe_root / "big.bin"
    target.write_bytes(b"x" * (2 * 1024 * 1024))
    tool, sender = _tool(monkeypatch, safe_root, max_mb=1)

    result = json.loads(tool._run(path=str(target)))

    assert result["success"] is False
    assert result["code"] == "file_too_large"
    assert sender.calls == []


def test_send_file_reports_sender_failure(monkeypatch, safe_root):
    target = safe_root / "report.pdf"
    target.write_bytes(b"demo")
    tool, _ = _tool(monkeypatch, safe_root)

    class _FailingSender:
        def send_file(self, *args, **kwargs):
            raise RuntimeError("feishu down")

    monkeypatch.setattr(feishu_tool, "_create_sender", lambda: _FailingSender())
    result = json.loads(tool._run(path=str(target)))

    assert result["success"] is False
    assert result["code"] == "send_failed"


def test_send_file_rejects_empty_file(monkeypatch, safe_root):
    target = safe_root / "empty.txt"
    target.write_bytes(b"")
    tool, sender = _tool(monkeypatch, safe_root)

    result = json.loads(tool._run(path=str(target)))

    assert result["success"] is False
    assert result["code"] == "file_empty"
    assert sender.calls == []


def test_sensitive_file_rejected(monkeypatch, safe_root):
    target = safe_root / ".env"
    target.write_text("OPENAI_API_KEY=secret", encoding="utf-8")
    tool, sender = _tool(monkeypatch, safe_root)

    result = json.loads(tool._run(path=str(target)))

    assert result["success"] is False
    assert result["code"] == "sensitive_path"
    assert sender.calls == []


def test_feishu_enabled_requires_complete_config():
    assert feishu_enabled(SimpleNamespace(
        ENABLE_FEISHU=True, FEISHU_APP_ID="cli_x", FEISHU_APP_SECRET=SecretStr("sec")
    ))
    assert not feishu_enabled(SimpleNamespace(
        ENABLE_FEISHU=False, FEISHU_APP_ID="cli_x", FEISHU_APP_SECRET=SecretStr("sec")
    ))
    assert not feishu_enabled(SimpleNamespace(
        ENABLE_FEISHU=True, FEISHU_APP_ID="", FEISHU_APP_SECRET=SecretStr("sec")
    ))
    assert not feishu_enabled(SimpleNamespace(
        ENABLE_FEISHU=True, FEISHU_APP_ID="cli_x", FEISHU_APP_SECRET=SecretStr("")
    ))


def _stub_tool_factories(monkeypatch):
    for name in (
        "create_time_tool", "create_http_request_tool", "create_web_fetch_tool",
        "create_git_tool", "create_sleep_tool", "create_file_list_query_tool",
        "create_read_file_tool", "create_write_file_tool", "create_edit_file_tool",
        "create_grep_tool", "create_glob_tool",
    ):
        monkeypatch.setattr(tools_pkg, name, lambda *a, **k: object())
    monkeypatch.setattr(tools_pkg, "create_cron_tools", lambda *a, **k: [])
    monkeypatch.setattr(tools_pkg, "get_cron_manager", lambda: None)


def _feature_config(enabled: bool):
    return SimpleNamespace(
        FILE_SAFE_DIRS=".",
        BOCHA_API_KEY=None,
        EMAIL_SMTP_SERVER=None,
        EMAIL_SMTP_USERNAME=None,
        EMAIL_SMTP_PASSWORD=None,
        ENABLE_BASH_TOOL=False,
        ENABLE_MEMORY=False,
        ENABLE_SKILLS=False,
        ENABLE_SKILL_SCRIPT=False,
        ENABLE_MCP=False,
        ENABLE_WORKFLOW=False,
        ENABLE_FEISHU=enabled,
        FEISHU_APP_ID="cli_x" if enabled else "",
        FEISHU_APP_SECRET=SecretStr("sec" if enabled else ""),
    )


def test_tool_registered_when_feishu_enabled(monkeypatch):
    _stub_tool_factories(monkeypatch)
    monkeypatch.setattr(tools_pkg, "get_global_config", lambda: _feature_config(True))

    result = tools_pkg.create_tool_list()

    assert any(isinstance(tool, FeishuSendFileTool) for tool in result)


def test_tool_not_registered_when_feishu_disabled(monkeypatch):
    _stub_tool_factories(monkeypatch)
    monkeypatch.setattr(tools_pkg, "get_global_config", lambda: _feature_config(False))

    result = tools_pkg.create_tool_list()

    assert not any(isinstance(tool, FeishuSendFileTool) for tool in result)


def _bare_sender():
    return object.__new__(feishu_module.FeishuMessageSender)


def _sparse_file(path, size):
    with open(path, "wb") as file_obj:
        file_obj.truncate(size)
    return path


def test_upload_image_rejects_empty_file(tmp_path):
    target = _sparse_file(tmp_path / "empty.png", 0)

    with pytest.raises(RuntimeError, match="空图片"):
        _bare_sender().upload_image(str(target))


def test_upload_image_rejects_oversized_file(tmp_path):
    target = _sparse_file(tmp_path / "big.png", 10 * 1024 * 1024 + 1)

    with pytest.raises(RuntimeError, match="10MB"):
        _bare_sender().upload_image(str(target))


def test_upload_file_rejects_empty_and_oversized(tmp_path):
    sender = _bare_sender()

    with pytest.raises(RuntimeError, match="空文件"):
        sender.upload_file(str(_sparse_file(tmp_path / "empty.bin", 0)))
    with pytest.raises(RuntimeError, match="30MB"):
        sender.upload_file(str(_sparse_file(tmp_path / "big.bin", 30 * 1024 * 1024 + 1)))


def _stub_sender(monkeypatch):
    sender = _bare_sender()
    sent = {}

    def fake_upload_file(path):
        return "file_key_demo"

    def fake_upload_image(path):
        return "image_key_demo"

    def fake_send_message(receive_id, msg_type, content, receive_id_type):
        sent["msg_type"] = msg_type
        sent["content"] = json.loads(content)
        return True, "om_demo", None

    monkeypatch.setattr(sender, "upload_file", fake_upload_file)
    monkeypatch.setattr(sender, "upload_image", fake_upload_image)
    monkeypatch.setattr(sender, "_send_message", fake_send_message)
    return sender, sent


def test_send_file_uses_official_audio_and_media_payload(monkeypatch, tmp_path):
    audio = _sparse_file(tmp_path / "voice.opus", 4)
    video = _sparse_file(tmp_path / "clip.mp4", 4)
    sender, sent = _stub_sender(monkeypatch)

    sender.send_file(str(audio), "ou_demo")
    assert sent["msg_type"] == "audio"
    assert sent["content"] == {"file_key": "file_key_demo"}

    sender.send_file(str(video), "ou_demo")
    assert sent["msg_type"] == "media"
    assert sent["content"] == {"file_key": "file_key_demo"}


def test_send_file_sends_heic_as_image(monkeypatch, tmp_path):
    target = _sparse_file(tmp_path / "photo.heic", 4)
    sender, sent = _stub_sender(monkeypatch)

    result = sender.send_file(str(target), "ou_demo")

    assert sent["msg_type"] == "image"
    assert sent["content"] == {"image_key": "image_key_demo"}
    assert result["degraded"] is False


def test_send_file_degrades_oversized_image_to_file(monkeypatch, tmp_path):
    target = _sparse_file(tmp_path / "huge.png", 10 * 1024 * 1024 + 1)
    sender, sent = _stub_sender(monkeypatch)

    result = sender.send_file(str(target), "ou_demo")

    assert sent["msg_type"] == "file"
    assert sent["content"] == {"file_key": "file_key_demo"}
    assert result["degraded"] is True
