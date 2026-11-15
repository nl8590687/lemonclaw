[文档首页](index.md) · [English](../en/feishu-cli.md)

# Bash 中使用飞书 CLI

Docker 镜像预装 Node.js 24、npm 和 `@larksuite/cli` 1.0.100；构建参数
`NODE_IMAGE`、`LARK_CLI_VERSION` 可覆盖默认值。启用 `ENABLE_BASH_TOOL=true`
并配置现有的 `FEISHU_APP_ID`、`FEISHU_APP_SECRET` 后，Bash 子进程会自动获得
CLI 的应用凭证、`feishu` 品牌和短期 tenant access token，无需重复配置容器环境变量。
SDK 缓存 token，并在过期前重新获取；每次 Bash 调用重新取 SDK 中的有效值。
已经启动的长时间命令不会在进程内自动替换 token，过期后需重新调用。
应用身份初始化失败会阻止本次 Bash 执行，检查配置和网络后重试。

应用密钥和 token 不写入镜像，但 Bash 命令能够读取子进程环境，应只向可信任务开放。
当前内置凭证注入支持应用身份；用户 OAuth 尚未接入，应用凭证不能代替用户授权。
在 `LARK_CHANNEL` bridge 环境中保留已有身份绑定，不覆盖其 profile。
工具输出会遮蔽 CLI 密钥和 token 的明文原值；这不能阻止命令读取或转换这些值。
