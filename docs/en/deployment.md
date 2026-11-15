[Documentation](index.md) · [简体中文](../zh/deployment.md)

# Deployment

## Build the Docker image from source

Prepare the configuration as described in [quick start](getting-started.md), then run:

```bash
docker build -t lemonclaw:local .
docker run -it --name lemonclaw -e TZ=Asia/Shanghai   --mount type=bind,src="$(pwd)/.lemonclaw",dst=/root/.lemonclaw   lemonclaw:local
```

This is an interactive Linux/macOS example. In PowerShell, use a single-line command and an absolute bind-mount source path. Terminal interaction requires `-it`. Configure Feishu or Webhook input before running as a background service; choose `-d` and a restart policy for that deployment.

The image includes Python 3.14, Node.js 24, npm, and Feishu CLI. See the [Dockerfile](https://github.com/nl8590687/lemonclaw/blob/main/Dockerfile) for build arguments.

## Webhook port

Enable `ENABLE_WEBHOOK=true` only when HTTP input is needed. Set `WEBHOOK_HOST=0.0.0.0` inside the container and a nonempty `WEBHOOK_AUTH_TOKEN`. Add `-p 127.0.0.1:8765:8765` to restrict host access to localhost. Remote access requires an explicit network and authentication setup.

## Storage and time zone

Mount `/root/.lemonclaw` for configuration and database persistence. Received attachments default to `/root/workspace/received`; persist that directory separately when using attachments, along with any other working directories. Historical image/file references need their underlying files.

The image defaults to UTC; the example sets `TZ=Asia/Shanghai`. Scheduled tasks use the service's local time zone.

## Pre-built images

The publishing workflow targets `ghcr.io/nl8590687/lemonclaw`. Verify available tags through [releases](https://github.com/nl8590687/lemonclaw/releases) and their associated images before replacing `lemonclaw:local` above. Do not assume `latest` contains unreleased main-branch changes.

## To be completed

- Full Docker Compose example and restart policy.
- Windows Docker screenshots.
- Linux systemd deployment tutorial.
