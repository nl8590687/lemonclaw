[Documentation](index.md) · [简体中文](../zh/commands.md)

# 💬 Slash Commands

Available inside any conversation (type `/help` for the full list):

| Command | Description |
|---------|-------------|
| `/help` | Show help |
| `/tokens` | Show cumulative token usage |
| `/clear` | Clear the current conversation |
| `/session` / `/session show <id>` | List recent sessions / view a session's history |
| `/resume [id]` | Resume a session in place |
| `/chunk` | Manage long-term memory chunks (list/add/get/delete/search) |
| `/memory` | Manage core memory (set/get/delete/list) |
| `/cron` | List and manage scheduled tasks (`/cron help` for subcommands) |
| `/skills` | List and manage skills (`/skills help` for subcommands: list/show/enable/disable/unload/setup/reload) |
| `/mcp` | List and manage MCP servers (`/mcp help` for subcommands: list/add/remove/enable/disable/tools/reconnect/reload/call) |
| `/wf` | List and manage workflows (`/wf help` for subcommands: list/runs/resume/cancel/delete) |
| `/exit` `/quit` `/q` | Exit |


Other commands: `/image` selects images for a question and `/upload` saves attachments (see [images](images.md)); `/question` redisplays a pending question and `/cancel` cancels it (see [confirmation](interaction.md)). For exact subcommands, use the running application's `/help` and per-command `help`.
