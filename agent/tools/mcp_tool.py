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

"""MCP 工具注册入口（从 ``agent.mcp.tools`` 重导出，保持与其它工具模块注册对称）"""

from agent.mcp.tools import MCPToolWrapper, create_mcp_tools  # noqa: F401

__all__ = ["create_mcp_tools", "MCPToolWrapper"]
