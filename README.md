# LemonClaw

[English](README.md) | [简体中文](README_ZH-CN.md)

[![Python](https://img.shields.io/badge/Python-3.13–3.15-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache%202.0-green)](LICENSE)

> A self-hosted AI digital employee, accessible through your terminal or Feishu.

LemonClaw connects OpenAI-compatible models to file, web, shell, and scheduling tools, with persistent memory, Skills, MCP, and multi-agent workflows. Start with a terminal conversation, then connect Feishu or Webhook input.

[Quick start](docs/en/getting-started.md) · [User documentation](docs/en/index.md) · [Deployment and operations](docs/en/deployment.md) · [Issues](https://github.com/nl8590687/lemonclaw/issues)

## What can you use it for?

- Research web pages, organize files, and summarize information. Some tools, including search, require additional services.
- Save preferences and facts for retrieval in later conversations.
- Schedule tasks or use multi-agent workflows for multi-stage work.
- Extend capabilities through Skills and MCP; receive replies, send files, and answer confirmation questions in Feishu.

These are usage scenarios, not guarantees for every model or external service. Capabilities depend on your model, configuration, and permissions.

## Core capabilities

| Capability | Description |
|---|---|
| Entry points | Terminal, Feishu, Webhook, and scheduled events |
| Tools | Files, web, HTTP, Git; opt-in shell execution |
| Persistence | One SQLite database for sessions, memory, tasks, and other state |
| Extensions | Skills; MCP over Streamable HTTP, SSE, and stdio |
| Workflows | Sub-agents, conditional routing, human confirmation, and recovery |
| Deployment | Python source or Docker; configure your model provider separately |

## Quick start

You need **Python 3.13–3.15**, an OpenAI-compatible endpoint, API key, and available model name. The following source-install example is for Linux/macOS; see the [full guide and Windows instructions](docs/en/getting-started.md).

```bash
git clone https://github.com/nl8590687/lemonclaw.git
cd lemonclaw
python -m venv .venv
source .venv/bin/activate
python -m pip install -e . -c constraints.txt
cp .lemonclaw/.env.example .lemonclaw/.env
```

Edit `.lemonclaw/.env` with your provider settings. The following endpoint, key, and model name are placeholders:

```ini
OPENAI_BASE_URL=https://your-provider.example/v1
OPENAI_API_KEY=your-api-key
MODEL_NAME=your-model-name
ENABLE_WEBHOOK=false
ENABLE_FEISHU=false
```

Start from the project root:

```bash
lemonclaw
```

Ask “Hello, what can you do?” in the terminal. A reply verifies basic connectivity. Use `/help` for commands and `/exit` to quit. For Docker, see [deployment](docs/en/deployment.md).

## Before you use it

- Configure external model, search, and email services yourself; provider fees may apply.
- Shell execution is off by default; `FILE_SAFE_DIRS` restricts file access. Review data access and execution permissions before enabling tools.
- Terminal and Feishu share the personal main session by default. Feishu personal mode binds the first messaging user; it is not a multi-user isolation service.
- Persist configuration, database, and attachments and plan backups for production. See [operations](docs/en/operations.md).

## Documentation

| I want to… | Read |
|---|---|
| Install, deploy, or troubleshoot | [Quick start](docs/en/getting-started.md), [deployment](docs/en/deployment.md), [troubleshooting](docs/en/troubleshooting.md) |
| Connect Feishu, use images or CLI | [Channels](docs/en/channels.md), [images](docs/en/images.md), [Feishu CLI](docs/en/feishu-cli.md) |
| Configure models and tools | [Configuration](docs/en/configuration.md), [tools](docs/en/tools.md) |
| Browser interface | [WebUI setup and management](docs/en/webui.md) |
| Extend and automate | [Skills](docs/en/skills.md), [MCP](docs/en/mcp.md), [workflows](docs/en/workflows.md) |
| Manage conversations and tasks | [Memory](docs/en/memory.md), [commands](docs/en/commands.md), [human confirmation](docs/en/interaction.md) |
| Contribute code | [Contributing](docs/en/contributing.md), [architecture](docs/en/architecture.md) |

Screenshots, complete examples, and some operations guides remain to be added; see the [documentation index](docs/en/index.md).

## Contributing

Issues, documentation improvements, and code contributions are welcome. Read the [contribution guide](docs/en/contributing.md) and [AGENTS.md](AGENTS.md). Update documentation for user-facing behavior changes; keep development history and validation in commits and PRs.

## License

[Apache License 2.0](LICENSE). Copyright © 2026 LemonClaw Contributors.
