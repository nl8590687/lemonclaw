[文档首页](index.md) · [English](../en/deployment.md)

# 部署与运行

## 从源码构建 Docker 镜像

先完成[快速开始](getting-started.md)中的配置准备，再执行：

```bash
docker build -t lemonclaw:local .
docker run -it --name lemonclaw -e TZ=Asia/Shanghai   --mount type=bind,src="$(pwd)/.lemonclaw",dst=/root/.lemonclaw   lemonclaw:local
```

这是 Linux/macOS 的终端交互示例；PowerShell 使用单行命令，挂载源填写 `.lemonclaw` 的绝对路径。终端方式需要 `-it`。作为后台服务运行前，先配置飞书或 Webhook 输入，再按服务用途选择 `-d` 和重启策略。

镜像包含 Python 3.14、Node.js 24、npm 和飞书 CLI；具体构建参数以 [Dockerfile](https://github.com/nl8590687/lemonclaw/blob/main/Dockerfile) 为准。

## Webhook 端口

仅在需要 HTTP 输入时开启 `ENABLE_WEBHOOK=true`。容器内设置 `WEBHOOK_HOST=0.0.0.0`，并配置非空 `WEBHOOK_AUTH_TOKEN`；启动容器时增加 `-p 127.0.0.1:8765:8765`，将宿主访问限制在本机。其他机器访问需另行配置网络和鉴权，不能只照搬端口映射。

## 数据与时区

挂载 `/root/.lemonclaw` 保留配置和数据库。附件接收目录默认 `/root/workspace/received`，使用附件时还需持久化该目录；其他文件工作目录也应按实际路径单独挂载。不要只备份数据库而漏掉被历史消息引用的图片和文件。

镜像默认 UTC；示例使用 `TZ=Asia/Shanghai`。定时任务按服务本地时区执行。

## 预构建镜像

仓库发布工作流使用 `ghcr.io/nl8590687/lemonclaw`。请在[发布页](https://github.com/nl8590687/lemonclaw/releases)及关联镜像中确认可用标签，再替换上述 `lemonclaw:local`。不要假设 `latest` 包含尚未发布的 main 分支改动。

## 待补充

- 完整 Docker Compose 示例与服务重启策略。
- Windows Docker 操作截图。
- Linux systemd 部署教程。
