# WebUI

The personal WebUI shares LemonClaw's single main conversation with the terminal and Feishu. It displays the current checkpoint context; it is not a complete conversation archive. Workflow runs retain separate checkpoints.

## Build and start

Install Node.js 24 and the Python dependencies described in [Quick start](getting-started.md). From the repository:

```bash
cd webui
npm ci --include=dev
npm run build
cd ..
python main.py
```

The build requires frontend development dependencies such as `vue-tsc`. If `npm run build` cannot find `vue-tsc`, run `npm ci --include=dev` again from `webui` and retry the build once installation succeeds. The commands above also work in Windows Command Prompt.

Open `http://127.0.0.1:8080`. An absent `webui/dist/index.html` disables only the WebUI. Rebuild after changing frontend sources. Build output and `node_modules` must remain untracked.

The application reads `.lemonclaw/.env` itself. These are application settings, not a Docker `--env-file`:

```dotenv
ENABLE_WEBUI=true
WEBUI_HOST=127.0.0.1
WEBUI_PORT=8080
WEBUI_AUTH_KEY=
```

On the first WebUI startup an empty key is replaced with a random value and saved to the application `.env`. Obtain `WEBUI_AUTH_KEY` locally from that file and enter it in the login page, or open `http://127.0.0.1:8080/?key=YOUR_KEY`. The frontend immediately removes the key from the URL. Avoid sharing that URL. The server exchanges the key for an HttpOnly browser cookie. The key remains valid until manually changed; changing it invalidates existing browser sessions. Logout revokes that browser's cookie.

## Containers

The Dockerfile builds the Vue frontend in a Node stage and copies the static files into the Python runtime. No host-side frontend build is required. Set `WEBUI_HOST=0.0.0.0` in the mounted **application** `.lemonclaw/.env` to expose the container listener. For local-only access:

```bash
docker build -t lemonclaw:webui .
docker run --name lemonclaw -p 127.0.0.1:8080:8080 \
  -v "$PWD/.lemonclaw:/root/.lemonclaw" lemonclaw:webui
```

The existing webhook port remains separate. For remote access, configure HTTPS on a reverse proxy and preserve the request host; the API checks same-origin mutations. The WebUI controls the same tools and files as the Agent, so restrict access to the owner.

Live updates use SSE at `/api/v1/events`. Nginx honors the application's `X-Accel-Buffering: no` header by default. If the proxy ignores that header, set `proxy_buffering off` for this route.

## Conversation and management

- Chat streams public replies, accepts images/files, and shows pending human questions. While WebUI is active, the terminal also displays shared questions and their final status. The first valid answer from the terminal, Feishu, or WebUI wins. Failed Feishu card updates are retried.
- Settings displays program defaults and preserves untouched values. Secret fields are masked: an empty edit preserves the value; use **Clear** for explicit clearing. Custom/Skill variables have a separate section, including unknown `.env` keys.
- Configuration is written atomically to `.env`. Existing calls finish with their captured arguments; subsequent model/tool calls use current settings. Listeners rebind independently; Agent resources are replaced at an idle boundary without restarting the process. After changing the port, open the new address. A conflicting configuration revision requires refreshing before saving.
- Workflows has a node canvas, connections, node parameter dialogs, state-field/reducer editor, conditional route editor, JSON representation, layout persistence, undo/redo and run inspection. LLM, tool, subagent, main Agent, human and subgraph nodes use the existing backend schema and validation. Run inspection shows persisted node states and checkpoint data; refresh it to update.
- Cron schedules, MCP connections and persistent memories are managed through the existing managers and database. MCP supports HTTP, SSE and stdio; omitted credentials are preserved. Connection failures remain visible as connection status rather than a successful connection claim.
- Skills accepts a ZIP with `SKILL.md` at its root or inside one top-level directory. Preview and installation are separate. Upload never executes dependencies; dependency installation is a separate explicit action. Referenced Skills cannot be deleted or replaced.

Changing a workflow affects future runs. While WebUI is active, new runs store the workflow and child definitions used when they started. Running/referenced workflow deletion is rejected. Graph validation rejects unsupported fields rather than silently dropping them. The current backend spec does not expose arbitrary Python nodes or all LangGraph SDK APIs; consult [Workflows](workflows.md) for the supported execution model.

The frontend locale catalogs are in `webui/src/i18n/locales/`; new locales can be registered in `webui/src/i18n/index.ts`. English is the fallback. The navigation and forms adapt to narrow screens; complex graphs can also be edited through their node list and JSON representation.

## Workflow semantics

| Capability | Persisted definition and editor |
| --- | --- |
| State and reducers | `state_schema`; state-field dialog, with `overwrite`, `append`, `add_messages` |
| Sequence / parallel fan-out | Multiple `edges`; draw and edit connections |
| Wait-all join | An edge with `src: ["branch_a", "branch_b"]`; connection dialog selects all required sources |
| Conditional / cyclic flow | `conditionals` with `state_field` or `llm` router; route labels and target selection, existing recursion limit |
| Nested workflows | `sub_workflow_id`; child definition snapshots and nested checkpoint namespaces |
| Human / main Agent handoff | `human` / `main_agent` nodes; persistent pause, inspect and resume |
| Failure handling | Node timeout, retries, backoff, `on_error`, tool compensation; node dialog |

JSON editing preserves the complete backend spec. Arbitrary SDK reducers, executable Python nodes and dynamic `Send` expressions are not part of this declarative schema and cannot be saved as pretend UI options.

## Troubleshooting

- Login screen missing: build `webui/dist` and check the configured host/port and server logs.
- Cannot reach the container: configure `WEBUI_HOST=0.0.0.0` in the mounted application file and publish port 8080.
- Authentication rejected: use the current key from the application's `.env`; changing it revokes old cookies.
- Management reports busy: wait until the current main Agent turn reaches an idle boundary, then retry.
- Browser reconnects: SSE resumes from its last event ID; retained events are bounded and a replay gap triggers context refresh. Closing the browser does not stop the Agent.
