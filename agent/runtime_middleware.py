"""Refresh model/tool bindings at call boundaries without replacing the current graph."""

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

import agent.llm
from agent.mcp import get_mcp_manager
from agent.skill import get_skill_manager
from agent.tools import create_tool_list
from config import get_global_config, runtime


class RuntimeConfigurationMiddleware(AgentMiddleware):
    def __init__(self, allowed_names=None):
        self.allowed_names = None if allowed_names is None else set(allowed_names)
        self.revision = runtime.revision
        self._live_tools = None

    def current_tools(self):
        if self.revision != runtime.revision:

            cfg = get_global_config()
            if cfg.ENABLE_SKILLS:

                manager = get_skill_manager()
                manager.max_active, manager.script_timeout = cfg.MAX_ACTIVE_SKILLS, cfg.SKILL_SCRIPT_TIMEOUT
                manager.pip_index_url, manager.npm_registry = cfg.PIP_INDEX_URL, cfg.NPM_REGISTRY
            if cfg.ENABLE_MCP:

                manager = get_mcp_manager()
                if manager:
                    manager.call_timeout = cfg.MCP_CALL_TIMEOUT
                    manager.result_max_chars = cfg.MCP_RESULT_MAX_CHARS
                    for connection in list(manager._connections.values()):
                        connection.call_timeout = cfg.MCP_CALL_TIMEOUT
                        connection.result_max_chars = cfg.MCP_RESULT_MAX_CHARS

            tools = create_tool_list()
            self._live_tools = {t.name: t for t in tools if self.allowed_names is None or t.name in self.allowed_names}
            self.revision = runtime.revision
        return self._live_tools

    def wrap_model_call(self, request, handler):
        tools = self.current_tools()
        if tools is not None:

            return handler(request.override(model=agent.llm.create_openai_llm(), tools=list(tools.values())))
        return handler(request)

    def wrap_tool_call(self, request, handler):
        tools = self.current_tools()
        if tools is not None:
            tool = tools.get(request.tool_call["name"])
            if tool is None:
                return ToolMessage(
                    content="Tool disabled by current configuration", tool_call_id=request.tool_call["id"]
                )
            return handler(request.override(tool=tool))
        return handler(request)
