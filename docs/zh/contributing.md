[文档首页](index.md) · [English](../en/contributing.md)

# 贡献指南

先阅读 [AGENTS.md](https://github.com/nl8590687/lemonclaw/blob/main/AGENTS.md) 的代码和文档维护约束。Fork 后创建主题分支，保持修改范围清晰，在 PR 说明问题、最终行为和验证结果。

## 本地开发

```bash
python -m pip install -e '.[dev]' -c constraints.txt
python -m pytest -q
ruff check .
basedpyright
python -m build
```

以上命令在项目根目录执行。纯文档修改检查相对链接、示例与中英文一致性；不需要仅为移动文档运行整套业务测试。

## 文档维护

README 面向首次访问者；详细使用与运维说明放在 `docs/`。开发经过、修复记录及验证结果写在 Git 提交信息和 PR。改动涉及用户行为时，同步更新对应中英文说明；未知内容明确写“待补充”，不要写成已经支持。

## 待补充

Issue/PR 模板、贡献者行为准则和独立漏洞报告渠道。
