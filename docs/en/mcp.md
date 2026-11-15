[Documentation](index.md) · [简体中文](../zh/mcp.md)

# MCP integration

LemonClaw is an MCP client for external servers over Streamable HTTP, SSE, and stdio. `ENABLE_MCP` is enabled by default. Install the full project dependencies; no custom protocol implementation is needed.

## Configure and connect

Configure servers by ID in `.lemonclaw/mcp.json`, for example:

```json
{
  "remote": {
    "url": "https://your-server.example/mcp",
    "headers": {"Authorization": "Bearer your-token"},
    "auto_connect": true
  },
  "local": {
    "transport": "stdio",
    "command": "python",
    "args": ["/absolute/path/to/server.py"],
    "auto_connect": false
  }
}
```

The endpoint and script are placeholders. The stdio command and dependencies must exist in LemonClaw's runtime; Docker paths are container paths. For SSE, set `"transport": "sse"` explicitly and use your server's URL.

Run `/mcp reload`, inspect `/mcp list`, and view `/mcp tools remote`. IDs may contain letters, digits, underscores, and hyphens. Tools are named `mcp__<server_id>__<tool>`. See [mcp.json.example](https://github.com/nl8590687/lemonclaw/blob/main/.lemonclaw/mcp.json.example) for the template.

## Runtime management

Use `/mcp help` for all commands. Common operations include `list`, `tools <id>`, `enable <id>`, `disable <id>`, `reconnect <id>`, `reload`, and `call <id> <tool> [json_args]`. Enable state is stored in the database rather than an `enabled` JSON field. Reloading retains the conversation.

`MCP_MAX_TOOLS` limits tools per server; `MCP_RESULT_MAX_CHARS` limits tool results. One server's connection failure does not block other servers or built-in tools.

## Capability boundaries

Resource, resource-template, and prompt capabilities can be exposed through helper tools when declared by the server, subject to capability and global tool limits. Interactive elicitation can use human confirmation. SDK protocol support does not mean every feature has an Agent-facing entry point: remote sampling, subscription pushes, and task extensions do not have complete application integration. LemonClaw does not expose an MCP server.

## Credentials

Connection headers are not intentionally injected into model prompts. Configuration can contain real credentials: do not commit or share it. Server responses, logs, and tools with file/shell access still need appropriate permissions; this is not a guarantee against credential disclosure.

## To be completed

Complete setup examples, OAuth configuration, and a verified compatibility list.
