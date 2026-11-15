[文档首页](index.md) · [English](../en/mcp.md)

# MCP 接入

LemonClaw 作为 MCP 客户端接入外部服务，支持 Streamable HTTP、SSE 和 stdio。默认开启 `ENABLE_MCP`；使用项目完整依赖安装即可，不需要自行实现协议。

## 配置并连接

在 `.lemonclaw/mcp.json` 按服务 ID 配置，例如：

```json
{
  "remote": {
    "url": "https://your-server.example/mcp",
    "headers": {"Authorization": "Bearer your-token"},
    "auto_connect": true
  },
  "local": {
    "transport": "stdio",
    "command": "python",
    "args": ["/absolute/path/to/server.py"],
    "auto_connect": false
  }
}
```

示例端点和脚本是占位值。stdio 命令和依赖必须在 LemonClaw 的运行环境中存在；Docker 中的路径是容器内路径。SSE 服务显式设置 `"transport": "sse"`，并使用服务方提供的 URL。

启动后执行 `/mcp reload`，用 `/mcp list` 检查状态、`/mcp tools remote` 查看工具。服务 ID 只使用字母、数字、下划线和连字符；工具名为 `mcp__<服务ID>__<工具名>`。完整模板见 [mcp.json.example](https://github.com/nl8590687/lemonclaw/blob/main/.lemonclaw/mcp.json.example)。

## 运行时管理

输入 `/mcp help` 查看全部命令。常用操作包括 `list`、`tools <id>`、`enable <id>`、`disable <id>`、`reconnect <id>`、`reload` 和 `call <id> <tool> [json_args]`。启用状态由数据库管理，不在 JSON 文件里设置 `enabled`。重载保留已有会话。

单服务端工具数量受 `MCP_MAX_TOOLS` 限制；工具结果受 `MCP_RESULT_MAX_CHARS` 限制。单个服务连接失败不阻断其他服务和内置工具。

## 能力边界

服务声明资源、资源模板或提示词等能力时，客户端可通过相应辅助工具访问；可用工具受服务能力和全局工具上限约束。交互式 elicitation 可进入人工确认流程。不要将协议 SDK 的所有能力都理解为已开放给 Agent：远程 sampling、订阅推送、任务扩展等没有完整的业务入口；LemonClaw 也不对外提供 MCP 服务端。

## 凭证

`headers` 用于服务连接，不主动注入模型提示词；文件可能包含真实凭证，不要提交或分享。远程服务返回内容、日志以及具有文件/Shell 权限的工具仍需按实际权限管理，不能据此承诺密钥绝不泄露。

## 待补充

常用服务的完整安装案例、OAuth 配置与验证过的兼容性列表。
