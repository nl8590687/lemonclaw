[Documentation](index.md) · [简体中文](../zh/skills.md)

# 🧩 Skills System

When `ENABLE_SKILLS=true` (default), LemonClaw turns reusable workflows into on-demand **skill packages**. Drop a skill folder under `.lemonclaw/skills/` and the agent can discover and load it at runtime.

### Skill package format (OpenClaw-compatible)

```
.lemonclaw/skills/<name>-<version>/
├── SKILL.md         # required - YAML frontmatter (name/description/tags) + markdown instructions
├── _meta.json       # optional - slug/version metadata
├── requirements.txt # optional - Python deps (enables run_skill_script for this skill)
├── package.json     # optional - Node deps
└── *.md             # optional - extra reference docs (appended to the loaded content)
```

`SKILL.md` frontmatter example:

```yaml
---
name: weekly-report
description: Generate a weekly work summary
tags: [report, work]
metadata:
  openclaw:
    emoji: 📊
    requires:
      env:
        - BOCHA_API_KEY   # skill declares required env vars
    primaryEnv: BOCHA_API_KEY
---
```

### How it works

- **Discovery** - on startup and `/skills reload`, the skill directory is scanned and metadata is indexed in the SQLite DB.
- **Routing** - the summary (name + description + tags) of all *available* skills is injected into the system prompt every turn, so the LLM can pick the right skill.
- **Activation** - the agent calls `load_skill(name)` to activate a skill; its full instructions are then injected every turn by the context middleware (not stored in message history, so context compression can't lose them).
- **LRU + unload** - at most `MAX_ACTIVE_SKILLS` (default 5) skills stay active (LRU eviction); the agent calls `unload_skill(name)` when done.
- **Hot reload** - add/modify/delete skill packages, run `/skills reload`, and changes take effect immediately without restarting.

### Sensitive parameters (API keys, etc.)

Skills declare required env vars in frontmatter. Configure them **once** in `.lemonclaw/.env`; `/skills reload` picks up new keys. A skill whose required env vars are missing is marked `⚠ missing config` and hidden from the agent. Use `${VAR}` placeholders in skill bodies so `http_request` can resolve them server-side instead of placing raw credentials in prompts. Scripts, shell access, and external responses still require appropriate permission and data handling; this is not a universal non-disclosure guarantee.

### Script skills (Python / Node)

If a skill ships a `requirements.txt` / `package.json`, install its deps once with `/skills setup <name>` (isolated venv / `node_modules`, China-friendly mirror defaults). Run scripts via the `run_skill_script` tool (gated by `ENABLE_SKILL_SCRIPT`, off by default; path-contained, no shell, cross-platform). The Docker image includes `node`/`npm`; source installations need to provide them separately.
