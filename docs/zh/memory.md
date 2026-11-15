[文档首页](index.md) · [English](../en/memory.md)

# 🧠 记忆系统

当 `ENABLE_MEMORY=true` 时，LemonClaw 会在唯一的 SQLite 数据库中维护持久化记忆：

- **长期记忆块** —— 以可检索的块形式存储事实、偏好与知识，查询时通过 **TF-IDF** 召回。
- **会话归档** —— 会话结束时自动摘要归档，便于后续召回。
- **记忆工具** —— 使用 `recall_memory` 检索历史事实与决策，使用 `list_memory` 读取核心偏好和项目背景。
- **历史维护** —— 每轮结束仅缩短保留区外的超长工具文本/入参字符串（`CONTEXT_TOOL_MAX_CHARS`，默认每字符串 12000 字符）；达到上下文 80% 阈值才统一摘要较早历史。最近至少 `CONTEXT_MIN_FULL_MESSAGES` 条消息完整保留，边界遇到工具调用/结果组时向前扩展。

可通过 `/memory`、`/chunk`、`/session` 命令在运行时管理记忆。
