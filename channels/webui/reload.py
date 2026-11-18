"""Refresh resources at an idle boundary, preserving the single Agent checkpoint."""

from config import get_global_config


def resource_snapshot():
    cfg = get_global_config()
    from config.runtime import plain

    return {
        prefix: {
            name: plain(getattr(cfg, name))
            for name in getattr(type(cfg), "model_fields", vars(cfg))
            if name.startswith(prefix) or name == "ENABLE_" + prefix.rstrip("_")
        }
        for prefix in ("FEISHU_", "WEBHOOK_", "MCP_")
    }


def refresh_agent(service):
    from agent.agent import _create_agent
    from agent.llm import create_openai_llm, get_system_prompt
    from agent.skill import get_skill_manager
    from agent.mcp import get_mcp_manager
    from agent.memory import get_memory_manager
    from agent.workflow import get_workflow_manager

    cfg = get_global_config()
    previous = getattr(service, "_web_resources", {})
    current = resource_snapshot()
    service.llm = create_openai_llm()
    service.memory = get_memory_manager() if cfg.ENABLE_MEMORY else None
    service.skill_manager = get_skill_manager() if cfg.ENABLE_SKILLS else None
    if service.skill_manager:
        sm = service.skill_manager
        sm.max_active = cfg.MAX_ACTIVE_SKILLS
        sm.script_timeout = cfg.SKILL_SCRIPT_TIMEOUT
        sm.pip_index_url, sm.npm_registry = cfg.PIP_INDEX_URL, cfg.NPM_REGISTRY
    if not cfg.ENABLE_MCP and service.mcp_manager is not None:
        service.mcp_manager.close(preserve_active=True)
    service.mcp_manager = get_mcp_manager() if cfg.ENABLE_MCP else None
    if service.mcp_manager:
        mm = service.mcp_manager
        mm.connect_timeout, mm.call_timeout = cfg.MCP_CONNECT_TIMEOUT, cfg.MCP_CALL_TIMEOUT
        mm.max_tools, mm.result_max_chars = cfg.MCP_MAX_TOOLS, cfg.MCP_RESULT_MAX_CHARS
        if previous.get("MCP_") != current["MCP_"]:
            mm.reload(preserve_active=True)
    service.workflow_manager = get_workflow_manager() if cfg.ENABLE_WORKFLOW else None
    if service.workflow_manager:
        service.workflow_manager.llm = service.llm
        service.workflow_manager._tools_dict = None
        service.workflow_manager._graph_cache.clear()
        service.workflow_manager.runner.recursion_limit = cfg.WORKFLOW_RECURSION_LIMIT
        service.workflow_manager.runner.result_max_chars = cfg.WORKFLOW_RESULT_MAX_CHARS
        service.workflow_manager.executor.resize(cfg.WORKFLOW_WORKER_POOL_SIZE)
    service.tools = service._create_tool_list()
    service.agent = _create_agent(
        service.llm, service.tools, get_system_prompt(), service.checkpointer, middleware=service._build_middleware()
    )
    for attr, field in [
        ("max_iterations", "AGENT_REACT_MAX_ITERATIONS"),
        ("min_full_messages", "CONTEXT_MIN_FULL_MESSAGES"),
        ("tool_max_chars", "CONTEXT_TOOL_MAX_CHARS"),
        ("model_context_length", "MODEL_CONTEXT_LENGTH"),
        ("model_max_tokens", "MODEL_MAX_COMPLETION_TOKEN"),
    ]:
        setattr(service, attr, getattr(cfg, field))
    # Only restart channel resources at this safe boundary; terminal/Cron remain intact.
    import loop
    from channels.ins import WebhookInput, FeishuInput

    for cls, enabled, prefix in [
        (WebhookInput, cfg.ENABLE_WEBHOOK, "WEBHOOK_"),
        (FeishuInput, cfg.ENABLE_FEISHU, "FEISHU_"),
    ]:
        if previous.get(prefix) == current[prefix]:
            continue
        for source in list(loop._event_sources):
            if isinstance(source, cls):
                device = getattr(source, "webhook_server", None) or getattr(source, "feishu_client", None)
                if device:
                    device.stop()
                source.stop()
                loop._event_sources.remove(source)
        if not enabled and prefix == "FEISHU_":
            from channels.device.feishu import set_feishu_client

            set_feishu_client(None)
        if enabled:
            source = cls()
            source.start()
            loop._event_sources.append(source)

    service._web_resources = current
