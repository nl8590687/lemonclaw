[文档首页](index.md) · [English](../en/memory.md)

# 🧠 记忆系统

## OpenViking

安装本项目依赖后，在 `.lemonclaw/.env` 中设置以下变量并重启 LemonClaw。使用 LemonClaw 进程能访问的 OpenViking 服务地址。两个服务都运行于 Docker 时，可在共享网络内使用 OpenViking 的服务名。

```dotenv
ENABLE_OPENVIKING=true
OPENVIKING_BASE_URL=http://openviking:1933
OPENVIKING_API_KEY=your-user-api-key
```

启用后，终端、飞书和 WebUI 的主 Agent 用户轮次会检索 OpenViking 记忆，并在有最终文本回复后写入用户原文和最终回复。附件和工具原始输出不会单独写入。服务不可用时记录警告，对话继续。可先告诉 Agent 一个偏好，再开启新会话询问该偏好以验证召回。

OpenViking 关闭时，`ENABLE_MEMORY` 控制 SQLite 内置记忆。切换不会迁移既有记忆。当前对话和中断恢复仍使用 LemonClaw 的 checkpoint。内置记忆工具在 OpenViking 模式下不注册。

## 内置记忆

当 `ENABLE_MEMORY=true` 时，LemonClaw 会在唯一的 SQLite 数据库中维护持久化记忆：

- **长期记忆块** —— 以可检索的块形式存储事实、偏好与知识，查询时通过 **TF-IDF** 召回。
- **会话归档** —— 会话结束时自动摘要归档，便于后续召回。
- **记忆工具** —— 使用 `recall_memory` 检索历史事实与决策，使用 `list_memory` 读取核心偏好和项目背景。
- **历史维护** —— 每轮结束仅缩短保留区外的超长工具文本/入参字符串（`CONTEXT_TOOL_MAX_CHARS`，默认每字符串 12000 字符）；达到上下文 80% 阈值才统一摘要较早历史。最近至少 `CONTEXT_MIN_FULL_MESSAGES` 条消息完整保留，边界遇到工具调用/结果组时向前扩展。

可通过 `/memory`、`/chunk`、`/session` 命令在运行时管理记忆。
