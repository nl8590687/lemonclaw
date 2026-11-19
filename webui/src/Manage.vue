<script setup lang="ts">
import { ref, watch, onMounted, computed } from "vue";
import { useI18n } from "vue-i18n";
import { ElMessage, ElMessageBox } from "element-plus";
import { api, upload } from "./api";
const props = defineProps<{ kind: string }>(),
  { t } = useI18n(),
  data = ref<any>([]),
  loading = ref(false),
  dialog = ref(false),
  draft = ref<any>({}),
  json = ref(""),
  mcpJsonFields = ref<Record<string, string>>({}),
  id = ref(""),
  revision = ref(""),
  query = ref(""),
  packageInput = ref<HTMLInputElement | null>(null);
const rows = computed(() => {
  let r = Array.isArray(data.value)
    ? data.value
    : data.value.servers || [
        ...(data.value.core || []).map((x: any) => ({ ...x, type: "core" })),
        ...(data.value.chunks || []).map((x: any) => ({ ...x, type: "chunk" })),
      ];
  return r.filter((x: any) =>
    JSON.stringify(x).toLowerCase().includes(query.value.toLowerCase()),
  );
});
function itemId(row: any) {
  return row.type === "core"
    ? "core:" + row.memory_type + ":" + row.key
    : row.task_id ||
        row.server_id ||
        row.name ||
        String(row.id || row.key || "");
}
async function load() {
  loading.value = true;
  try {
    data.value = await api("manage/" + props.kind);
    revision.value = data.value.revision || "";
  } catch (e) {
    ElMessage.error(String(e));
  } finally {
    loading.value = false;
  }
}
function edit(row?: any) {
  mcpJsonFields.value = {};
  id.value = row ? itemId(row) : "";
  draft.value = JSON.parse(JSON.stringify(row || {}));
  if (props.kind === "mcp") {
    json.value = JSON.stringify(
      row?.config || { transport: "http", url: "", auto_connect: true },
      null,
      2,
    );
  } else if (props.kind === "cron") {
    json.value = JSON.stringify(row?.metadata || {}, null, 2);
  } else
    json.value = JSON.stringify(
      row || {
        type: "core",
        memory_type: "preference",
        key: "",
        value: "",
        description: "",
      },
      null,
      2,
    );
  dialog.value = true;
}
function mcpValue(k: string) {
  try {
    return JSON.parse(json.value)[k];
  } catch {
    return "";
  }
}
function isMcpJsonField(k: string) {
  return ["args", "headers", "env"].includes(k);
}
function mcpSet(k: string, v: any) {
  const isJson = isMcpJsonField(k);
  if (isJson) mcpJsonFields.value[k] = v;
  try {
    const config = JSON.parse(json.value);
    config[k] = isJson ? parseMcpField(k, v) : v;
    json.value = JSON.stringify(config, null, 2);
  } catch {
    // Keep incomplete input visible and validate it when the user saves.
    if (!isJson) ElMessage.error(t("invalidJson"));
  }
}
function parseMcpField(k: string, value: string) {
  try {
    return JSON.parse(value.trim() || (k === "args" ? "[]" : "{}"));
  } catch {
    throw new Error(`${k}: ${t("invalidJson")}`);
  }
}
function mcpConfig() {
  const config = JSON.parse(json.value);
  for (const [key, value] of Object.entries(mcpJsonFields.value))
    config[key] = parseMcpField(key, value);
  return config;
}
async function save() {
  try {
    let value: any =
      props.kind === "mcp"
        ? { config: mcpConfig(), revision: revision.value }
        : props.kind === "cron"
          ? {
              prompt: draft.value.prompt || "",
              cron_expression: draft.value.cron_expression || "0 9 * * *",
              enabled: draft.value.enabled !== false,
              metadata: JSON.parse(json.value),
            }
          : JSON.parse(json.value);
    const target =
      id.value || (props.kind === "mcp" ? draft.value.server_id : "");
    await api(
      "manage/" + props.kind + (target ? "/" + encodeURIComponent(target) : ""),
      id.value ? "PUT" : "POST",
      value,
    );
    dialog.value = false;
    await load();
    ElMessage.success(t("saved"));
  } catch (e) {
    ElMessage.error(String(e));
  }
}
async function remove(row: any) {
  if (
    !(await ElMessageBox.confirm(t("deleteConfirm"))
      .then(() => true)
      .catch(() => false))
  )
    return;
  try {
    await api(
      "manage/" + props.kind + "/" + encodeURIComponent(itemId(row)),
      "DELETE",
      { revision: revision.value },
    );
    await load();
  } catch (e) {
    ElMessage.error(String(e));
  }
}
async function action(row: any, action: string) {
  try {
    if (action === "setup_deps") await ElMessageBox.confirm(t("dependencies"));
    await api(
      "manage/" + props.kind + "/" + encodeURIComponent(itemId(row)),
      "POST",
      { action },
    );
    await load();
  } catch (e) {
    ElMessage.error(String(e));
  }
}
async function packageUpload(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  try {
    const p = await upload(file, "skills/packages");
    await ElMessageBox.confirm(
      t("staged") +
        "\n" +
        p.name +
        "\n" +
        p.files.join("\n") +
        "\n" +
        t("dependencies"),
      t("install"),
      { confirmButtonText: t("install") },
    );
    let replace = false;
    if (rows.value.some((x) => x.name === p.name)) {
      await ElMessageBox.confirm(t("replaceConfirm"));
      replace = true;
    }
    await api("skills/packages/" + p.id + "/install", "POST", { replace });
    await load();
  } catch (e) {
    if (e !== "cancel") ElMessage.error(String(e));
  } finally {
    (event.target as HTMLInputElement).value = "";
  }
}
onMounted(load);
watch(() => props.kind, load);
</script>
<template>
  <section v-loading="loading">
    <div class="toolbar">
      <h1>{{ t(kind) }}</h1>
      <el-input
        v-model="query"
        :placeholder="t('filter')"
        clearable
      /><el-button @click="load">{{ t("refresh") }}</el-button
      ><el-button v-if="kind !== 'skills'" type="primary" @click="edit()">{{
        t("create")
      }}</el-button
      ><el-button v-else type="primary" @click="packageInput?.click()">{{
        t("upload")
      }}</el-button
      ><input
        ref="packageInput"
        type="file"
        accept=".zip"
        hidden
        @change="packageUpload"
      />
    </div>
    <el-empty v-if="!rows.length && !loading" :description="t('empty')" />
    <div class="resource-card" v-for="row in rows" :key="itemId(row)">
      <div>
        <h3>
          {{ row.name || row.prompt || row.title || row.key || itemId(row) }}
        </h3>
        <p>
          {{
            row.description || row.value || row.status || row.cron_expression
          }}
        </p>
        <small
          >{{
            row.enabled === undefined
              ? ""
              : t(row.enabled ? "enabled" : "disable")
          }}
          {{ row.next_run || row.dependencies || "" }}</small
        >
      </div>
      <div class="toolbar">
        <el-button v-if="kind !== 'skills'" @click="edit(row)">{{
          t("edit")
        }}</el-button
        ><el-button
          v-if="kind === 'skills'"
          @click="action(row, row.enabled ? 'disable' : 'enable')"
          >{{ t(row.enabled ? "disable" : "enable") }}</el-button
        ><el-button
          v-if="kind === 'skills'"
          @click="action(row, 'setup_deps')"
          >{{ t("setup_deps") }}</el-button
        ><el-button v-if="kind === 'mcp'" @click="action(row, 'reconnect')">{{
          t("reconnect")
        }}</el-button
        ><el-button
          v-if="kind === 'mcp'"
          @click="action(row, row.enabled ? 'disable' : 'enable')"
          >{{ t(row.enabled ? "disable" : "enable") }}</el-button
        ><el-button type="danger" plain @click="remove(row)">{{
          t("delete")
        }}</el-button>
      </div>
      <el-collapse
        ><el-collapse-item :title="t('details')">
          <pre>{{ JSON.stringify(row, null, 2) }}</pre>
        </el-collapse-item></el-collapse
      >
    </div>
    <el-dialog v-model="dialog" :title="t('edit')" width="min(760px,96vw)"
      ><el-form label-position="top"
        ><template v-if="kind === 'cron'"
          ><el-form-item :label="t('prompt')"
            ><el-input v-model="draft.prompt" type="textarea" /></el-form-item
          ><el-form-item label="Cron"
            ><el-input
              v-model="draft.cron_expression"
              placeholder="0 9 * * *" /></el-form-item
          ><el-form-item :label="t('enabled')"
            ><el-switch v-model="draft.enabled" /></el-form-item></template
        ><el-form-item v-if="kind === 'mcp'" :label="t('name')"
          ><el-input v-model="draft.server_id" :disabled="!!id" /></el-form-item
        ><template v-if="kind === 'mcp'"
          ><el-form-item label="Transport"
            ><el-select
              :model-value="mcpValue('transport') || 'http'"
              @update:model-value="(v) => mcpSet('transport', v)"
              ><el-option
                v-for="v in ['http', 'sse', 'stdio']"
                :key="v"
                :value="v" /></el-select></el-form-item
          ><el-form-item
            v-for="k in mcpValue('transport') === 'stdio'
              ? ['command', 'args', 'env']
              : ['url', 'headers']"
            :key="k"
            :label="k"
            ><textarea
              v-if="k === 'headers'"
              class="mcp-headers-input el-textarea__inner"
              aria-label="headers"
              rows="6"
              spellcheck="false"
              placeholder='{"X-Client": "lemonclaw"}'
              :value="mcpJsonFields.headers ?? JSON.stringify(mcpValue('headers'), null, 2) ?? ''"
              @input="mcpSet('headers', ($event.target as HTMLTextAreaElement).value)"
            /><el-input
              v-else
              :model-value="
                isMcpJsonField(k)
                  ? (mcpJsonFields[k] ??
                    JSON.stringify(mcpValue(k) || (k === 'args' ? [] : {})))
                  : mcpValue(k) || ''
              "
              :type="k === 'env' ? 'password' : 'text'"
              :show-password="k === 'env'"
              @update:model-value="(v) => mcpSet(k, v)"
            /></el-form-item
          ><el-form-item label="auto_connect"
            ><el-switch
              :model-value="mcpValue('auto_connect') !== false"
              @update:model-value="
                (v) => mcpSet('auto_connect', v)
              " /></el-form-item
        ></template>
        <p v-if="kind === 'mcp'" class="muted">{{ t("secretNotice") }}</p>
        <el-form-item :label="t('advanced')"
          ><el-input
            v-model="json"
            @input="mcpJsonFields = {}"
            type="textarea"
            :rows="16" /></el-form-item></el-form
      ><template #footer
        ><el-button @click="dialog = false">{{ t("cancel") }}</el-button
        ><el-button type="primary" @click="save">{{
          t("save")
        }}</el-button></template
      ></el-dialog
    >
  </section>
</template>

<style scoped>
.mcp-headers-input {
  font-family: monospace;
  resize: vertical;
}
</style>
