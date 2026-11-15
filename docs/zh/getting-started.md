[文档首页](index.md) · [English](../en/getting-started.md)

# 快速开始

需要 Python 3.13～3.15，以及一个 OpenAI 兼容的模型接口、API Key 和可用模型名称。

## 1. 安装

以下命令适用于 Linux/macOS：

```bash
git clone https://github.com/nl8590687/lemonclaw.git
cd lemonclaw
python -m venv .venv
source .venv/bin/activate
python -m pip install -e . -c constraints.txt
cp .lemonclaw/.env.example .lemonclaw/.env
```

Windows PowerShell 中将激活命令替换为 `.venv\Scripts\Activate.ps1`，复制配置使用 `Copy-Item .lemonclaw/.env.example .lemonclaw/.env`。其余安装步骤相同。

## 2. 配置模型

编辑 `.lemonclaw/.env`，按服务商提供的值填写；下面是占位值，不能直接调用：

```ini
OPENAI_BASE_URL=https://your-provider.example/v1
OPENAI_API_KEY=your-api-key
MODEL_NAME=your-model-name
ENABLE_WEBHOOK=false
ENABLE_FEISHU=false
```

先使用终端完成验证，再按需要开启其他通道。Shell 工具默认关闭。

## 3. 启动并验证

```bash
lemonclaw
```

请保持当前目录为项目根目录。看到终端输入提示后发送“你好，请介绍你能做什么”；收到回复说明模型连接和基本对话可用。输入 `/help` 查看命令，使用 `/exit` 退出。

首次调用失败时，检查模型名、接口地址、Key 和网络，参阅[排障](troubleshooting.md)。

## 下一步

- [Docker 部署](deployment.md)
- [飞书和其他通道](channels.md)
- [配置参考](configuration.md)
- [MCP 接入](mcp.md)
