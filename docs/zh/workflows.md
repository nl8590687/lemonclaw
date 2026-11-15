[文档首页](index.md) · [English](../en/workflows.md)

# 🔀 多 Agent 工作流

节点 config 支持 `timeout_seconds`（默认 300 秒）、`max_retries`（默认 0）、指数退避 `retry_backoff`（默认 1 秒）以及 `on_error`（`fail`、`continue`、`compensate`）。补偿通过 `compensation` 声明 `tool_name` 与 `args`。仅对可安全重复的操作配置重试。取消在节点、模型与工具调用边界生效，并保留 checkpoint。超时的阻塞调用可能继续留在守护线程中，其结果会被丢弃，后续调用会被阻止；超时会明确报错，不自动重试或补偿。尚未结束的节点调用最多 32 个，容量占满时新节点明确报错。


简单查询由主 Agent 直接完成；多阶段调查、核验汇总和长任务优先使用后台 Workflow。使用 `workflow_list_defs` 检查可复用定义，`workflow_execute` 启动后返回 run_id，后续由事件回调继续处理。子 Agent 的可用工具和技能可在定义中单独指定。

周期业务可用 `create_cron_task(prompt="每日天气报告", cron_expression="0 9 * * *", workflow_id="daily_weather", workflow_input='{"city":"上海"}')` 绑定已定义的可复用 Workflow。每次触发创建独立 run，计划使用服务本地时区。`update_cron_task` 可更新绑定及输入，`workflow_id=""` 恢复提示词任务。


开启 `ENABLE_WORKFLOW` 后，可让主 Agent 定义、执行和管理多阶段工作流。工作流在后台运行，主 Agent 可以监督进展；需要用户决定时暂停，收到答复后继续。

### 核心能力

- **主 Agent 在回路** vs. **人在回路** — 两个独立的"回路参与者"：
  - **主 Agent 在回路**：主 Agent 是回路中的积极参与者。它可作为 `main_agent` 节点在流程执行中被回调（带完整会话记忆与工作流工具，实现动态递归）；也可**随时监督检查和控制调整**在途 run——不限于预定义回调点——通过监督命令（`/wf inspect`、`/wf inject`）与工具（`workflow_inspect_run`、`workflow_inject`）。这是"主 Agent 在回路中"，区别于被动的结果投递。
  - **人在回路**：`human` 节点暂停执行，**通过主 Agent** 通知用户（主 Agent 是人介入工作流的唯一界面——人不与子 Agent 直接交互，不"越级"）。`run_id` 在消息文本中双向携带；主 Agent 提取后调 `workflow_resume(run_id, 答复)` 续跑。
- **声明式 spec** — 通过单次 `workflow_define(name, description, spec)` 调用定义工作流（JSON：`state_schema` / `nodes` / `edges` / `conditionals`），无需代码生成。
- **子 Agent**（`subagent` 节点）— 声明工具集、系统提示与技能，每次执行使用独立会话。
- **超越 DAG** — 条件边支持 LLM 路由与状态字段路由，同时支持回环（`recursion_limit` 保护）。
- **持久化执行** — run 通过 `SqliteSaver` checkpoint 到唯一 `.lemonclaw/lemonclaw.db`。暂停的 run 跨进程重启仍可续跑（数小时/数天后）。
- **后台 Worker 池** — 工作流分段在有界线程池中执行（`WORKFLOW_WORKER_POOL_SIZE`，默认 4），主 Agent 循环永不阻塞。
- **一次性工作流** — spec 中标记 `"one_shot": true`，run 完成/出错后自动删除定义、全部 run 与 checkpoint。

### 三步构建与运行

**1. 定义** — 主 Agent 调 `workflow_define`，给出 JSON spec：

```json
{
  "state_schema": [{"name": "answer", "type": "str"}, {"name": "summary", "type": "str"}],
  "nodes": [
    {"name": "ask", "kind": "human", "config": {"question": "请确认搜索范围。", "output_field": "answer"}},
    {"name": "summarize", "kind": "subagent", "config": {"type": "general", "system_prompt": "你是一个摘要员。", "tools": ["bocha_search"], "task": "总结：{answer}", "output_field": "summary"}}
  ],
  "edges": [{"src": "START", "dst": "ask"}, {"src": "ask", "dst": "summarize"}, {"src": "summarize", "dst": "END"}]
}
```

**2. 执行** — 主 Agent 调 `workflow_execute("workflow_id")`。工作流在后台 Worker 线程中执行；遇 `human` 节点暂停，发 `LangGraphLoop` 消息给主 Agent（经既有消息总线——无特殊分发）。

**3. 续跑（HITL）** — 用户在消息文本中带上 `run_id` 答复（如 `wf_run_xxx 同意，限近一周`）。主 Agent 提取 `run_id`，调 `workflow_resume(run_id, 答复)` 续跑。

### 运行时管理

`/wf` 命令（输入 `/wf help` 查看完整列表）：`list`、`runs [status]`（active/running/paused/all）、`resume <id> <value>`、`cancel <id>`、`delete <id>`。主 Agent 也拥有 `workflow_list`（查运行/阻塞中的 run）、`workflow_inspect_run`、`workflow_inject` 工具。

> `python` 节点与沙箱机制**尚不支持**；待沙箱选型完成后与 skill 脚本系统统一支持。
