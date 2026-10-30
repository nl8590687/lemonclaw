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
Langchain Callback Custom
"""

from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs.llm_result import LLMResult

from channels.out.base import BaseOutChannel


class StreamingCallback(BaseCallbackHandler):
    """
    流式输出回调 + Token 统计 + 工具调用展示
    """

    def __init__(self, console: BaseOutChannel=None):
        self.console = console
        self.tokens = {
            "prompt_tokens": 0,
            "cached_prompt_tokens": 0,
            "uncached_prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "successful_requests": 0,
            "memory_tokens": 0
        }

    def on_llm_new_token(self, token: str, **kwargs):
        self.console.print(token)

    def on_llm_end(self, response: LLMResult, **kwargs):
        self.tokens["successful_requests"] += 1
        if not response.generations:
            return
        for generation_list in response.generations:
            for generation in generation_list:
                if hasattr(generation, "message") and hasattr(generation.message, "usage_metadata"):
                    usage = generation.message.usage_metadata
                    if usage:
                        self.tokens["memory_tokens"] = max(usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                                                            usage.get("total_tokens", 0))
                        input_tokens = usage.get("input_tokens", 0)
                        cache_reads = [value or 0 for key, value in (usage.get("input_token_details") or {}).items()
                                       if key.endswith("cache_read")]
                        raw_usage = generation.message.response_metadata.get("token_usage") or {}
                        cached = sum(cache_reads) if cache_reads else raw_usage.get("prompt_cache_hit_tokens", 0) or 0
                        cached = min(input_tokens, max(0, cached))
                        self.tokens["cached_prompt_tokens"] += cached
                        self.tokens["uncached_prompt_tokens"] += input_tokens - cached
                        self.tokens["prompt_tokens"] += usage.get("input_tokens", 0)
                        self.tokens["completion_tokens"] += usage.get("output_tokens", 0)
                        self.tokens["total_tokens"] += usage.get("total_tokens",
                            self.tokens["prompt_tokens"] + self.tokens["completion_tokens"])

    def on_tool_start(self, serialized: dict[str, Any], input_str: str, **kwargs):
        tool_name = serialized.get("name", "未知工具")
        if self.console:
            self.console.write_tool_calling(tool_name, input_str)

    def on_tool_end(self, output, **kwargs):
        if self.console:
            self.console.write_tool_result(output)

    def on_tool_error(self, error, **kwargs):
        self.console.write_tool_error(error)
