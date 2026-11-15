[Documentation](index.md) · [简体中文](../zh/configuration.md)

# ⚙️ Configuration

All configuration lives in `.lemonclaw/.env` (see `.env.example` for the full list). Main sections:

| Section | Purpose |
|---------|---------|
| `OPENAI_*` / `MODEL_*` | LLM endpoint, model, context window, temperature, timeout |
| `BOCHA_*` | Bocha web-search API (optional — enables the search tool) |
| `EMAIL_*` | SMTP server for the email tool (optional) |
| `ENABLE_BASH_TOOL` / `FILE_SAFE_DIRS` | Tool safety: shell tool on/off, file-access whitelist |
| `WEB_*` | Web/HTTP safety: private-access switch, allowlist, private writes, redirect/response-size/timeout limits |
| `AGENT_REACT_MAX_ITERATIONS` / `CONTEXT_*` | Agent behavior: max ReAct iterations, retained message count |
| `ENABLE_WEBHOOK` / `WEBHOOK_*` | Webhook server: host/port, auth token, rate limit |
| `ENABLE_FEISHU` / `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | Feishu/Lark app credentials |
| `FEISHU_RECEIVED_DIR` / `FEISHU_MAX_DOWNLOAD_MB` / `FEISHU_MAX_SEND_FILE_MB` / `FEISHU_PENDING_FILE_TTL_SECONDS` | Feishu files: receive directory (default `/root/workspace/received`), transfer size caps, pending-file TTL |
| `ENABLE_MEMORY` / `MEMORY_*` | Persistent memory: context budget, recent sessions, search chunks, auto-archive |
| `ENABLE_SKILLS` / `ENABLE_SKILL_SCRIPT` / `MAX_ACTIVE_SKILLS` / `PIP_INDEX_URL` / `NPM_REGISTRY` | Skills: master switch, script-execution gate, active-set cap, pip/npm dependency mirrors |
| `ENABLE_MCP` / `MCP_CONNECT_TIMEOUT` / `MCP_CALL_TIMEOUT` / `MCP_MAX_TOOLS` / `MCP_RESULT_MAX_CHARS` | MCP integration: master switch, connect/call timeouts, per-server tool cap, result truncation |
| `ENABLE_WORKFLOW` / `WORKFLOW_*` | Multi-Agent Workflow: master switch, recursion limit, nesting max, node/branch limits, result truncation, worker pool size, HITL handler |

Model requests use `LLM_API_TIMEOUT` per request and `LLM_TOTAL_TIMEOUT` for the whole call, including retries and fallback. `LLM_MAX_RETRIES` (default 10 retries shared by primary and fallback), `LLM_RETRY_BASE_DELAY`, and `LLM_RETRY_MAX_DELAY` control exponential backoff with jitter; rate limits respect `Retry-After`. Set `LLM_FALLBACK_MODEL` and optionally `LLM_FALLBACK_BASE_URL`/`LLM_FALLBACK_API_KEY` for a backup. Provider circuit breakers use `LLM_CIRCUIT_FAILURE_THRESHOLD` and `LLM_CIRCUIT_COOLDOWN`. Automatic retries/fallback apply to transient failures before streaming begins. A failed request retains the existing conversation checkpoint. The total deadline releases the caller; an SDK call already in progress may finish in its bounded daemon thread.


Full template: [`.env.example`](https://github.com/nl8590687/lemonclaw/blob/main/.lemonclaw/.env.example). Launch from the project directory to load `.lemonclaw/.env`; existing environment variables take precedence. Never commit credentials.
