[Documentation](index.md) · [简体中文](../zh/architecture.md)

# 🏗️ Architecture

```mermaid
flowchart LR
    subgraph Inputs[Input Channels]
        T[Terminal]
        W[Webhook]
        C[Cron]
        F[Feishu/Lark]
    end
    Inputs --> Bus[(Message Bus)]
    Bus --> Loop{Agent Loop}
    Loop -->|"/" command| Cmd[Command Handler]
    Loop -->|message| Agent[Agent Service]
    Agent --> LLM[LLM<br/>OpenAI-compatible]
    Agent --> Tools[Tools<br/>16+ built-in]
    Agent --> Mem[Memory<br/>TF-IDF + Archive]
    Agent --> Skills[Skills<br/>load/unload + inject]
    Agent --> MCP[MCP<br/>HTTP / SSE / stdio]
    Agent --> Out[Output Channel]
    Cmd --> Out
    Out --> Resp[Terminal / Feishu]
```

### Project structure

```
|- .lemonclaw/    LemonClaw core config storage
|--- .env         Environment variables
|--- .env.example Example env file
|--- mcp.json     MCP server config (HTTP / SSE / stdio; gitignored - contains secrets)
|--- lemonclaw.db Global SQLite3 database (single DB for the whole project)
|- agent/         Agent implementation (loop, tools, LLM, memory, skills, MCP)
|- channels/      Input/output devices and the message bus
|- dao/           Database models and DAO operations
|- config/        Configuration
|- tests/         Unit tests
|- loop.py        Agent loop core
|- main.py        Entry point
```
