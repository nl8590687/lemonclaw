[文档首页](index.md) · [English](../en/tools.md)

# 🛠️ 内置工具

| 工具 | 说明 | 可用性 |
|------|------|--------|
| `time` | 当前日期/时间 | 始终 |
| `http_request` | 任意 HTTP 请求 | 始终 |
| `web_fetch` | 抓取并提取网页内容 | 始终 |
| `read_file` / `write_file` / `edit_file` | 文件读 / 写 / 增量编辑 | 始终（白名单目录） |
| `file_list_query` | 列出目录下的文件 | 始终（白名单目录） |
| `glob` / `grep` | 文件通配匹配 / 内容搜索 | 始终（白名单目录） |
| `git` | 常用 git 操作 | 始终 |
| `sleep` | 等待一段时长 | 始终 |
| `cron` | 创建 / 列出 / 删除定时任务 | 始终 |
| `bocha_search` | 通过博查 API 联网搜索 | 可选（需 `BOCHA_API_KEY`） |
| `email` | 通过 SMTP 发送邮件 | 可选（需 `EMAIL_*`） |
| `bash` | 执行 Shell 命令 | 可选（需 `ENABLE_BASH_TOOL=true`） |
| `feishu_send_file` | 把工作空间内的文件/图片/音频/MP4 发送给当前飞书会话 | 可选（需完整飞书配置） |
| `memory` | 读写持久化记忆 | 可选（需 `ENABLE_MEMORY=true`） |
| `load_skill` / `unload_skill` | 激活 / 卸载技能（指令由中间件注入） | 可选（需 `ENABLE_SKILLS=true`） |
| `run_skill_script` | 在技能隔离环境执行 Python/Node 脚本 | 可选（需 `ENABLE_SKILL_SCRIPT=true`） |
| `mcp__<服务名>__<工具名>` | 已连接 MCP 服务端暴露的工具（Streamable HTTP） | 可选（需 `ENABLE_MCP=true` + `.lemonclaw/mcp.json`） |
| `workflow_define` / `workflow_execute` / `workflow_resume` / `workflow_cancel` / `workflow_list` / `workflow_inspect_run` / `workflow_delete` | 定义、运行、续跑、管理多 Agent 工作流 | 可选（需 `ENABLE_WORKFLOW=true`） |

> 可扩展：在 `agent/tools/` 下新增工具，并在 `create_tool_list()` 中注册即可。

> **Web/HTTP 安全边界**：私网/本地目标只能由用户**当前消息中的完整 URL**授权，或加入 `WEB_PRIVATE_ALLOWLIST`；网页、搜索结果和工具输出中的 URL 不构成授权。私网目标默认只允许只读方法，重定向逐跳复检；网页/HTTP 响应会标记为不可信外部数据。
