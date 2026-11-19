# LemonClaw

[English](README.md) | [简体中文](README_ZH-CN.md)

[![Python](https://img.shields.io/badge/Python-3.13–3.15-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache%202.0-green)](LICENSE)

> 可自行部署、通过终端或飞书使用的 AI 数字员工。

LemonClaw 将 OpenAI 兼容模型与文件、网页、Shell、定时任务等工具连接起来，支持持久化记忆、Skills、MCP 和多 Agent 工作流。你可以从一次终端对话开始，再接入飞书或 Webhook。

[快速开始](docs/zh/getting-started.md) · [用户文档](docs/zh/index.md) · [部署与运维](docs/zh/deployment.md) · [问题反馈](https://github.com/nl8590687/lemonclaw/issues)

## 可以做什么

- 查询网页、整理文件和总结资料；联网搜索等能力需要相应服务配置。
- 保存偏好和历史信息，让后续对话可以检索已有记忆。
- 安排定时任务，或通过多 Agent 工作流执行多阶段任务。
- 使用 Skills 和 MCP 接入外部能力，在飞书中接收回复、发送文件和回答确认问题。

这些是使用方向，不保证任意模型或外部服务都能完成所有任务；可用能力由模型、配置和权限决定。

## 核心能力

| 能力 | 说明 |
|---|---|
| 多入口 | 终端、飞书、Webhook、定时事件 |
| 工具 | 文件操作、网页、HTTP、Git；Shell 按需开启 |
| 持久化 | 单一 SQLite 数据库保存会话、记忆、任务等状态 |
| 扩展 | Skills；MCP 支持 Streamable HTTP、SSE 和 stdio |
| 工作流 | 子 Agent、条件路由、人工确认和中断恢复 |
| 部署 | Python 源码运行或 Docker；模型服务单独配置 |

## 快速开始

需要 **Python 3.13～3.15**、一个 OpenAI 兼容接口、API Key 和可用模型名称。以下为 Linux/macOS 源码运行示例；[Windows 和完整教程](docs/zh/getting-started.md)。

```bash
git clone https://github.com/nl8590687/lemonclaw.git
cd lemonclaw
python -m venv .venv
source .venv/bin/activate
python -m pip install -e . -c constraints.txt
cp .lemonclaw/.env.example .lemonclaw/.env
```

编辑 `.lemonclaw/.env`，填写真实服务配置。以下地址、Key 和模型名是占位值：

```ini
OPENAI_BASE_URL=https://your-provider.example/v1
OPENAI_API_KEY=your-api-key
MODEL_NAME=your-model-name
ENABLE_WEBHOOK=false
ENABLE_FEISHU=false
```

在项目根目录启动：

```bash
lemonclaw
```

在终端发送“你好，请介绍你能做什么”，收到回复即可确认基本连接正常。`/help` 查看命令，`/exit` 退出。Docker 部署见[部署说明](docs/zh/deployment.md)。

## 使用前了解

- 模型 API、搜索和邮件等外部服务需要自行配置，可能产生费用。
- Shell 默认关闭；文件访问受 `FILE_SAFE_DIRS` 限制。开启工具前确认它们可访问的数据和执行权限。
- 终端与飞书默认共享个人主会话；飞书个人模式会绑定首个发送消息的用户，不应当作多用户隔离服务部署。
- 生产环境需要持久化数据库、配置及附件，并安排备份；详见[运维文档](docs/zh/operations.md)。

## 文档导航

| 我想…… | 阅读 |
|---|---|
| 安装、部署或排障 | [快速开始](docs/zh/getting-started.md)、[部署](docs/zh/deployment.md)、[排障](docs/zh/troubleshooting.md) |
| 连接飞书、处理图片或使用 CLI | [通道](docs/zh/channels.md)、[图片](docs/zh/images.md)、[飞书 CLI](docs/zh/feishu-cli.md) |
| 配置模型和工具 | [配置](docs/zh/configuration.md)、[工具](docs/zh/tools.md) |
| 浏览器界面 | [WebUI 构建、登录与管理](docs/zh/webui.md) |
| 使用扩展和自动化 | [Skills](docs/zh/skills.md)、[MCP](docs/zh/mcp.md)、[工作流](docs/zh/workflows.md) |
| 管理对话和任务 | [记忆](docs/zh/memory.md)、[命令](docs/zh/commands.md)、[人工确认](docs/zh/interaction.md) |
| 贡献代码 | [贡献指南](docs/zh/contributing.md)、[架构](docs/zh/architecture.md) |

截图、完整案例和部分运维教程尚待补充，见[文档首页](docs/zh/index.md)。

## 参与贡献

欢迎提交问题、改进文档或贡献代码。请先阅读[贡献指南](docs/zh/contributing.md)和 [AGENTS.md](AGENTS.md)。用户可见行为变化应同步更新文档；开发过程及验证记录写入提交信息和 PR。

## 许可证

[Apache License 2.0](LICENSE)。Copyright © 2026 LemonClaw Contributors.
