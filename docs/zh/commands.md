[文档首页](index.md) · [English](../en/commands.md)

# 💬 斜杠命令

在任意对话中可用（输入 `/help` 查看完整列表）：

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/tokens` | 查看累计 Token 用量 |
| `/clear` | 清空当前对话 |
| `/session` / `/session show <id>` | 列出最近会话 / 查看某会话历史 |
| `/resume [id]` | 原地续写指定 id 或最近一次会话 |
| `/chunk` | 管理长期记忆块（list/add/get/delete/search） |
| `/memory` | 管理核心记忆（set/get/delete/list） |
| `/cron` | 列出并管理定时任务（`/cron help` 查看子命令） |
| `/skills` | 列出并管理技能（`/skills help` 查看子命令：list/show/enable/disable/unload/setup/reload） |
| `/mcp` | 列出并管理 MCP 服务端（`/mcp help` 查看子命令：list/add/remove/enable/disable/tools/reconnect/reload/call） |
| `/wf` | 列出并管理工作流（`/wf help` 查看子命令：list/runs/resume/cancel/delete） |
| `/exit` `/quit` `/q` | 退出 |


其他常用命令：`/image` 选择图片参与提问，`/upload` 保存附件（见[图片](images.md)）；`/question` 重看当前确认问题，`/cancel` 取消（见[人工确认](interaction.md)）。具体子命令以运行中的 `/help` 和各命令的 `help` 输出为准。
