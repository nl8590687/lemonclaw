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

"""
输出通道聚合测试

覆盖 FanoutOutputChannel 广播 / 异常隔离、输出通道工厂按开关装配，
以及 FeishuOutputChannel 的 open_id 回退顺序。
"""

import unittest
from unittest.mock import MagicMock, patch

from channels.out.fanout import FanoutOutputChannel
from channels.out.factory import build_output_channel


class _Recorder:
    def __init__(self):
        self.calls = []

    def write_message(self, msg, context):
        self.calls.append(("write_message", msg, context))

    def print(self, msg):
        self.calls.append(("print", msg))

    def write_tool_calling(self, tool_name, param_str):
        self.calls.append(("write_tool_calling", tool_name, param_str))

    def write_tool_result(self, output):
        self.calls.append(("write_tool_result", output))

    def write_tool_error(self, error):
        self.calls.append(("write_tool_error", error))

    def write_menu_content(self, content):
        self.calls.append(("write_menu_content", content))

    def write_system_error(self, content):
        self.calls.append(("write_system_error", content))


class FanoutOutputChannelTest(unittest.TestCase):
    def test_broadcasts_to_all_channels(self):
        first, second = _Recorder(), _Recorder()
        channel = FanoutOutputChannel([first, second])
        context = {"open_id": "ou_1"}

        channel.write_message("hello", context)
        channel.print("token")
        channel.write_tool_calling("shell", "{}")
        channel.write_tool_result("ok")
        error = ValueError("boom")
        channel.write_tool_error(error)
        channel.write_menu_content("menu")
        channel.write_system_error("error")

        for recorder in (first, second):
            self.assertEqual(
                [call[0] for call in recorder.calls],
                [
                    "write_message",
                    "print",
                    "write_tool_calling",
                    "write_tool_result",
                    "write_tool_error",
                    "write_menu_content",
                    "write_system_error",
                ],
            )
            self.assertEqual(recorder.calls[0], ("write_message", "hello", context))
            self.assertEqual(recorder.calls[1], ("print", "token"))
            self.assertIs(recorder.calls[4][1], error)

    def test_channel_failure_does_not_block_others(self):
        broken = _Recorder()

        def fail(*args, **kwargs):
            raise RuntimeError("channel down")

        broken.write_message = fail
        healthy = _Recorder()

        with self.assertLogs("channels.out.fanout", level="ERROR"):
            FanoutOutputChannel([broken, healthy]).write_message("hello", {})

        self.assertEqual(healthy.calls, [("write_message", "hello", {})])


class BuildOutputChannelTest(unittest.TestCase):
    @patch("channels.out.factory.get_global_config")
    @patch("channels.out.factory.FeishuOutputChannel")
    @patch("channels.out.factory.TerminalOutputChannel")
    def test_feishu_enabled_builds_both_channels(self, terminal_cls, feishu_cls, config):
        config.return_value.ENABLE_FEISHU = True

        channel = build_output_channel({"open_id": "ou_1"})

        self.assertIsInstance(channel, FanoutOutputChannel)
        self.assertEqual(len(channel.channels), 2)
        terminal_cls.assert_called_once_with()
        feishu_cls.assert_called_once_with("ou_1")

    @patch("channels.out.factory.get_global_config")
    @patch("channels.out.factory.FeishuOutputChannel")
    @patch("channels.out.factory.TerminalOutputChannel")
    def test_feishu_disabled_keeps_terminal_only(self, terminal_cls, feishu_cls, config):
        config.return_value.ENABLE_FEISHU = False

        channel = build_output_channel()

        self.assertEqual(len(channel.channels), 1)
        terminal_cls.assert_called_once_with()
        feishu_cls.assert_not_called()


class FeishuOutputChannelTest(unittest.TestCase):
    def _new_channel(self, open_id=None):
        with patch("channels.out.feishu.get_feishu_client", return_value=None), \
                patch("channels.out.feishu.FeishuMessageSender", return_value=MagicMock()):
            from channels.out.feishu import FeishuOutputChannel
            return FeishuOutputChannel(open_id=open_id)

    def test_bound_owner_has_highest_priority(self):
        channel = self._new_channel(open_id="ou_explicit")
        with patch("channels.out.feishu.get_feishu_owner_open_id", return_value="ou_owner"):
            self.assertEqual(channel._resolve_open_id({"open_id": "ou_ctx"}), "ou_owner")

    def test_context_open_id_used_when_not_bound_yet(self):
        channel = self._new_channel()
        with patch("channels.out.feishu.get_feishu_owner_open_id", return_value=None):
            self.assertEqual(channel._resolve_open_id({"open_id": "ou_ctx"}), "ou_ctx")

    def test_explicit_open_id_used_when_not_bound_yet(self):
        channel = self._new_channel(open_id="ou_explicit")
        with patch("channels.out.feishu.get_feishu_owner_open_id", return_value=None):
            self.assertEqual(channel._resolve_open_id(None), "ou_explicit")

    def test_returns_none_when_no_recipient_available(self):
        channel = self._new_channel()
        with patch("channels.out.feishu.get_feishu_owner_open_id", return_value=None):
            self.assertIsNone(channel._resolve_open_id(None))


if __name__ == "__main__":
    unittest.main()
