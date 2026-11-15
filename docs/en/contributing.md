[Documentation](index.md) · [简体中文](../zh/contributing.md)

# Contributing

Read [AGENTS.md](https://github.com/nl8590687/lemonclaw/blob/main/AGENTS.md) for code and documentation constraints. Fork the repository, create a topic branch, and describe the problem, final behavior, and validation in your PR.

## Local development

```bash
python -m pip install -e '.[dev]' -c constraints.txt
python -m pytest -q
ruff check .
basedpyright
python -m build
```

Run these commands from the project root. Documentation-only changes should validate relative links, examples, and language parity; moving prose alone does not require the full application test suite.

## Documentation maintenance

READMEs serve first-time visitors; detailed usage and operations belong in `docs/`. Record development history, fixes, and validation in commits and PRs. Update both languages when behavior changes, and label unknown content “To be completed” rather than presenting it as available functionality.

## To be completed

Issue/PR templates, a contributor code of conduct, and a dedicated vulnerability reporting channel.
