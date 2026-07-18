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

from langchain_openai import ChatOpenAI

from config import get_global_config


def create_openai_llm() -> ChatOpenAI:
    """
    根据配置创建 OpenAI兼容的LLM 实例
    """
    global_config = get_global_config()
    return ChatOpenAI(
        model=global_config.MODEL_NAME,
        temperature=global_config.TEMPERATURE,
        max_tokens=global_config.MODEL_MAX_COMPLETION_TOKEN,
        streaming=True,
        stream_usage=True,
        base_url=global_config.OPENAI_BASE_URL,
        api_key=global_config.OPENAI_API_KEY,
        timeout=global_config.LLM_API_TIMEOUT,
        max_retries=10
    )
