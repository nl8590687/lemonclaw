This file provides guidance to AI coding agents working with this repository.

## Project Overview
LemonClaw is an open-source, universal AI digital employee agent.

## Project Structure

```
|- .lemonclaw/    LemonClaw核心配置存储目录
|--- .env         LemonClaw环境变量配置文件
|--- .env.example LemonClaw环境变量配置文件样例文件
|--- lemonclaw.db LemonClaw全局Sqlite3数据库文件
|- agent/         Agent实现模块
|- channels/      输入输出设备和通道实现模块
|- dao/           数据库model和dao操作模块
|- config/        配置相关代码模块
|- docs/          中英文用户、运维和贡献者文档（zh/、en/）
|- webui/        Vue 3 + TypeScript 前端；dist/ 为构建产物，禁止提交
|- tests/         单元测试目录
|- loop.py        Agent Loop核心代码
|- main.py        启动入口代码
```

## Structure Design

## 约束
1. 实现代码之前，必须先了解当前项目的整体代码风格和架构设计，保持现在的设计不变 
2. 整个项目全局只能使用一个 sqlite数据库文件`.lemonclaw/lemonclaw.db`，不允许出现多个。
3. 不允许写重复代码，所有新增代码都要基于当前的代码结构设计，合并同类项，除非用户有新的明确要求。
4. 代码结构要清洗，设计要参考设计模式和设计原则的优秀最佳实践，例如抽象工厂模式、单例模式、单一职责原则、开闭原则等。
5. 目录和模块必须遵循其业务语义：`channels/device/` 中的模块对应具体设备或通道；某个通道的附属能力（如飞书消息表情回复）应归入该通道实现，不应作为同级设备模块。新增文件前先判断是否适合合并到现有模块。

6. 每次变更采用满足需求的最小改动。除非用户明确要求改变现有行为，必须保留原有功能、默认值、配置加载顺序和兼容性。新增能力优先在自身模块实现，共享模块仅加入必要的接入点。提交前检查差异并验证受影响的既有行为，避免顺手重构、格式化或改变无关模块。

7. Python 的 import 统一放在文件顶部（模块文档字符串及 `__future__` 导入之后），按标准库、第三方包、项目内依赖分组，组间空一行。新增或修改代码不得在函数或方法里放 import。遇到循环依赖，优先调整依赖方向，或在顶部导入模块并在使用时访问其成员。

## 文档结构与维护约束

1. `README.md`（英文）与 `README_ZH-CN.md`（中文）面向首次关注项目的用户，主体必须帮助读者快速理解项目、完成安装配置并验证首次使用。优先顺序为：项目定位、使用场景/核心能力、快速开始、文档导航、贡献和许可证。通常保持约 100～200 行；不得为凑行数删除必要的使用前提或安全边界。
2. 详细用户指南、配置/命令参考、部署运维和贡献者资料统一放在 `docs/`。`docs/README.md` 为语言入口，`docs/zh/index.md` 和 `docs/en/index.md` 为对应导航。新增能力先判断应更新哪个现有页面，不得持续在 README 末尾追加章节，尤其不得在许可证后追加功能说明。
3. README 只保留首次上手需要的最小示例和详细文档链接。实现原理归入架构/贡献者资料；完整参数、协议过程及内部工具调用约定不得挤占快速开始。开发过程、任务记录、修复经过、测试运行结果、阶段总结等开发日志写入 Git 提交信息及 PR，不写进 README、用户文档或 AGENTS.md。稳定的行为、限制和操作方法仍应作为产品文档保留。
4. 中英文入口和功能文档使用对应结构；行为或配置变更必须同步更新两种语言、示例与导航。无法确认的内容标注“待补充 / To be completed”，注明缺少的资料，不得编造已支持能力、性能数据、发布版本、截图或站点地址。
5. 文档以当前代码、配置模板和发布流程为依据。示例使用明确占位凭证，不提交真实密钥。操作步骤须包含前置条件、配置准备、执行和成功判定；区分源码/容器、终端交互/后台服务及 Windows/Unix 命令。不要承诺未经验证的隔离、安全、备份一致性或版本兼容性。
6. 文档站与仓库共用 `docs/` 中的内容，避免复制维护另一套手册。未来 Pages 构建输出不提交到 main；发布配置与实际上线需明确区分，不把未部署网站写成可访问入口。
7. 文档改动检查相对链接、图片路径、导航、中英文对应关系及代码示例；站点配置存在时执行相应构建检查。纯排版或文档迁移无需重复运行完整业务测试；文档不得为通过链接检查而指向不存在的目标。

8. 本仓库文档站采用 MkDocs：入口为 `docs/index.md`，导航及项目路径在根目录 `mkdocs.yml` 中配置，依赖为 `docs/requirements.txt`。文档内部链接保持相对 `.md` 地址；指向 `docs/` 外的源码/配置使用 GitHub 链接，避免生成站点后失效。改动必须通过 `python -m mkdocs build --strict`；工作流 `.github/workflows/docs.yml` 对 PR 只构建，对 main 发布。Pages 设置必须选择 GitHub Actions；不得把原始 Markdown 目录当作已经生成的 HTML 网站发布。

## WebUI 维护约束

WebUI 复用唯一主 Agent、现有管理器及 SQLite；前端不得另造会话或执行引擎。前端改动执行 `cd webui && npm ci && npm run build`，本地运行顺序为构建后再 `python main.py`。静态目录缺失仅关闭 WebUI。配置管理写应用 `.lemonclaw/.env`，未知变量保留，敏感值脱敏；不得改成 Docker 参数配置或强制重启进程。界面文案放入 i18n，至少同步中英文。
