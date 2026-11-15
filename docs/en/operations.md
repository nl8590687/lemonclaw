[Documentation](index.md) · [简体中文](../zh/operations.md)

# Operations and backups

## Logs

For foreground execution, read terminal output. For a background Docker container, use `docker logs --tail 100 lemonclaw`. Remove credentials, private messages, and sensitive file content before sharing logs.

## Persistent data

- `.lemonclaw/.env`: provider, channel, and tool configuration, including credentials.
- `.lemonclaw/lemonclaw.db`: the single database for sessions, memory, workflows, and other state.
- `.lemonclaw/mcp.json`: MCP configuration, potentially including tokens.
- `.lemonclaw/skills/`: custom skills.
- Attachments and working files: persist actual directories separately; see [deployment](deployment.md).

## Before upgrading

Record the current commit or image tag; back up configuration and data. Read commits, PRs, and release notes for the target version. Validate a nonproduction copy before upgrading.

## To be completed: backup and recovery

Document offline and online SQLite backup commands, retention, restore drills, permissions, and credential handling. Copying only the live main database file is not a verified consistent backup procedure.

## To be completed: upgrade and rollback

Document version compatibility, database changes, upgrade validation, and rollback. Do not assume an older application can read an upgraded database.

## To be completed: long-running services

Monitoring, log rotation, capacity planning, and measured resource requirements remain to be documented.
