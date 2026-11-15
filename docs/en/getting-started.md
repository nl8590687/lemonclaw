[Documentation](index.md) · [简体中文](../zh/getting-started.md)

# Quick start

You need Python 3.13–3.15 and an OpenAI-compatible endpoint, API key, and available model name.

## 1. Install

For Linux/macOS:

```bash
git clone https://github.com/nl8590687/lemonclaw.git
cd lemonclaw
python -m venv .venv
source .venv/bin/activate
python -m pip install -e . -c constraints.txt
cp .lemonclaw/.env.example .lemonclaw/.env
```

In Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` and copy the config with `Copy-Item .lemonclaw/.env.example .lemonclaw/.env`. Other installation steps are the same.

## 2. Configure your model

Edit `.lemonclaw/.env` using your provider's values. These are placeholders, not a working endpoint:

```ini
OPENAI_BASE_URL=https://your-provider.example/v1
OPENAI_API_KEY=your-api-key
MODEL_NAME=your-model-name
ENABLE_WEBHOOK=false
ENABLE_FEISHU=false
```

Verify the terminal first, then enable additional channels as needed. The shell tool is off by default.

## 3. Start and verify

```bash
lemonclaw
```

Keep the project root as your working directory. At the terminal prompt, ask “Hello, what can you do?” A reply verifies the model connection and basic conversation. Use `/help` for commands and `/exit` to quit.

If the first request fails, check the endpoint, model name, API key, and network; see [troubleshooting](troubleshooting.md).

## Next steps

- [Docker deployment](deployment.md)
- [Feishu and other channels](channels.md)
- [Configuration](configuration.md)
- [MCP integration](mcp.md)
