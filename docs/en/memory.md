[Documentation](index.md) · [简体中文](../zh/memory.md)

# 🧠 Memory System

## OpenViking

Install the project's dependencies, set these variables in `.lemonclaw/.env`, and restart LemonClaw. Use an OpenViking URL reachable from the LemonClaw process. If both services run in Docker, you can use the OpenViking service name on a shared network.

```dotenv
ENABLE_OPENVIKING=true
OPENVIKING_BASE_URL=http://openviking:1933
OPENVIKING_API_KEY=your-user-api-key
```

When enabled, user turns in the main Agent from the terminal, Feishu, and WebUI retrieve OpenViking memories. After a final text reply, LemonClaw records the user text and final reply. Attachments and raw tool output are excluded as separate records. If the service is unavailable, LemonClaw logs a warning and continues the conversation. To verify retrieval, tell the Agent a preference, then ask about it in a new conversation.

With OpenViking disabled, `ENABLE_MEMORY` controls built-in SQLite memory. Switching does not migrate existing memories. The current conversation and interrupted runs continue to use LemonClaw checkpoints. Built-in memory tools are omitted in OpenViking mode.

## Built-in memory

When `ENABLE_MEMORY=true`, LemonClaw maintains persistent memory in the single SQLite database:

- **Long-term memory chunks** — facts, preferences, and knowledge stored as searchable chunks, retrieved at query time via **TF-IDF**.
- **Session archival** — at session end, the conversation is summarized and archived so it can be recalled later.
- **Memory tools** — use `recall_memory` for historical facts and decisions, and `list_memory` for core preferences and project context.
- **History maintenance** — after each turn, only oversized tool text/argument strings outside the protected recent-message group are shortened (`CONTEXT_TOOL_MAX_CHARS`, default 12000 characters per string). Older history is summarized together only at 80% context pressure. At least `CONTEXT_MIN_FULL_MESSAGES` recent messages, extended to keep tool calls/results paired, remain intact.

To manage memory live via the `/memory`, `/chunk`, and `/session` commands.
