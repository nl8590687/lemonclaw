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

'''CLI 入口测试。'''

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from main import main


class MainCliTest(unittest.TestCase):
    def test_help_exits_zero(self):
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(['--help'])

        self.assertEqual(raised.exception.code, 0)
        self.assertIn('--version', output.getvalue())

    def test_version_exits_zero(self):
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(['--version'])

        self.assertEqual(raised.exception.code, 0)
        self.assertIn('lemonclaw', output.getvalue())

    def test_default_run_starts_sources_then_loop(self):
        calls = []
        with (
            patch('config.get_global_config', side_effect=lambda: calls.append('config')),
            patch('loop.start_event_source', side_effect=lambda: calls.append('sources')),
            patch('loop.loop_forever', side_effect=lambda: calls.append('loop')),
        ):
            main([])

        self.assertEqual(calls, ['config', 'sources', 'loop'])
