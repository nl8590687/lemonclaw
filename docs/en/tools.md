[Documentation](index.md) · [简体中文](../zh/tools.md)

# 🛠️ Built-in Tools

| Tool | Description | Availability |
|------|-------------|--------------|
| `time` | Current date/time | always |
| `http_request` | Arbitrary HTTP requests | always |
| `web_fetch` | Fetch and extract web page content | always |
| `read_file` / `write_file` / `edit_file` | File read / write / incremental edit | always (whitelisted dirs) |
| `file_list_query` | List files in a directory | always (whitelisted dirs) |
| `glob` / `grep` | File pattern match / content search | always (whitelisted dirs) |
| `git` | Common git operations | always |
| `sleep` | Wait for a duration | always |
| `cron` | Create / list / delete scheduled tasks | always |
| `bocha_search` | Web search via Bocha API | optional (needs `BOCHA_API_KEY`) |
| `email` | Send email via SMTP | optional (needs `EMAIL_*`) |
| `bash` | Run shell commands | optional (needs `ENABLE_BASH_TOOL=true`) |
| `feishu_send_file` | Send a workspace file/image/audio/MP4 to the current Feishu chat | optional (needs complete Feishu config) |
| `memory` | Read / write persistent memory | optional (needs `ENABLE_MEMORY=true`) |
| `load_skill` / `unload_skill` | Activate / unload a skill (instructions injected by the middleware) | optional (needs `ENABLE_SKILLS=true`) |
| `run_skill_script` | Run a skill's Python/Node script in its isolated env | optional (needs `ENABLE_SKILL_SCRIPT=true`) |
| `mcp__<server>__<tool>` | Tools from connected MCP servers (HTTP / SSE / stdio) | optional (needs `ENABLE_MCP=true` + `.lemonclaw/mcp.json`) |
| `workflow_define` / `workflow_execute` / `workflow_resume` / `workflow_cancel` / `workflow_list` / `workflow_inspect_run` / `workflow_delete` | Define, run, resume, manage multi-agent workflows | optional (needs `ENABLE_WORKFLOW=true`) |

> Extensible: add a new tool under `agent/tools/` and register it in `create_tool_list()`.

> **Web/HTTP safety boundary**: private/local targets require a full URL explicitly supplied in the user's current message, or an entry in `WEB_PRIVATE_ALLOWLIST`; URLs found in web pages, search results, or tool output do not grant access. Private targets are read-only by default, redirects are revalidated hop by hop, and external responses are marked as untrusted data.
