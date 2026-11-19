<script setup lang="ts">
import { ref, onMounted, computed } from "vue";
import { useI18n } from "vue-i18n";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "./api";
const { t, locale } = useI18n(),
  data = ref<any>({ fields: [], custom: [] }),
  group = ref("All"),
  query = ref(""),
  changed = ref<any>({}),
  customName = ref(""),
  customValue = ref("");
async function load() {
  data.value = await api("settings");
  changed.value = {};
}
const groups = computed(() => [
  "All",
  ...new Set(data.value.fields.map((x: any) => x.group)),
]);
const fields = computed(() =>
  data.value.fields.filter(
    (f: any) =>
      (group.value === "All" || f.group === group.value) &&
      f.name.toLowerCase().includes(query.value.toLowerCase()),
  ),
);
async function save() {
  try {
    data.value = await api("settings", "PATCH", {
      revision: data.value.revision,
      changes: changed.value,
    });
    changed.value = {};
    ElMessage.success(t("saved"));
  } catch (e) {
    ElMessage.error(String(e));
  }
}
async function custom(name: string, value: any) {
  try {
    data.value = await api("settings", "PATCH", {
      revision: data.value.revision,
      custom: true,
      changes: { [name]: value },
    });
    customName.value = "";
    customValue.value = "";
  } catch (e) {
    ElMessage.error(String(e));
  }
}
async function remove(name: string) {
  if (
    !(await ElMessageBox.confirm(t("deleteConfirm"))
      .then(() => true)
      .catch(() => false))
  )
    return;
  await custom(name, null);
}
onMounted(load);
</script>
<template>
  <section>
    <div class="toolbar">
      <h1>{{ t("settings") }}</h1>
      <el-button @click="load">{{ t("refresh") }}</el-button
      ><el-button
        type="primary"
        :disabled="!Object.keys(changed).length"
        @click="save"
        >{{ t("save") }}</el-button
      >
    </div>
    <p class="muted">{{ t("secretNotice") }}</p>
    <div class="toolbar">
      <el-select v-model="group"
        ><el-option
          v-for="g in groups"
          :key="String(g)"
          :value="g"
          :label="g === 'All' ? t('all') : String(g)" /></el-select
      ><el-input v-model="query" :placeholder="t('filter')" clearable />
    </div>
    <div class="settings-grid">
      <div v-for="f in fields" :key="f.name" class="setting">
        <label
          >{{ f.name }}
          <small v-if="f.sensitive">{{
            f.configured ? t("configured") : ""
          }}</small></label
        ><el-switch
          v-if="f.type === 'boolean'"
          :model-value="changed[f.name] ?? f.value"
          @update:model-value="(v) => (changed[f.name] = v)"
        /><el-input-number
          v-else-if="f.type === 'number'"
          :model-value="changed[f.name] ?? f.value"
          @update:model-value="(v) => (changed[f.name] = v)"
        /><el-input
          v-else
          :model-value="changed[f.name] ?? f.value ?? ''"
          :type="f.sensitive ? 'password' : 'text'"
          :show-password="f.sensitive"
          :placeholder="f.sensitive ? t('unchanged') : ''"
          @update:model-value="
            (v) => {
              if (f.sensitive && !v) delete changed[f.name];
              else changed[f.name] = v;
            }
          "
        /><small>{{ f.description?.[locale] || f.description?.en }}</small
        ><small
          >{{ t("default") }}:
          {{ f.default === null ? "—" : String(f.default) }}
          <el-button v-if="f.sensitive" link @click="changed[f.name] = ''">{{
            t("clear")
          }}</el-button></small
        >
      </div>
    </div>
    <h2>{{ t("custom") }}</h2>
    <div class="toolbar">
      <el-input v-model="customName" :placeholder="t('variable')" /><el-input
        v-model="customValue"
        type="password"
        show-password
        :placeholder="t('value')"
      /><el-button
        :disabled="!customName"
        @click="custom(customName, customValue)"
        >{{ t("save") }}</el-button
      >
    </div>
    <div v-for="v in data.custom" :key="v.name" class="list-row">
      <code>{{ v.name }}</code
      ><span>{{ v.configured ? t("configured") : "" }}</span
      ><el-button
        @click="
          customName = v.name;
          customValue = '';
        "
        >{{ t("edit") }}</el-button
      ><el-button type="danger" plain @click="remove(v.name)">{{
        t("delete")
      }}</el-button>
    </div>
  </section>
</template>
