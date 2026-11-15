[文档首页](index.md) · [English](../en/architecture.md)

# 🏗️ 架构

```mermaid
flowchart LR
    subgraph Inputs[输入通道]
        T[终端]
        W[Webhook]
        C[Cron 定时]
        F[飞书/Lark]
    end
    Inputs --> Bus[(消息总线)]
    Bus --> Loop{Agent 循环}
    Loop -->|"/" 命令| Cmd[命令处理器]
    Loop -->|消息| Agent[Agent 服务]
    Agent --> LLM[LLM<br/>OpenAI 兼容]
    Agent --> Tools[工具<br/>16+ 内置]
    Agent --> Mem[记忆<br/>TF-IDF + 归档]
    Agent --> Skills[技能<br/>load/unload + 注入]
    Agent --> MCP[MCP<br/>HTTP / SSE / stdio]
    Agent --> Out[输出通道]
    Cmd --> Out
    Out --> Resp[终端 / 飞书]
```

### 项目结构

```
|- .lemonclaw/    LemonClaw 核心配置存储目录
|--- .env         环境变量配置文件
|--- .env.example 环境变量配置样例文件
|--- mcp.json     MCP 服务端配置（HTTP / SSE / stdio；含密钥，已 gitignore）
|--- lemonclaw.db 全局 SQLite3 数据库（整个项目仅此一个库）
|- agent/         Agent 实现模块（循环、工具、LLM、记忆、技能、MCP）
|- channels/      输入输出设备和通道、消息总线
|- dao/           数据库 model 和 dao 操作模块
|- config/        配置相关代码模块
|- tests/         单元测试目录
|- loop.py        Agent Loop 核心代码
|- main.py        启动入口代码
```
