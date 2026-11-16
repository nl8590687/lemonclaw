[Documentation](index.md) · [简体中文](../zh/feishu-cli.md)

# Feishu CLI in Bash

The Docker image includes Node.js 24, npm, and `@larksuite/cli` 1.0.100
(overridable with the `NODE_IMAGE` and `LARK_CLI_VERSION` build arguments).
With `ENABLE_BASH_TOOL=true` and the existing `FEISHU_APP_ID` /
`FEISHU_APP_SECRET` configured, Bash child processes receive the CLI app
credentials, the `feishu` brand, and a short-lived tenant access token.
The Feishu SDK caches and renews this token; each Bash invocation obtains the
current value. Existing long-running commands need to be invoked again after
their token expires. Credential initialization failures stop that Bash invocation.
No credentials are stored in the image. Bash can read its environment, so only
trusted tasks should have access. Plaintext CLI secrets are redacted from tool
output, which does not prevent commands from reading or transforming them.
Built-in credential injection supports app identity. User OAuth is not integrated; app credentials do not grant user identity.
An existing `LARK_CHANNEL` bridge binding is preserved without overriding its profile.

The main agent's system prompt includes CLI guidance: when Bash is available, use `bash_cmd` and inspect `lark-cli --help` and subcommand help first. You can describe a Feishu task without repeating the CLI name; execution still depends on installation, credentials, and app permissions.
