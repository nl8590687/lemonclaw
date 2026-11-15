[Documentation](index.md) · [简体中文](../zh/workflows.md)

# 🔀 Multi-Agent Workflow

Node configs support `timeout_seconds` (default 300), `max_retries` (default 0), exponential `retry_backoff` (default 1 second), and `on_error` (`fail`, `continue`, or `compensate`). Compensation declares a `compensation` object with `tool_name` and `args`. Configure retries only for operations safe to repeat. Cancellation stops execution at node/model/tool boundaries and retains checkpoints. A timed-out blocking call may continue in its daemon thread; its result is discarded, further calls are blocked, and the timeout is reported without retry or compensation. Outstanding node calls are capped at 32; new nodes fail explicitly when that capacity is occupied.


The main agent handles short queries directly and prefers background Workflows for multi-stage research, verification, and long tasks. Use `workflow_list_defs` to find reusable definitions; `workflow_execute` returns a run ID and follow-up events continue the interaction. Sub-agent definitions can specify their tools and skills separately.

Schedule a reusable definition with `create_cron_task(prompt="Daily weather report", cron_expression="0 9 * * *", workflow_id="daily_weather", workflow_input='{"city":"Shanghai"}')`. Each trigger creates an independent run using the service's local timezone. `update_cron_task` updates the binding or inputs; `workflow_id=""` restores prompt execution.


With `ENABLE_WORKFLOW` enabled, the main agent can define, execute, and manage multi-stage workflows. Work runs in the background while the main agent supervises; human decisions pause execution until an answer is received.

### Key capabilities

- **Main agent in the loop** vs. **Human in the loop** — two independent "loop participants":
  - **Main agent in the loop**: the main agent is an active participant. It can be called back as a `main_agent` node during execution (with full session memory and workflow tools, enabling dynamic recursion). It can also **inspect, control, and adjust** in-flight runs **at any time** — not just at predefined callback points — via supervisor commands (`/wf inspect`, `/wf inject`) and tools (`workflow_inspect_run`, `workflow_inject`). This is the "main-agent-in-the-loop", distinct from passive result delivery.
  - **Human in the loop**: `human` nodes pause execution and notify the user **through the main agent** (the main agent is the human's sole interface — humans never interact with sub-agents directly). The `run_id` is carried in the message text bidirectionally; the main agent extracts it and calls `workflow_resume(run_id, answer)`.
- **Declarative specs** — define workflows via a single `workflow_define(name, description, spec)` call (JSON: `state_schema` / `nodes` / `edges` / `conditionals`). No code generation required.
- **Sub-agents** (`subagent` nodes) — curated tools, a custom system prompt, declared skills, and a fresh conversation for each run. 
- **Beyond DAG** — conditional edges support LLM-based and state-field routing, plus cyclic loops (with `recursion_limit` protection).
- **Persistent execution** — runs are checkpointed via `SqliteSaver` in the single `.lemonclaw/lemonclaw.db`. Paused runs survive process restarts and can be resumed hours/days later.
- **Background worker pool** — workflow segments execute in a bounded thread pool (`WORKFLOW_WORKER_POOL_SIZE`, default 4) while allowing the main agent to receive later events.
- **One-shot workflows** — mark `"one_shot": true` in the spec and the definition, runs, and checkpoints are auto-cleaned on completion.

### Define and run in 3 steps

**1. Define** — the main agent calls `workflow_define` with a JSON spec:

```json
{
  "state_schema": [{"name": "answer", "type": "str"}, {"name": "summary", "type": "str"}],
  "nodes": [
    {"name": "ask", "kind": "human", "config": {"question": "Please confirm the scope.", "output_field": "answer"}},
    {"name": "summarize", "kind": "subagent", "config": {"type": "general", "system_prompt": "You are a summarizer.", "tools": ["bocha_search"], "task": "Summarize: {answer}", "output_field": "summary"}}
  ],
  "edges": [{"src": "START", "dst": "ask"}, {"src": "ask", "dst": "summarize"}, {"src": "summarize", "dst": "END"}]
}
```

**2. Execute** — the main agent calls `workflow_execute("workflow_id")`. The workflow runs in a background worker thread; on a `human` node it pauses and sends a `LangGraphLoop` message to the main agent (via the normal message bus — no special dispatch).

**3. Resume (HITL)** — the user replies with the `run_id` in the text (e.g. `wf_run_xxx agreed, limit to one week`). The main agent extracts the `run_id` and calls `workflow_resume(run_id, answer)` to continue.

### Manage at runtime

`/wf` commands (type `/wf help` for the full list): `list`, `runs [status]` (active/running/paused/all), `resume <id> <value>`, `cancel <id>`, `delete <id>`. The main agent also has `workflow_list` (list active/paused runs), `workflow_inspect_run`, and `workflow_inject` tools.

> `python` nodes and the sandbox mechanism are **not implemented** in this release; they will be added later under a shared sandbox with the skill script system.
