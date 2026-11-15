[文档首页](index.md) · [English](../en/images.md)

# 图片输入

主模型支持图像输入时设置 `ENABLE_VISION=True`（默认开启）。图片保存到 `FEISHU_RECEIVED_DIR`，会话 checkpoint 保存稳定附件引用；请求模型时按原始字节编码为 Base64 Data URL。支持按实际内容校验 JPEG、PNG、GIF、WebP。应用单次请求最多 8 张图、图片原始数据合计 20 MiB，单张最多 10 MiB。纯文本请求保持现有行为。

```text
/image "/path/带空格的图片.png" /path/b.jpg -- 比较这两张图
/image img-<编号> img-<编号> -- 比较差异
/image all -- 描述当前暂存图片
/upload "/path/image.png"
```

`/image` 选择本轮图片，问题前使用 `--` 分隔；`/upload` 仅保存文件并返回路径/编号。飞书单独发图后会收到编号回执；可引用该图片消息并回复问题、用 `/image` 指定编号，或在同一条富文本消息中发送文字和图片。普通后续文字沿用附件路径说明机制，暂存图片通过明确选择加入视觉输入。`/upload` 将所有暂存图片标记为仅保存，`/upload <编号...>` 仅处理指定图片。暂存选择按 `FEISHU_PENDING_FILE_TTL_SECONDS` 过期，已有历史引用仍可使用。本地路径只允许在命令行选择。

备用模型支持图片时再设置 `LLM_FALLBACK_ENABLE_VISION=True`；含图请求要求备用模型具备视觉能力。关闭视觉后请求只携带图片文字引用。请保留被历史引用的文件；图片缺失、变更或超过预算时会明确报错。上下文摘要使用同一图片适配层。Workflow 的 `llm`/`subagent` 节点通过 `config.image_ids` 或 `config.image_ids_field`（list 状态字段）显式传入当前来源会话的图片编号。当前文档介绍图片理解和文件发送；不提供图片生成教程。

主会话沿用现有共享机制，终端与飞书可继续同一段图片对话。历史图片按已保存的附件作用域读取，新选附件仍校验当前来源；需要独立会话时可指定不同的 `session_key`。
