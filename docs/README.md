# Documentation source / 文档源码

- [简体中文](zh/index.md)
- [English](en/index.md)
- [Website entry / 站点首页](index.md)

## Build locally / 本地构建

Run from the repository root / 在仓库根目录执行：

```bash
python -m pip install -r docs/requirements.txt
python -m mkdocs build --strict
python -m mkdocs serve
```

Open the URL printed by `mkdocs serve`; the preview includes the `/lemonclaw/` project path. Build output goes to `site/`, which is ignored by Git. Preview with a virtual environment separate from application dependencies.

打开 `mkdocs serve` 输出的地址，预览包含 `/lemonclaw/` 项目路径。生成文件位于 `site/`，已被 Git 忽略。建议使用独立虚拟环境安装文档依赖。

## GitHub Pages setup / 发布设置

1. Merge the documentation and workflow into `main` / 将文档和工作流合并到 `main`。
2. In repository **Settings → Pages → Build and deployment → Source**, select **GitHub Actions**. Do not select “Deploy from a branch” for the raw `docs/` Markdown.
3. Run the **Documentation** workflow on `main` if it did not run automatically. Subsequent pushes changing documentation on `main` trigger a build and deployment; pull requests only build and validate.
4. Use the successful deployment's URL to verify the home page, both languages, navigation, search, and assets. The expected default project URL is `https://nl8590687.github.io/lemonclaw/`; a configured workflow does not mean the site has already been published.

仓库首次需管理员在 Pages 设置中选择 **GitHub Actions**；如未自动触发，可在 Actions 中手动运行 `main` 的 **Documentation**。PR 只检查，合并到 main 后自动发布。部署成功后验收首页、中英文导航、搜索和资源加载，不能仅凭本地构建宣称已上线。

## Maintenance / 维护

Keep document sources in `docs/zh/` and `docs/en/` with matching pages. Update `mkdocs.yml` when changing navigation. Relative `.md` links work in the repository and are converted during the site build. Links to code or configuration outside `docs/` must use GitHub repository URLs because those files are not deployed.

中英文页面保持对应，导航在 `mkdocs.yml` 中维护。文档内部保留相对 `.md` 链接，由构建器转换为网页地址；指向 `docs/` 外的代码和配置使用 GitHub 链接，避免发布后指向不存在的站点路径。

See [AGENTS.md](https://github.com/nl8590687/lemonclaw/blob/main/AGENTS.md) for documentation rules. Development logs belong in commits and PRs.
