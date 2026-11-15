[Documentation](index.md) · [简体中文](../zh/troubleshooting.md)

# Troubleshooting

| Symptom | Check first |
|---|---|
| No model reply or authentication failure | Endpoint, key, model, provider quota, network, and environment variables overriding `.env` |
| Configuration changes ignored | Working directory and actual mounted `.env`; restart after changing startup configuration |
| Container Webhook unreachable | Enable flag, container listen address, port mapping, and authentication header; see deployment |
| Feishu not responding | App credentials, subscriptions, long connection, and bound user; see channels |
| File access denied | `FILE_SAFE_DIRS` and container mounts; do not indiscriminately expand access |
| No MCP tools | `/mcp list`, `/mcp tools <id>`, connection, authentication, and tool limits |
| Confirmation card not working | `card.action.trigger`; resend with `/question`, or answer/cancel with text in the original channel |
| Historical image missing | Original attachment files and container mounts |

For an Issue, include OS, Python version, commit/image tag, redacted configuration, minimal reproduction steps, and error logs.

## To be completed

Feishu error codes, provider differences, proxies, and representative incidents.
