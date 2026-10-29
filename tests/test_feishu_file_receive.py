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

"""飞书文件/媒体接收与延迟触发测试。"""

import json
from types import SimpleNamespace

import pytest

import channels.device.feishu as feishu
from agent.agent import format_attachment_message


class _FakeSender:
    def __init__(self, data=b"demo-bytes", filename=None, error=None):
        self.data = data
        self.filename = filename
        self.error = error
        self.calls = []

    def download_message_resource(self, message_id, file_key, message_type):
        self.calls.append((message_id, file_key, message_type))
        return self.data, self.filename, self.error


def _event(message_type, content, *, open_id="ou_1", chat_id="oc_1",
           chat_type="p2p", message_id="om_1"):
    sender = SimpleNamespace(
        sender_id=SimpleNamespace(open_id=open_id, union_id="un_1", user_id="uid_1")
    )
    message = SimpleNamespace(
        message_type=message_type,
        content=json.dumps(content, ensure_ascii=False),
        message_id=message_id,
        chat_id=chat_id,
        chat_type=chat_type,
        mentions=[],
    )
    return SimpleNamespace(event=SimpleNamespace(sender=sender, message=message))


@pytest.fixture
def client(tmp_path, monkeypatch):
    received = tmp_path / "received"
    received.mkdir(parents=True, exist_ok=True)
    store = {}
    monkeypatch.setattr(feishu, "received_dir", lambda: received)
    monkeypatch.setattr(feishu, "get_state", lambda key: store.get(key))
    monkeypatch.setattr(
        feishu, "set_state", lambda key, value: store.__setitem__(key, value)
    )
    monkeypatch.setattr(
        feishu, "delete_state", lambda key: store.pop(key, None)
    )
    monkeypatch.setattr(feishu, "bind_feishu_owner_open_id", lambda open_id: "ou_1")
    monkeypatch.setattr(feishu, "is_feishu_owner", lambda open_id, owner=None: True)

    calls = []
    instance = feishu.FeishuClient(
        app_id="cli_x", app_secret="sec", on_message=lambda *args: calls.append(args)
    )
    instance._sender = _FakeSender(filename="报告.pdf")
    instance.received = received
    instance.store = store
    instance.calls = calls
    return instance


def test_file_message_waits_for_text(client):
    client._handle_message(_event("file", {"file_key": "fk_1", "file_name": "报告.pdf"}))

    assert client.calls == []
    files = list(client.received.iterdir())
    assert len(files) == 1
    assert files[0].read_bytes() == b"demo-bytes"
    assert client.store

    client._handle_message(_event("text", {"text": "帮我总结一下"}))

    assert len(client.calls) == 1
    text, images, context = client.calls[0]
    assert text == "帮我总结一下"
    assert images is None
    assert len(context["attachments"]) == 1
    assert context["attachments"][0]["path"] == str(files[0])
    assert context["attachments"][0]["kind"] == "文件"
    assert not client.store


def test_image_message_waits_and_merges_with_next_text(client):
    client._sender = _FakeSender(data=b"image-bytes", filename="photo.png")

    client._handle_message(_event("image", {"image_key": "img_1"}))
    assert client.calls == []

    client._handle_message(_event("text", {"text": "这张图讲了什么"}))

    assert len(client.calls) == 1
    attachments = client.calls[0][2]["attachments"]
    assert len(attachments) == 1
    assert attachments[0]["kind"] == "图片"
    assert attachments[0]["path"].endswith(".png")


def test_post_with_text_and_image_triggers_immediately(client):
    client._sender = _FakeSender(data=b"image-bytes", filename="inline.png")
    content = {
        "post": {
            "zh_cn": {
                "title": "周报",
                "content": [[
                    {"tag": "text", "text": "请查看配图"},
                    {"tag": "img", "image_key": "img_2"},
                ]],
            }
        }
    }

    client._handle_message(_event("post", content))

    assert len(client.calls) == 1
    text, _, context = client.calls[0]
    assert "周报" in text and "请查看配图" in text
    assert len(context["attachments"]) == 1
    assert context["attachments"][0]["kind"] == "图片"


def test_post_direct_shape_with_text_and_image_triggers_immediately(client):
    client._sender = _FakeSender(data=b"image-bytes", filename="inline.png")
    content = {
        "title": "周报",
        "content": [[
            {"tag": "text", "text": "请查看配图"},
            {"tag": "img", "image_key": "img_direct"},
        ]],
    }

    client._handle_message(_event("post", content))

    assert len(client.calls) == 1
    text, _, context = client.calls[0]
    assert "周报" in text and "请查看配图" in text
    assert len(context["attachments"]) == 1


def test_download_failure_does_not_break_follow_up_text(client):
    client._sender = _FakeSender(data=None, error="403 forbidden")

    client._handle_message(_event("file", {"file_key": "fk_2", "file_name": "x.pdf"}))
    assert client.calls == []

    client._handle_message(_event("text", {"text": "处理一下"}))
    assert len(client.calls) == 1
    attachment = client.calls[0][2]["attachments"][0]
    assert attachment["path"] is None
    assert "403 forbidden" in attachment["error"]


def test_non_owner_message_ignored(client, monkeypatch):
    monkeypatch.setattr(feishu, "is_feishu_owner", lambda open_id, owner=None: False)

    client._handle_message(_event("file", {"file_key": "fk_3", "file_name": "x.pdf"}))

    assert client.calls == []
    assert list(client.received.iterdir()) == []


def test_command_does_not_consume_pending_file(client):
    client._handle_message(_event("file", {"file_key": "fk_4", "file_name": "a.pdf"}))
    client._handle_message(_event("text", {"text": "/clear"}))

    assert len(client.calls) == 1
    assert client.calls[0][2]["attachments"] == []
    assert client.store

    client._handle_message(_event("text", {"text": "继续处理"}))
    assert len(client.calls) == 2
    assert len(client.calls[1][2]["attachments"]) == 1


def test_saved_filename_cannot_escape_received_dir(client):
    attachment = feishu.save_attachment(
        b"data", "../../evil.txt", "file", "om_9"
    )

    assert attachment["path"].startswith(str(client.received))
    assert (client.received / "evil.txt").exists()


def test_extract_post_content_supports_unwrapped_shape():
    text, images, media_keys = feishu.extract_post_content(
        {"zh_cn": {"content": [[
            {"tag": "text", "text": "hello"},
            {"tag": "img", "image_key": "img_9"},
        ]]}}
    )

    assert text == "hello"
    assert images == ["img_9"]
    assert media_keys == []


def test_extract_post_content_supports_direct_shape():
    text, images, media_keys = feishu.extract_post_content({
        "title": "日报",
        "content": [[
            {"tag": "text", "text": "完成"},
            {"tag": "img", "image_key": "img_1"},
        ]],
    })

    assert text == "日报 完成"
    assert images == ["img_1"]
    assert media_keys == []


def test_extract_post_content_prefers_non_empty_locale():
    text, images, media_keys = feishu.extract_post_content({
        "zh_cn": {"title": "", "content": []},
        "en_us": {"title": "Daily", "content": [[
            {"tag": "text", "text": "report"},
            {"tag": "img", "image_key": "img_en"},
        ]]},
    })

    assert text == "Daily report"
    assert images == ["img_en"]
    assert media_keys == []


def test_extract_post_content_supports_media_hr_and_at_fallback():
    text, images, media_keys = feishu.extract_post_content({
        "content": [[
            {"tag": "at", "user_id": "ou_123"},
            {"tag": "hr"},
            {"tag": "media", "file_key": "file_video_1"},
        ]],
    })

    assert "@ou_123" in text
    assert "---" in text
    assert images == []
    assert media_keys == ["file_video_1"]


def test_attachment_user_message_format():
    note = format_attachment_message([
        {"kind": "文件", "path": "/root/workspace/received/a.pdf"},
        {"kind": "图片", "path": "/root/workspace/received/b.png"},
    ])

    assert note == (
        "收到用户发来的文件：文件路径：/root/workspace/received/a.pdf\n"
        "收到用户发来的图片：文件路径：/root/workspace/received/b.png"
    )


def test_agent_run_injects_attachment_path_as_user_message():
    from langchain_core.messages import AIMessage

    from agent.agent import AgentService

    captured = {}

    class _FakeAgent:
        def invoke(self, payload, config=None, *, durability=None):
            assert durability == "sync"
            captured["messages"] = payload["messages"]
            return {"messages": [AIMessage(content="ok")]}

    class _FakeOut:
        def write_message(self, text, context=None):
            captured["reply"] = text

        def write_system_error(self, text):
            captured["error"] = text

        def print(self, *args, **kwargs):
            pass

    service = object.__new__(AgentService)
    service.default_out_chan = _FakeOut()
    service.session_id = "session-test"
    service.max_iterations = 3
    service.agent = _FakeAgent()
    service.memory = None
    service.stats = {"context_tokens": {}, "context_messages": {}}
    service._update_stats = lambda callback: None

    service.run(
        "这个图片是什么",
        {"source": "feishu"},
        service.default_out_chan,
        attachments=[{"kind": "图片", "path": "/root/workspace/received/a.jpg"}],
    )

    contents = [message.content for message in captured["messages"]]
    assert contents[0] == "收到用户发来的图片：文件路径：/root/workspace/received/a.jpg"
    assert contents[1] == "这个图片是什么"


def test_format_attachment_log_lists_paths():
    from loop import format_attachment_log

    text = format_attachment_log([
        {"kind": "图片", "path": "/root/workspace/received/a.jpg"},
        {"kind": "文件", "path": None},
        "bad",
    ])

    assert text == "图片 /root/workspace/received/a.jpg; 文件 下载失败"
