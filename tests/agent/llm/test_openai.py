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
openai llm 模块单元测试
"""

import os
import unittest
from unittest.mock import patch

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from agent.llm.openai import (
    create_openai_llm,
)


class TestCreateOpenaiLlm(unittest.TestCase):
    """
    create_openai_llm 工厂函数测试
    """

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-api-key", "OPENAI_BASE_URL": "http://test-url",
                             "MODEL_NAME": "deepseek-v4-flash", "MODEL_MAX_TOKEN": "32000"})
    def test_create_llm(self):
        """测试创建LLM"""
        llm = create_openai_llm()
        self.assertIsInstance(llm, ChatOpenAI, "LLM应该是ChatOpenAI的实例")
        self.assertEqual(llm.openai_api_base, "http://test-url")
        self.assertEqual(llm.openai_api_key.get_secret_value(), SecretStr("test-api-key").get_secret_value())
        self.assertEqual(llm.model_name, "deepseek-v4-flash")
        self.assertEqual(llm.max_tokens, 32000)
        self.assertTrue(llm.streaming)
