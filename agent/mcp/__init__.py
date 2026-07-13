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
MCP 业务层

``MCPManager`` 是唯一的 MCP 业务入口；``MCPConnection`` 只做单服务端协议传输与工具发现；
``MCPServerDAO`` 只做纯 SQL；``MCPToolWrapper`` 只做 LangChain 适配与 schema 转换；
工具与命令都经由 ``MCPManager``（或 ``AgentService`` 委托方法）访问 MCP。
"""

import logging

from agent.mcp.manager import MCPManager  # noqa: F401

logger = logging.getLogger(__name__)

_global_mcp_manager: MCPManager | None = None


def get_mcp_manager() -> MCPManager | None:
    """获取全局 ``MCPManager`` 单例；初始化失败降级返回 None（AgentService 视同未启用）。

    Returns:
        全局唯一的 MCPManager 实例，或 None（初始化失败时）
    """
    global _global_mcp_manager
    if _global_mcp_manager is None:
        try:
            _global_mcp_manager = MCPManager()
        except Exception as e:
            logger.warning(f"MCPManager 初始化失败，降级为未启用: {e}")
            _global_mcp_manager = None
    return _global_mcp_manager


__all__ = ["MCPManager", "get_mcp_manager"]
