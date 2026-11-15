[文档首页](index.md) · [English](../en/skills.md)

# 🧩 技能系统

当 `ENABLE_SKILLS=true`（默认）时，LemonClaw 把可复用的工作流封装为按需加载的**技能包**。把技能目录放入 `.lemonclaw/skills/`，Agent 即可在运行时发现并加载。

### 技能包格式（OpenClaw 兼容）

```
.lemonclaw/skills/<name>-<version>/
├── SKILL.md         # 必需 - YAML frontmatter（name/description/tags）+ markdown 指令
├── _meta.json       # 可选 - slug/version 元数据
├── requirements.txt # 可选 - Python 依赖（启用该技能的 run_skill_script）
├── package.json     # 可选 - Node 依赖
└── *.md             # 可选 - 附带参考文档（追加到加载内容后）
```

`SKILL.md` frontmatter 样例：

```yaml
---
name: weekly-report
description: 生成每周工作总结
tags: [report, work]
metadata:
  openclaw:
    emoji: 📊
    requires:
      env:
        - BOCHA_API_KEY   # 声明所需环境变量
    primaryEnv: BOCHA_API_KEY
---
```

### 工作机制

- **发现** - 启动时与 `/skills reload` 时扫描技能目录，元数据索引到 SQLite 库。
- **路由** - 每轮将所有*可用*技能的摘要（name + description + tags）注入系统提示，供 LLM 选择。
- **激活** - Agent 调用 `load_skill(name)` 激活技能；其完整指令随后由上下文中间件每轮注入（不进消息历史，不会被上下文压缩丢失）。
- **LRU + 卸载** - 最多 `MAX_ACTIVE_SKILLS`（默认 5）个技能同时活跃（LRU 淘汰）；用完后 Agent 调 `unload_skill(name)` 卸载。
- **热加载** - 新增/修改/删除技能包后执行 `/skills reload`，立即生效，无需重启。

### 敏感参数（API Key 等）

技能在 frontmatter 声明所需环境变量。在 `.lemonclaw/.env` 中**配置一次**即永久生效；`/skills reload` 拾取新增密钥。缺配置的技能标 `⚠ 缺配置` 且不向 Agent 暴露。技能正文应使用 `${VAR}` 占位符，由 `http_request` 在服务端替换，避免主动把原值写入提示词。脚本、Shell 和外部响应仍应按实际权限与数据流管理，不能保证任何场景都不会暴露密钥。

### 脚本技能（Python / Node）

若技能含 `requirements.txt` / `package.json`，用 `/skills setup <name>` 一次性安装依赖（隔离 venv / `node_modules`，默认国内镜像）。通过 `run_skill_script` 工具执行脚本（受 `ENABLE_SKILL_SCRIPT` 控制，默认关闭；路径围栏、无 shell、跨平台）。Docker 镜像已预装 `node`/`npm`；源码部署时需自行安装。
