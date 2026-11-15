[Documentation](index.md) · [简体中文](../zh/channels.md)

# 📡 Channels

LemonClaw receives events through pluggable input channels and broadcasts replies to every enabled output channel. All channels publish to a single message bus consumed by the agent loop. The terminal is always enabled; when Feishu is enabled, replies go to both the terminal and Feishu.

Feishu final replies use Card JSON 2.0 with a Markdown body. The top title displays the received event type (`terminal`, `lark_message`, `scheduled`, `webhook`, `system`, etc.); a missing type is shown as `未知`. After a human-confirmation resume, this is the event that resumed the turn. Long replies are delivered as ordered cards, with fenced code blocks continued across parts. Sending stops on the first failed part without resending earlier parts. Menu/error output and human-confirmation forms retain their existing behavior. Card JSON 2.0 requires Feishu client 7.20 or later.


| Channel | Direction | Notes |
|---------|-----------|-------|
| **Terminal** | in/out | Always on. Interactive stdin + rich terminal output. |
| **Webhook** | in | HTTP server (default `127.0.0.1:8765`). Optional `X-Auth-Token` auth and per-minute rate limit. Enable with `ENABLE_WEBHOOK=true`. |
| **Feishu/Lark** | in/out | Bot messaging. Requires `ENABLE_FEISHU=true` plus `FEISHU_APP_ID` / `FEISHU_APP_SECRET` and event subscription configured in the Feishu developer console. In personal mode, the first Feishu user who messages the bot is bound automatically and persisted in `lemonclaw.db`; messages from other Feishu users are ignored, and all Feishu output goes to the bound user while the terminal always keeps outputting. Received files/images/audio/video are saved under `FEISHU_RECEIVED_DIR`; file-only messages are held until the user adds a text instruction. |
| **Cron** | in | Scheduled tasks. Always on; tasks are managed at runtime via the `/cron` command or the cron tool. |


## Feishu replies and status

Main-agent final replies use Markdown cards with the event type at the top. Commands and other system messages can use their own formats. User requests show Typing while being processed and DONE after a successful nonempty reply; errors or interrupts clear Typing. Reactions require `im:message.reactions:write_only`; reaction failures do not block message handling. For background workflows, DONE refers to the foreground reply only.

## To be completed: Feishu onboarding

Add screenshots for app creation, the full permission list, event subscriptions, long connections, publishing, and first-user binding. Human confirmation also requires `card.action.trigger`; see [confirmation](interaction.md).

## To be completed: Webhook examples

Add verified request schemas, authenticated requests, and asynchronous result consumption. See [deployment](deployment.md) for networking.
