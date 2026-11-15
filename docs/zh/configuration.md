[文档首页](index.md) · [English](../en/configuration.md)

# ⚙️ 配置

所有配置位于 `.lemonclaw/.env`（完整项见 `.env.example`）。主要分组：

| 分组 | 用途 |
|------|------|
| `OPENAI_*` / `MODEL_*` | LLM 接口地址、模型、上下文窗口、温度、超时 |
| `BOCHA_*` | 博查联网搜索 API（可选，开启后生效搜索工具） |
| `EMAIL_*` | 邮件工具的 SMTP 服务器配置（可选） |
| `ENABLE_BASH_TOOL` / `FILE_SAFE_DIRS` | 工具安全：Shell 工具开关、文件访问白名单 |
| `WEB_*` | Web/HTTP 安全：私网访问开关、信任列表、私网写入开关、重定向/响应大小/超时 |
| `AGENT_REACT_MAX_ITERATIONS` / `CONTEXT_*` | Agent 行为：ReAct 最大迭代次数、保留消息数 |
| `ENABLE_WEBHOOK` / `WEBHOOK_*` | Webhook 服务：主机/端口、鉴权 Token、频率限制 |
| `ENABLE_FEISHU` / `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | 飞书/Lark 应用凭证 |
| `FEISHU_RECEIVED_DIR` / `FEISHU_MAX_DOWNLOAD_MB` / `FEISHU_MAX_SEND_FILE_MB` / `FEISHU_PENDING_FILE_TTL_SECONDS` | 飞书文件：接收目录（默认 `/root/workspace/received`）、收发大小上限、纯文件暂存过期时间 |
| `ENABLE_MEMORY` / `MEMORY_*` | 持久化记忆：上下文预算、最近会话数、检索块上限、自动归档 |
| `ENABLE_SKILLS` / `ENABLE_SKILL_SCRIPT` / `MAX_ACTIVE_SKILLS` / `PIP_INDEX_URL` / `NPM_REGISTRY` | 技能系统：总开关、脚本执行开关、活跃集上限、pip/npm 依赖镜像源 |
| `ENABLE_MCP` / `MCP_CONNECT_TIMEOUT` / `MCP_CALL_TIMEOUT` / `MCP_MAX_TOOLS` / `MCP_RESULT_MAX_CHARS` | MCP 接入：总开关、连接/调用超时、单服务端工具数上限、结果截断阈值 |
| `ENABLE_WORKFLOW` / `WORKFLOW_*` | 多 Agent 工作流：总开关、递归上限、嵌套上限、节点/分支上限、结果截断、Worker 池大小、HITL handler |

模型调用通过 `LLM_API_TIMEOUT` 设置单次请求超时，`LLM_TOTAL_TIMEOUT` 限制包含重试、备用模型在内的总耗时。`LLM_MAX_RETRIES`（默认最多重试 10 次，主备模型共用预算）、`LLM_RETRY_BASE_DELAY`、`LLM_RETRY_MAX_DELAY` 控制带随机抖动的指数退避，限流时遵循 `Retry-After`。可设置 `LLM_FALLBACK_MODEL`，以及可选的 `LLM_FALLBACK_BASE_URL`/`LLM_FALLBACK_API_KEY`。Provider 熔断通过 `LLM_CIRCUIT_FAILURE_THRESHOLD` 与 `LLM_CIRCUIT_COOLDOWN` 配置。自动重试和切换适用于流式输出开始前的暂时性故障；失败时保留现有会话 checkpoint。总时限到达后释放调用方，已进入 SDK 的请求可能继续留在有容量上限的守护线程中直至返回。


完整配置模板：[`.env.example`](https://github.com/nl8590687/lemonclaw/blob/main/.lemonclaw/.env.example)。从项目目录启动时读取 `.lemonclaw/.env`；环境变量优先于该文件。密钥不要提交到版本库。
