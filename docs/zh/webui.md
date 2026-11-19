# WebUI

个人 WebUI 与终端、飞书共用唯一主会话，显示当前 checkpoint 中的上下文，并非全部历史归档。工作流运行仍使用各自独立的 checkpoint。

## 构建与启动

先安装 Node.js 24 及[快速开始](getting-started.md)中的 Python 依赖，在项目目录执行：

```bash
cd webui
npm ci --include=dev
npm run build
cd ..
python main.py
```

构建依赖 `vue-tsc` 等前端开发依赖。如果 `npm run build` 提示找不到 `vue-tsc`，在 `webui` 目录重新运行 `npm ci --include=dev`，安装成功后再构建。Windows CMD 也可使用上述命令。

访问 `http://127.0.0.1:8080`。没有 `webui/dist/index.html` 时仅关闭 WebUI，其他通道继续运行。修改前端后重新构建，构建产物和 `node_modules` 不提交到 Git。

程序自行读取 `.lemonclaw/.env`，以下是应用配置，并非 Docker 的 `--env-file`：

```dotenv
ENABLE_WEBUI=true
WEBUI_HOST=127.0.0.1
WEBUI_PORT=8080
WEBUI_AUTH_KEY=
```

首次启动 WebUI 时，空 key 会被随机值替换并写入应用 `.env`。在本机查看该文件的 `WEBUI_AUTH_KEY`，在登录页输入，或打开 `http://127.0.0.1:8080/?key=你的KEY`。前端会立即移除 URL 中的 key，请勿传播此链接。服务端验证后使用 HttpOnly Cookie 保持浏览器登录。key 长期有效，手动更换后已有浏览器授权失效；退出登录仅撤销当前浏览器的授权。

## 容器部署

Dockerfile 在 Node 构建阶段编译 Vue，再将静态文件复制到 Python 运行镜像，无需在宿主机预先构建。容器访问需在挂载的**应用** `.lemonclaw/.env` 中设置 `WEBUI_HOST=0.0.0.0`。只允许宿主机本地访问的示例：

```bash
docker build -t lemonclaw:webui .
docker run --name lemonclaw -p 127.0.0.1:8080:8080 \
  -v "$PWD/.lemonclaw:/root/.lemonclaw" lemonclaw:webui
```

Webhook 端口仍独立。远程访问可用反向代理提供 HTTPS，并保留请求 Host；API 会校验写操作来源。WebUI 能操作 Agent 的工具和文件，访问权限应限于主人。

## 会话与管理

- 对话流式显示公开回复，支持图片、文件及人工确认。WebUI 启用时，终端也会显示同一问题和结束状态。终端、飞书、WebUI 三端的首个有效答案生效。飞书卡片更新失败会重试。
- 设置显示程序默认值，保留未修改值。敏感字段脱敏，输入框留空表示不改，明确清空需点“清空”。自定义/Skill 变量有独立区域，未知 `.env` 参数也保留在此。
- 配置原子写入 `.env`。当前调用使用已取得的参数完成，后续模型/工具调用使用新值；监听器独立切换，Agent 资源在空闲边界替换，不重启进程。修改端口后请打开新地址。配置版本冲突时需刷新后重试。
- 工作流提供节点画布、连线、节点参数弹窗、状态字段及合并规则编辑、条件路由编辑、JSON 表达、布局保存、撤销/重做和运行查看。LLM、工具、子 Agent、主 Agent、人工及子图节点使用既有后端 schema 和校验。运行详情展示持久化节点状态及 checkpoint 数据，刷新可更新。
- 定时任务、MCP 连接和持久记忆复用既有管理器及数据库。MCP 支持 HTTP、SSE、stdio，未填写的凭证保留原值；连接失败会显示状态，不把配置保存当成连接成功。
- Skill 上传 ZIP，要求根目录或单个一级子目录中包含 `SKILL.md`。预览、安装分别操作；上传不会执行依赖脚本，安装依赖需要单独操作。被工作流引用的 Skill 无法删除或替换。

修改工作流影响后续运行；WebUI 启用期间启动的运行会保存当时的主图及子图定义。活动运行或其他定义引用的工作流不能删除。后端拒绝不支持的字段，不会静默丢弃。当前 spec 并不开放任意 Python 节点或 LangGraph SDK 的全部 API，支持的执行模型见[工作流](workflows.md)。

前端语言目录为 `webui/src/i18n/locales/`，新增语言需在 `webui/src/i18n/index.ts` 注册，缺失项回退英语。导航和表单适配窄屏，复杂图也可通过节点列表及 JSON 编辑。

## 工作流语义

| 能力 | 持久化定义与界面入口 |
| --- | --- |
| 状态与合并 | `state_schema`；状态字段弹窗，支持 `overwrite`、`append`、`add_messages` |
| 串行 / 并行分发 | 多条 `edges`；画布连线及编辑 |
| 等待所有分支汇合 | `src: ["branch_a", "branch_b"]` 的边；连线弹窗选择必须完成的来源节点 |
| 条件 / 回环 | `conditionals` 的 `state_field` 或 `llm` 路由；分支名、目标编辑及既有递归上限 |
| 子工作流 | `sub_workflow_id`；子图定义快照及嵌套 checkpoint 命名空间 |
| 人工 / 主 Agent 回填 | `human` / `main_agent` 节点；持久暂停、查看及恢复 |
| 失败处理 | 节点超时、重试、退避、`on_error`、工具补偿；节点弹窗 |

JSON 编辑保留后端完整 spec。任意 SDK reducer、可执行 Python 节点和动态 `Send` 表达式不在当前声明式 schema 中，不会作为假选项保存。

## 排障

- 无法打开登录页：先构建 `webui/dist`，检查监听地址、端口及服务日志。
- 容器无法访问：在挂载的应用文件中设置 `WEBUI_HOST=0.0.0.0`，并映射 8080 端口。
- 认证失败：使用应用 `.env` 的当前 key；更换 key 后旧 Cookie 失效。
- 管理操作提示忙碌：等待当前主 Agent 任务进入空闲边界后重试。
- 浏览器重连：SSE 从最后事件 ID 恢复；事件保留数量有限，发现缺口会刷新上下文。关闭浏览器不会停止 Agent。
