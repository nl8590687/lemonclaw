<script setup lang="ts">
import { ref, onMounted, computed, watch } from "vue";
import { VueFlow, MarkerType } from "@vue-flow/core";
import { Background } from "@vue-flow/background";
import { Controls } from "@vue-flow/controls";
import { MiniMap } from "@vue-flow/minimap";
import { useI18n } from "vue-i18n";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "./api";
const { t } = useI18n(),
  items = ref<any[]>([]),
  catalog = ref<any>({
    tools: [],
    skills: [],
    node_schema: { properties: {} },
  }),
  current = ref<any>(null),
  nodes = ref<any[]>([]),
  edges = ref<any[]>([]),
  dialog = ref(false),
  draft = ref<any>({ config: {} }),
  oldId = ref(""),
  jsonDialog = ref(false),
  jsonText = ref(""),
  edgeDialog = ref(false),
  edgeDraft = ref<any>({}),
  runs = ref<any[]>([]),
  runsDialog = ref(false),
  runDetail = ref<any>(null),
  dirty = ref(false);
const history = ref<string[]>([]),
  future = ref<string[]>([]),
  stateDialog = ref(false),
  stateFields = ref<any[]>([]),
  runNodes = ref<any[]>([]),
  runEdges = ref<any[]>([]);
function checkpoint() {
  syncLayout();
  history.value.push(JSON.stringify(current.value));
  history.value = history.value.slice(-50);
  future.value = [];
}
function undo() {
  if (!history.value.length) return;
  future.value.push(JSON.stringify(current.value));
  current.value = JSON.parse(history.value.pop()!);
  render();
  dirty.value = true;
}
function redo() {
  if (!future.value.length) return;
  history.value.push(JSON.stringify(current.value));
  current.value = JSON.parse(future.value.pop()!);
  render();
  dirty.value = true;
}
function editState() {
  stateFields.value = JSON.parse(
    JSON.stringify(current.value.spec.state_schema || []),
  );
  stateDialog.value = true;
}
function saveState() {
  checkpoint();
  current.value.spec.state_schema = stateFields.value;
  stateDialog.value = false;
  dirty.value = true;
}
const kinds = ["llm", "tool", "subagent", "main_agent", "human", "subgraph"];
const fieldsByKind: any = {
  llm: ["prompt", "output_field", "image_ids", "image_ids_field"],
  tool: ["tool_name", "args", "output_field"],
  subagent: [
    "type",
    "system_prompt",
    "task",
    "task_template",
    "tools",
    "skills",
    "output_field",
    "image_ids",
    "image_ids_field",
  ],
  main_agent: ["task", "summary", "output_field"],
  human: ["question", "handler", "output_field"],
  subgraph: ["sub_workflow_id", "output_field"],
};
const configFields = computed(() => [
  ...(fieldsByKind[draft.value.kind] || []),
  "timeout_seconds",
  "max_retries",
  "retry_backoff",
  "on_error",
  "compensation",
]);
const schema = computed(() => catalog.value.node_schema.properties || {});
function showToolSchema() {
  return catalog.value.tools.find(
    (v: any) => v.name === draft.value.config.tool_name,
  )?.schema;
}
function stringify(v: any) {
  return typeof v === "string" ? v : JSON.stringify(v, null, 2);
}
function setParam(k: string, v: any) {
  const type = schema.value[k]?.type;
  if (
    type === "array" ||
    type === "object" ||
    k === "compensation" ||
    k === "args"
  ) {
    try {
      draft.value.config[k] = v ? JSON.parse(v) : null;
    } catch {
      draft.value.config[k] = v;
    }
  } else draft.value.config[k] = v;
}
async function load() {
  items.value = await api("manage/workflows");
  catalog.value = await api("manage/catalog");
}
function defaultSpec() {
  return {
    spec_version: 1,
    state_schema: [{ name: "answer", type: "str" }],
    nodes: [
      {
        name: "respond",
        kind: "llm",
        config: { prompt: "{answer}", output_field: "answer" },
      },
    ],
    edges: [
      { src: "START", dst: "respond" },
      { src: "respond", dst: "END" },
    ],
    conditionals: [],
  };
}
async function select(w: any) {
  if (
    dirty.value &&
    !(await ElMessageBox.confirm(t("unsaved"))
      .then(() => true)
      .catch(() => false))
  )
    return;
  current.value = w.workflow_id
    ? await api("manage/workflows/" + w.workflow_id)
    : JSON.parse(JSON.stringify(w));
  history.value = [];
  future.value = [];
  render();
  dirty.value = false;
}
function render() {
  const spec = current.value.spec;
  const positions = current.value.layout || {};
  nodes.value = [
    { name: "START", kind: "start" },
    ...spec.nodes,
    { name: "END", kind: "end" },
  ].map((n: any, i: number) => ({
    id: n.name,
    position: positions[n.name] || {
      x: 120 + (i % 3) * 250,
      y: 70 + Math.floor(i / 3) * 150,
    },
    label: n.name + " · " + n.kind,
    type:
      n.name === "START" ? "input" : n.name === "END" ? "output" : "default",
    data: n,
  }));
  edges.value = spec.edges.flatMap((e: any, i: number) =>
    (Array.isArray(e.src) ? e.src : [e.src]).map((src: string) => ({
      id: "e" + i + ":" + src,
      source: src,
      target: e.dst,
      label: Array.isArray(e.src) ? t("join") : "",
      data: { index: i, join: Array.isArray(e.src) },
      markerEnd: MarkerType.ArrowClosed,
    })),
  );
  for (const [i, c] of (spec.conditionals || []).entries())
    for (const [key, dst] of Object.entries(c.mapping))
      edges.value.push({
        id: `c${i}:${key}`,
        source: c.src,
        target: dst,
        label: key,
        animated: true,
        markerEnd: MarkerType.ArrowClosed,
        data: { conditional: i, route: key },
      });
}
function beginNode(node?: any) {
  if (node && ["START", "END"].includes(node.id)) return;
  oldId.value = node?.id || "";
  draft.value = JSON.parse(
    JSON.stringify(
      node?.data || {
        name: "node_" + (current.value.spec.nodes.length + 1),
        kind: "llm",
        config: {},
      },
    ),
  );
  dialog.value = true;
}
function commitNode() {
  const id = draft.value.name;
  if (
    !/^[A-Za-z_][A-Za-z0-9_-]*$/.test(id) ||
    ["START", "END"].includes(id) ||
    current.value.spec.nodes.some(
      (n: any) => n.name === id && n.name !== oldId.value,
    )
  ) {
    ElMessage.error(t("nameConflict"));
    return;
  }
  checkpoint();
  const spec = current.value.spec;
  const idx = spec.nodes.findIndex((n: any) => n.name === oldId.value);
  if (idx < 0) spec.nodes.push(draft.value);
  else {
    spec.nodes[idx] = draft.value;
    spec.edges.forEach((e: any) => {
      if (Array.isArray(e.src))
        e.src = e.src.map((v: string) => (v === oldId.value ? id : v));
      else if (e.src === oldId.value) e.src = id;
      if (e.dst === oldId.value) e.dst = id;
    });
    (spec.conditionals || []).forEach((c: any) => {
      if (c.src === oldId.value) c.src = id;
      for (const k in c.mapping)
        if (c.mapping[k] === oldId.value) c.mapping[k] = id;
    });
  }
  syncLayout();
  render();
  dirty.value = true;
  dialog.value = false;
}
async function deleteNode() {
  if (
    !(await ElMessageBox.confirm(t("nodeDelete"))
      .then(() => true)
      .catch(() => false))
  )
    return;
  checkpoint();
  const id = oldId.value,
    spec = current.value.spec;
  spec.nodes = spec.nodes.filter((n: any) => n.name !== id);
  spec.edges = spec.edges
    .map((e: any) => ({
      ...e,
      src: Array.isArray(e.src) ? e.src.filter((v: string) => v !== id) : e.src,
    }))
    .filter(
      (e: any) =>
        e.src !== id && e.dst !== id && (!Array.isArray(e.src) || e.src.length),
    );
  spec.conditionals = (spec.conditionals || []).filter(
    (c: any) => c.src !== id,
  );
  spec.conditionals.forEach((c: any) => {
    for (const key in c.mapping)
      if (c.mapping[key] === id) delete c.mapping[key];
  });
  render();
  dirty.value = true;
  dialog.value = false;
}
function connect(p: any) {
  checkpoint();
  current.value.spec.edges.push({ src: p.source, dst: p.target });
  syncLayout();
  render();
  dirty.value = true;
}
function syncLayout() {
  current.value.layout = Object.fromEntries(
    nodes.value.map((n) => [n.id, n.position]),
  );
}
function editEdge(edge: any) {
  edgeDraft.value = JSON.parse(JSON.stringify(edge));
  edgeDraft.value.route = edge.data?.route || "";
  edgeDraft.value.joinSources = edge.data?.join
    ? [...current.value.spec.edges[edge.data.index].src]
    : [edge.source];
  edgeDraft.value.router = JSON.parse(
    JSON.stringify(
      edge.data?.conditional !== undefined
        ? current.value.spec.conditionals[edge.data.conditional].router
        : { kind: "state_field", field: "" },
    ),
  );
  edgeDialog.value = true;
}
function deleteEdge() {
  checkpoint();
  const edge = edgeDraft.value,
    spec = current.value.spec;
  if (edge.data?.conditional !== undefined) {
    const c = spec.conditionals[edge.data.conditional];
    delete c.mapping[edge.data.route];
    if (!Object.keys(c.mapping).length)
      spec.conditionals.splice(edge.data.conditional, 1);
  } else spec.edges.splice(edge.data.index, 1);
  syncLayout();
  render();
  dirty.value = true;
  edgeDialog.value = false;
}
function saveEdge() {
  checkpoint();
  const edge = edgeDraft.value,
    spec = current.value.spec;
  if (!edge.route && edge.data?.conditional === undefined) {
    const sources = edge.joinSources?.length ? edge.joinSources : [edge.source];
    spec.edges[edge.data.index] = {
      src: sources.length > 1 ? sources : sources[0],
      dst: edge.target,
    };
  } else if (!edge.route) {
    const c = spec.conditionals[edge.data.conditional];
    delete c.mapping[edge.data.route];
    if (!Object.keys(c.mapping).length)
      spec.conditionals.splice(edge.data.conditional, 1);
    spec.edges.push({ src: edge.source, dst: edge.target });
  } else if (edge.route) {
    if (edge.data?.conditional === undefined) {
      spec.edges.splice(edge.data.index, 1);
      spec.conditionals ||= [];
      let c = spec.conditionals.find((x: any) => x.src === edge.source);
      if (!c) {
        c = { src: edge.source, router: edge.router, mapping: {} };
        spec.conditionals.push(c);
      }
      c.mapping[edge.route] = edge.target;
      c.router = edge.router;
    } else {
      const c = spec.conditionals[edge.data.conditional];
      delete c.mapping[edge.data.route];
      c.mapping[edge.route] = edge.target;
      c.router = edge.router;
    }
  }
  syncLayout();
  render();
  dirty.value = true;
  edgeDialog.value = false;
}
async function save() {
  try {
    syncLayout();
    const w = await api(
      "manage/workflows" +
        (current.value.workflow_id ? "/" + current.value.workflow_id : ""),
      current.value.workflow_id ? "PUT" : "POST",
      current.value,
    );
    current.value = { ...w, layout: current.value.layout };
    dirty.value = false;
    await load();
    ElMessage.success(t("saved"));
  } catch (e) {
    ElMessage.error(String(e));
  }
}
async function remove() {
  if (
    !(await ElMessageBox.confirm(t("deleteConfirm"))
      .then(() => true)
      .catch(() => false))
  )
    return;
  try {
    await api("manage/workflows/" + current.value.workflow_id, "DELETE");
    current.value = null;
    dirty.value = false;
    await load();
  } catch (e) {
    ElMessage.error(String(e));
  }
}
async function run() {
  try {
    const { value } = await ElMessageBox.prompt(t("runInput"), t("run"), {
      inputValue: "{}",
      inputType: "textarea",
    });
    await api("manage/workflows/" + current.value.workflow_id, "POST", {
      action: "run",
      input: JSON.parse(value),
    });
    await showRuns();
  } catch (e) {
    if (e !== "cancel") ElMessage.error(String(e));
  }
}
async function showRuns() {
  runs.value = await api("manage/runs");
  runsDialog.value = true;
}
async function detailRun(r: any) {
  runDetail.value = await api("manage/runs/" + r.run_id);
  const snapshot = runDetail.value.snapshot?.spec;
  runNodes.value = (snapshot?.nodes || []).map((n: any, i: number) => ({
    id: n.name,
    label:
      n.name + " · " + (runDetail.value.nodes?.[n.name]?.status || "pending"),
    position: { x: 80 + (i % 3) * 230, y: 50 + Math.floor(i / 3) * 120 },
    style: {
      borderColor:
        (
          {
            completed: "#159b70",
            failed: "#db4545",
            running: "#408cff",
            paused: "#d89b22",
          } as any
        )[runDetail.value.nodes?.[n.name]?.status] || "#cbd5e1",
    },
  }));
  runEdges.value = (snapshot?.edges || [])
    .filter(
      (e: any) =>
        !["START", "END"].includes(e.src) && !["START", "END"].includes(e.dst),
    )
    .map((e: any, i: number) => ({
      id: String(i),
      source: e.src,
      target: e.dst,
      markerEnd: MarkerType.ArrowClosed,
    }));
  for (const c of snapshot?.conditionals || [])
    for (const [key, dst] of Object.entries(c.mapping))
      if (dst !== "END")
        runEdges.value.push({
          id: c.src + key,
          source: c.src,
          target: dst,
          label: key,
          animated: true,
        });
}
async function runAction(action: string) {
  try {
    let value: any = null;
    if (action === "resume") {
      const x = await ElMessageBox.prompt(t("input"), t("resume"), {
        inputValue: "{}",
      });
      value = JSON.parse(x.value);
    }
    await api("manage/runs/" + runDetail.value.run.run_id, "POST", {
      action,
      value,
    });
    await showRuns();
  } catch (e) {
    ElMessage.error(String(e));
  }
}
function showJson() {
  jsonText.value = JSON.stringify(current.value.spec, null, 2);
  jsonDialog.value = true;
}
function applyJson() {
  try {
    const next = JSON.parse(jsonText.value);
    if (!Array.isArray(next.nodes) || !Array.isArray(next.edges))
      throw Error(t("invalidJson"));
    checkpoint();
    current.value.spec = next;
    syncLayout();
    render();
    dirty.value = true;
    jsonDialog.value = false;
  } catch (e) {
    ElMessage.error(String(e));
  }
}
onMounted(load);
</script>
<template>
  <section class="workflow-page">
    <div class="toolbar">
      <h1>{{ t("workflows") }}</h1>
      <el-button
        @click="
          select({
            name: '',
            enabled: true,
            description: '',
            spec: defaultSpec(),
            layout: {},
          })
        "
        >{{ t("create") }}</el-button
      ><el-button @click="showRuns">{{ t("runs") }}</el-button
      ><el-button @click="load">{{ t("refresh") }}</el-button>
    </div>
    <div class="workflow-shell">
      <aside class="workflow-list">
        <button
          v-for="w in items"
          :key="w.workflow_id"
          @click="select(w)"
          :class="{ selected: current?.workflow_id === w.workflow_id }"
        >
          <b>{{ w.name }}</b
          ><small>{{ w.description }}</small>
        </button>
        <p v-if="!items.length" class="muted">{{ t("empty") }}</p>
      </aside>
      <div v-if="current" class="workflow-editor">
        <div class="toolbar">
          <el-input
            v-model="current.name"
            :placeholder="t('name')"
            @input="dirty = true"
          /><el-switch
            v-model="current.enabled"
            :active-text="t('enabled')"
            @change="dirty = true"
          /><el-button type="primary" @click="save"
            >{{ t("save") }}{{ dirty ? " *" : "" }}</el-button
          ><el-button :disabled="!current.workflow_id || dirty" @click="run">{{
            t("run")
          }}</el-button
          ><el-button
            :disabled="!current.workflow_id"
            type="danger"
            plain
            @click="remove"
            >{{ t("delete") }}</el-button
          >
        </div>
        <el-input
          v-model="current.description"
          :placeholder="t('description')"
          @input="dirty = true"
        />
        <div class="toolbar">
          <el-button @click="beginNode()">+ {{ t("addNode") }}</el-button
          ><el-button @click="editState">{{ t("state") }}</el-button
          ><el-button :disabled="!history.length" @click="undo">{{
            t("undo")
          }}</el-button
          ><el-button :disabled="!future.length" @click="redo">{{
            t("redo")
          }}</el-button
          ><el-button @click="showJson"
            >{{ t("spec") }} / {{ t("state") }} /
            {{ t("conditionals") }}</el-button
          ><el-button
            @click="
              current.layout = {};
              render();
            "
            >{{ t("layout") }}</el-button
          >
        </div>
        <div class="canvas">
          <VueFlow
            :key="current.workflow_id || 'draft'"
            v-model:nodes="nodes"
            v-model:edges="edges"
            fit-view-on-init
            @node-click="({ node }) => beginNode(node)"
            @connect="connect"
            @edge-click="({ edge }) => editEdge(edge)"
            @node-drag-start="checkpoint"
            @node-drag-stop="dirty = true"
            ><Background :gap="20" /><Controls /><MiniMap
          /></VueFlow>
        </div>
        <div class="mobile-nodes">
          <el-button
            v-for="node in current.spec.nodes"
            :key="node.name"
            @click="beginNode(nodes.find((n) => n.id === node.name))"
            >{{ node.name }}</el-button
          >
        </div>
      </div>
      <el-empty v-else :description="t('choose')" />
    </div>
    <el-dialog v-model="dialog" :title="t('parameters')" width="min(720px,96vw)"
      ><el-form label-position="top"
        ><el-form-item :label="t('nodeName')"
          ><el-input v-model="draft.name" /></el-form-item
        ><el-form-item :label="t('nodeType')"
          ><el-select v-model="draft.kind"
            ><el-option
              v-for="k in kinds"
              :key="k"
              :value="k" /></el-select></el-form-item
        ><el-form-item
          v-for="k in configFields"
          :key="k"
          :label="t(k === 'question' ? 'questionLabel' : k)"
          ><el-select
            v-if="
              ['tool_name', 'sub_workflow_id', 'on_error', 'handler'].includes(
                k,
              )
            "
            :model-value="draft.config[k]"
            clearable
            filterable
            allow-create
            @update:model-value="(v) => (draft.config[k] = v)"
            ><template v-if="k === 'tool_name'"
              ><el-option
                v-for="tool in catalog.tools"
                :key="tool.name"
                :value="tool.name"
                :label="tool.name" /></template
            ><template v-else-if="k === 'sub_workflow_id'"
              ><el-option
                v-for="w in items.filter(
                  (w) => w.workflow_id !== current.workflow_id,
                )"
                :key="w.workflow_id"
                :value="w.workflow_id"
                :label="w.name" /></template
            ><template v-else
              ><el-option
                v-for="v in k === 'on_error'
                  ? ['fail', 'continue', 'compensate']
                  : ['interactive']"
                :key="v"
                :value="v" /></template></el-select
          ><el-select
            v-else-if="['tools', 'skills'].includes(k)"
            v-model="draft.config[k]"
            multiple
            filterable
            allow-create
            ><el-option
              v-for="v in k === 'tools' ? catalog.tools : catalog.skills"
              :key="v.name"
              :value="v.name"
              :label="v.name" /></el-select
          ><el-input-number
            v-else-if="
              schema[k]?.type === 'number' || schema[k]?.type === 'integer'
            "
            :model-value="draft.config[k] ?? schema[k].default"
            @update:model-value="(v) => (draft.config[k] = v)" /><el-input
            v-else
            :model-value="
              stringify(draft.config[k] ?? schema[k]?.default ?? '')
            "
            :type="
              ['output_field', 'type', 'image_ids_field'].includes(k)
                ? 'text'
                : 'textarea'
            "
            :autosize="{ minRows: 2, maxRows: 9 }"
            @update:model-value="(v) => setParam(k, v)"
        /></el-form-item>
        <pre v-if="draft.kind === 'tool' && showToolSchema()">{{
          JSON.stringify(showToolSchema(), null, 2)
        }}</pre>
        <el-collapse
          ><el-collapse-item :title="t('advanced')"
            ><p>{{ t("advancedHelp") }}</p>
            <el-input
              :model-value="JSON.stringify(draft.config, null, 2)"
              type="textarea"
              :rows="12"
              @change="
                (v) => {
                  try {
                    draft.config = JSON.parse(v);
                  } catch {
                    ElMessage.error(t('invalidJson'));
                  }
                }
              " /></el-collapse-item></el-collapse></el-form
      ><template #footer
        ><el-button v-if="oldId" type="danger" plain @click="deleteNode">{{
          t("delete")
        }}</el-button
        ><el-button @click="dialog = false">{{ t("cancel") }}</el-button
        ><el-button type="primary" @click="commitNode">{{
          t("save")
        }}</el-button></template
      ></el-dialog
    >
    <el-dialog v-model="stateDialog" :title="t('state')" width="min(760px,96vw)"
      ><div v-for="(f, i) in stateFields" :key="i" class="toolbar">
        <el-input v-model="f.name" :placeholder="t('name')" /><el-select
          v-model="f.type"
          ><el-option
            v-for="type in [
              'str',
              'int',
              'float',
              'bool',
              'list',
              'dict',
              'Any',
            ]"
            :key="type"
            :value="type" /></el-select
        ><el-select v-model="f.reducer" clearable :placeholder="t('reducer')"
          ><el-option
            v-for="r in ['overwrite', 'append', 'add_messages']"
            :key="r"
            :value="r" /></el-select
        ><el-button type="danger" @click="stateFields.splice(i, 1)">{{
          t("delete")
        }}</el-button>
      </div>
      <el-button @click="stateFields.push({ name: '', type: 'str' })"
        >+ {{ t("state") }}</el-button
      ><template #footer
        ><el-button type="primary" @click="saveState">{{
          t("save")
        }}</el-button></template
      ></el-dialog
    >
    <el-dialog v-model="jsonDialog" :title="t('spec')" width="min(850px,96vw)"
      ><el-input v-model="jsonText" type="textarea" :rows="24" /><template
        #footer
        ><el-button @click="jsonDialog = false">{{ t("cancel") }}</el-button
        ><el-button type="primary" @click="applyJson">{{
          t("save")
        }}</el-button></template
      ></el-dialog
    >
    <el-dialog v-model="edgeDialog" :title="t('edge')" width="min(500px,96vw)"
      ><p>{{ edgeDraft.source }} → {{ edgeDraft.target }}</p>
      <el-form-item :label="t('target')"
        ><el-select v-model="edgeDraft.target"
          ><el-option
            v-for="n in [...(current?.spec.nodes || []), { name: 'END' }]"
            :key="n.name"
            :value="n.name" /></el-select
      ></el-form-item>
      <el-form-item
        :label="t('join')"
        v-if="edgeDraft.data?.conditional === undefined"
        ><el-select v-model="edgeDraft.joinSources" multiple
          ><el-option
            v-for="n in current?.spec.nodes || []"
            :key="n.name"
            :value="n.name" /></el-select></el-form-item
      ><el-form-item :label="t('route')"
        ><el-input
          v-model="edgeDraft.route"
          :placeholder="edgeDraft.label || ''" /></el-form-item
      ><el-form-item :label="t('router')"
        ><el-select v-model="edgeDraft.router.kind"
          ><el-option value="state_field" /><el-option
            value="llm" /></el-select></el-form-item
      ><el-form-item :label="t('state')"
        ><el-select v-model="edgeDraft.router.field" filterable allow-create
          ><el-option
            v-for="f in current?.spec.state_schema || []"
            :key="f.name"
            :value="f.name" /></el-select></el-form-item
      ><template #footer
        ><el-button type="danger" @click="deleteEdge">{{
          t("delete")
        }}</el-button
        ><el-button type="primary" @click="saveEdge">{{
          t("save")
        }}</el-button></template
      ></el-dialog
    >
    <el-dialog v-model="runsDialog" :title="t('runs')" width="min(1000px,96vw)"
      ><div class="list-row" v-for="r in runs" :key="r.run_id">
        <button @click="detailRun(r)">{{ r.run_id }}</button
        ><span>{{ r.workflow_id }} · {{ r.status }}</span>
      </div>
      <template v-if="runDetail"
        ><el-button @click="detailRun(runDetail.run)">{{
          t("refresh")
        }}</el-button>
        <div class="canvas" style="height: 360px">
          <VueFlow
            :nodes="runNodes"
            :edges="runEdges"
            fit-view-on-init
            :nodes-draggable="false"
            :nodes-connectable="false"
            ><Background /><Controls
          /></VueFlow>
        </div>
        <pre>{{ JSON.stringify(runDetail, null, 2) }}</pre>
        <el-button
          :disabled="runDetail.run.status !== 'paused'"
          @click="runAction('resume')"
          >{{ t("resume") }}</el-button
        ><el-button @click="runAction('cancel')">{{
          t("cancel")
        }}</el-button></template
      ></el-dialog
    >
  </section>
</template>
