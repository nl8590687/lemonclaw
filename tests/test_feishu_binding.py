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
飞书用户自动绑定测试

验证只绑定首个向机器人发消息的用户，后续用户不会覆盖绑定。
"""

import unittest
from unittest.mock import patch

from channels.device.feishu import (
    bind_feishu_owner_open_id,
    get_feishu_owner_open_id,
    is_feishu_owner,
)


class FeishuOwnerBindingTest(unittest.TestCase):
    @patch("channels.device.feishu.get_state", return_value="ou_first")
    def test_get_owner_open_id(self, get_state):
        self.assertEqual(get_feishu_owner_open_id(), "ou_first")
        get_state.assert_called_once_with("feishu.owner_open_id")

    @patch("channels.device.feishu.get_or_set_state", return_value="ou_first")
    def test_bind_keeps_existing_owner(self, get_or_set_state):
        self.assertEqual(bind_feishu_owner_open_id("ou_second"), "ou_first")
        get_or_set_state.assert_called_once_with("feishu.owner_open_id", "ou_second")

    @patch("channels.device.feishu.get_state", return_value="ou_first")
    @patch("channels.device.feishu.get_or_set_state")
    def test_empty_open_id_does_not_bind(self, get_or_set_state, get_state):
        self.assertEqual(bind_feishu_owner_open_id(None), "ou_first")
        get_or_set_state.assert_not_called()

    @patch("channels.device.feishu.get_feishu_owner_open_id")
    def test_given_owner_matches(self, get_owner):
        self.assertTrue(is_feishu_owner("ou_first", "ou_first"))
        get_owner.assert_not_called()

    @patch("channels.device.feishu.get_feishu_owner_open_id")
    def test_other_user_is_rejected_without_db_read(self, get_owner):
        self.assertFalse(is_feishu_owner("ou_second", "ou_first"))
        get_owner.assert_not_called()

    @patch("channels.device.feishu.get_feishu_owner_open_id", return_value=None)
    def test_user_allowed_when_not_bound_yet(self, get_owner):
        self.assertTrue(is_feishu_owner("ou_any"))

    def test_empty_open_id_is_rejected(self):
        self.assertFalse(is_feishu_owner(None, "ou_first"))


if __name__ == "__main__":
    unittest.main()
