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
AI Agent for context summarization
"""

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage

from agent.llm import create_openai_llm, get_context_agent_system_prompt
from channels.out.stdout import TerminalOutputChannel


class ContextAgent:
    def __init__(self):
        self.llm = create_openai_llm()
        self.default_out_chan = TerminalOutputChannel()

    def run(self, msg_list: list[BaseMessage]) -> str:
        inner_msg_list: list[BaseMessage] = [get_context_agent_system_prompt()]
        for msg in msg_list:
            if isinstance(msg, SystemMessage):
                continue
            inner_msg_list.append(msg)
        inner_msg_list.append(HumanMessage(content="请按要求总结以上内容摘要"))
        result = self.llm.invoke(inner_msg_list)
        return result.content
