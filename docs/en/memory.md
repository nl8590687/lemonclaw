[Documentation](index.md) · [简体中文](../zh/memory.md)

# 🧠 Memory System

When `ENABLE_MEMORY=true`, LemonClaw maintains persistent memory in the single SQLite database:

- **Long-term memory chunks** — facts, preferences, and knowledge stored as searchable chunks, retrieved at query time via **TF-IDF**.
- **Session archival** — at session end, the conversation is summarized and archived so it can be recalled later.
- **Memory tools** — use `recall_memory` for historical facts and decisions, and `list_memory` for core preferences and project context.
- **History maintenance** — after each turn, only oversized tool text/argument strings outside the protected recent-message group are shortened (`CONTEXT_TOOL_MAX_CHARS`, default 12000 characters per string). Older history is summarized together only at 80% context pressure. At least `CONTEXT_MIN_FULL_MESSAGES` recent messages, extended to keep tool calls/results paired, remain intact.

To manage memory live via the `/memory`, `/chunk`, and `/session` commands.
