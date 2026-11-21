<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from "vue";
import { useI18n } from "vue-i18n";
import { ElMessage } from "element-plus";
import elementEnglish from "element-plus/es/locale/lang/en";
import elementChinese from "element-plus/es/locale/lang/zh-cn";
import {
  ChatLineRound,
  Connection,
  Clock,
  SetUp,
  Collection,
  Document,
  Menu,
  Paperclip,
  Promotion,
  Key,
} from "@element-plus/icons-vue";
import { marked } from "marked";
import DOMPurify from "dompurify";
import { api, upload } from "./api";
import { locales } from "./i18n";
import Settings from "./Settings.vue";
import Workflow from "./Workflow.vue";
import Manage from "./Manage.vue";
const { t, locale } = useI18n(),
  authenticated = ref(false),
  key = ref((window as any).__lemonclawKey || ""),
  tab = ref(location.hash.slice(1) || "chat"),
  mobile = ref(false),
  messages = ref<any[]>([]),
  questions = ref<any[]>([]),
  busy = ref(false),
  stream = ref(""),
  text = ref(""),
  attachments = ref<any[]>([]),
  fileInput = ref<HTMLInputElement | null>(null),
  chatHistory = ref<HTMLElement | null>(null),
  answerFields = ref<any>({}),
  loading = ref(false),
  connected = ref(true);
let events: EventSource | null = null,
  refreshTimer: any;
const elementLocale = computed(() =>
  locale.value === "zh-CN" ? elementChinese : elementEnglish,
);
const navigation = [
  ["chat", ChatLineRound],
  ["workflows", Connection],
  ["cron", Clock],
  ["mcp", SetUp],
  ["skills", Collection],
  ["memory", Document],
  ["settings", SetUp],
] as const;
function html(value: any) {
  return DOMPurify.sanitize(
    marked.parse(typeof value === "string" ? value : JSON.stringify(value), {
      async: false,
    }) as string,
  );
}
async function login() {
  try {
    await api("auth/login", "POST", { key: key.value });
    key.value = "";
    (window as any).__lemonclawKey = "";
    await init();
  } catch (e) {
    ElMessage.error(String(e));
  }
}
let followLatest = true;
function updateScrollPosition() {
  const history = chatHistory.value;
  if (history) {
    followLatest = history.scrollHeight - history.clientHeight - history.scrollTop <= 48;
  }
}
function scrollToLatest() {
  const history = chatHistory.value;
  if (history && followLatest) history.scrollTop = history.scrollHeight;
}
watch(chatHistory, () => {
  followLatest = true;
  scrollToLatest();
}, { flush: "post" });
watch([messages, () => messages.value.length, stream], scrollToLatest, { flush: "post" });
async function refresh() {
  try {
    const c = await api("conversation/context");
    messages.value = c.messages;
    busy.value = c.busy;
    stream.value = "";
  } catch (e) {
    ElMessage.error(String(e));
  }
}
async function init() {
  try {
    const b = await api("bootstrap");
    authenticated.value = true;
    messages.value = b.context;
    questions.value = b.questions;
    busy.value = b.busy;
    startEvents(b.event_cursor);
  } catch {
    authenticated.value = false;
  }
}
function startEvents(cursor: number) {
  events?.close();
  events = new EventSource(`/api/v1/events?after=${cursor}`);
  events.addEventListener("update", (e: any) => {
    connected.value = true;
    const v = JSON.parse(e.data);
    if (v.kind === "delta") stream.value += v.data.content || "";
    if (v.kind === "input") busy.value = true;
    if (["refresh", "message", "error"].includes(v.kind)) {
      clearTimeout(refreshTimer);
      refreshTimer = setTimeout(refresh, 100);
    }
    if (v.kind === "error") ElMessage.error(v.data.content);
  });
  events.addEventListener(
    "questions",
    (e: any) => (questions.value = JSON.parse(e.data)),
  );
  events.addEventListener("reset", refresh);
  events.onopen = () => (connected.value = true);
  events.onerror = () => (connected.value = false);
}
const sending = ref(false);
let pendingRequest: { signature: string; id: string } | null = null;
function randomId() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (n) =>
    n.toString(16).padStart(2, "0"),
  ).join("");
}
async function send() {
  if (sending.value || (!text.value.trim() && !attachments.value.length))
    return;
  sending.value = true;
  try {
    const content = text.value;
    const payload = {
      text: content,
      attachments: attachments.value.map((x) => x.attachment_id),
    };
    const signature = JSON.stringify(payload);
    if (pendingRequest?.signature !== signature)
      pendingRequest = { signature, id: randomId() };
    await api("conversation/messages", "POST", {
      ...payload,
      request_id: pendingRequest.id,
    });
    followLatest = true;
    messages.value.push({ id: pendingRequest.id, role: "human", content });
    pendingRequest = null;
    text.value = "";
    attachments.value = [];
    busy.value = true;
  } catch (e) {
    ElMessage.error(String(e));
  } finally {
    sending.value = false;
  }
}
async function files(event: Event) {
  const input = event.target as HTMLInputElement;
  loading.value = true;
  for (const file of Array.from(input.files || [])) {
    try {
      attachments.value.push(await upload(file));
    } catch (e) {
      ElMessage.error(String(e));
    }
  }
  input.value = "";
  loading.value = false;
}
function field(qid: string, i: number, value: any) {
  answerFields.value[qid] ||= {};
  answerFields.value[qid][String(i + 1)] = value;
}
async function answer(q: any, action: string) {
  try {
    await api("questions/" + q.question_id + "/" + action, "POST", {
      fields: answerFields.value[q.question_id] || {},
    });
    questions.value = await api("questions");
  } catch (e) {
    ElMessage.error(String(e));
  }
}
function saveLocale(value: string) {
  localStorage.setItem("locale", value);
}
function go(name: string) {
  tab.value = name;
  location.hash = name;
  mobile.value = false;
}
async function logout() {
  await api("auth/logout", "POST", {});
  authenticated.value = false;
  events?.close();
}
function unauthorized() {
  authenticated.value = false;
  events?.close();
}
onMounted(() => {
  window.addEventListener("unauthorized", unauthorized);
  if (key.value) login();
  else init();
});
onBeforeUnmount(() => {
  events?.close();
  clearTimeout(refreshTimer);
  window.removeEventListener("unauthorized", unauthorized);
});
</script>
<template>
  <el-config-provider :locale="elementLocale">
    <div v-if="!authenticated" class="login-page">
      <form class="login-card" @submit.prevent="login">
        <div class="brand-icon">L</div>
        <h1>LemonClaw</h1>
        <p>{{ t("passwordHelp") }}</p>
        <el-input
          v-model="key"
          type="password"
          show-password
          :placeholder="t('key')"
          :prefix-icon="Key"
          size="large"
          autofocus
        /><el-button native-type="submit" type="primary" size="large">{{
          t("login")
        }}</el-button>
      </form>
    </div>
    <div v-else class="app-shell">
      <aside class="sidebar" :class="{ open: mobile }">
        <div class="brand">
          <div class="brand-icon">L</div>
          <strong>LemonClaw</strong>
        </div>
        <p class="sidebar-note">{{ t("shared") }}</p>
        <nav>
          <button
            v-for="[name, icon] in navigation"
            :key="name"
            :class="{ active: tab === name }"
            @click="go(name)"
          >
            <el-icon><component :is="icon" /></el-icon>{{ t(name) }}
          </button>
        </nav>
        <div class="sidebar-bottom">
          <el-select v-model="locale" @change="saveLocale"
            ><el-option
              v-for="(v, k) in locales"
              :key="k"
              :value="k"
              :label="v.name" /></el-select
          ><el-button link @click="logout">{{ t("logout") }}</el-button>
        </div>
      </aside>
      <div v-if="mobile" class="scrim" @click="mobile = false" />
      <main>
        <header>
          <el-button
            class="mobile-toggle"
            :icon="Menu"
            @click="mobile = !mobile"
          /><span>{{ t(tab) }}</span
          ><span class="status"
            ><i :class="{ working: busy }" />{{
              t(busy ? "busy" : "idle")
            }}</span
          >
        </header>
        <div v-if="!connected" class="connection-warning">
          {{ t("streamDisconnected") }}
        </div>
        <div v-if="tab === 'chat'" class="chat-page">
          <div ref="chatHistory" class="chat-history" @scroll.passive="updateScrollPosition">
            <div class="chat-intro">
              <h1>{{ t("currentContext") }}</h1>
              <p>{{ t("contextNote") }}</p>
            </div>
            <div
              v-for="(m, i) in messages"
              :key="m.id || i"
              class="message"
              :class="{ human: m.role === 'human' }"
            >
              <div class="avatar">
                {{
                  m.role === "human" ? t("you") : m.role === "tool" ? "↗" : "L"
                }}
              </div>
              <div class="message-body">
                <small>{{ m.role }}</small>
                <div class="markdown" v-html="html(m.content)" />
                <div class="history-images">
                  <a
                    v-for="a in m.attachments || []"
                    :key="a.attachment_id"
                    :href="'/api/v1/attachments/' + a.attachment_id"
                    target="_blank"
                    ><img
                      :src="'/api/v1/attachments/' + a.attachment_id"
                      :alt="a.attachment_id"
                      loading="lazy"
                  /></a>
                </div>
                <el-tag
                  v-for="tool in m.tools || []"
                  :key="tool.id"
                  size="small"
                  >{{ tool.name }}</el-tag
                >
              </div>
            </div>
            <div v-if="stream" class="message">
              <div class="avatar">L</div>
              <div class="message-body markdown" v-html="html(stream)" />
            </div>
            <div
              v-for="q in questions.filter((q) => q.status === 'pending')"
              :key="q.question_id"
              class="question-card"
            >
              <h3>{{ t("pending") }}</h3>
              <p>{{ q.payload.reason }}</p>
              <small
                >{{ t("deadline") }}:
                {{ new Date(q.deadline * 1000).toLocaleString(locale) }}</small
              ><el-form label-position="top"
                ><el-form-item
                  v-for="(v, i) in q.payload.questions"
                  :key="i"
                  :label="v.prompt"
                  ><el-input
                    v-if="v.kind === 'text'"
                    type="textarea"
                    @update:model-value="
                      (x) => field(q.question_id, Number(i), x)
                    " /><el-select
                    v-else
                    :multiple="v.kind === 'multiple'"
                    @update:model-value="
                      (x) =>
                        field(
                          q.question_id,
                          Number(i),
                          Array.isArray(x) ? x : [x],
                        )
                    "
                    ><el-option
                      v-for="(option, j) in v.options"
                      :key="j"
                      :label="option"
                      :value="String(Number(j) + 1)" /><el-option
                      :value="'0'"
                      :label="t('other')" /></el-select
                  ><el-input
                    v-if="v.kind !== 'text'"
                    :placeholder="t('other')"
                    @update:model-value="
                      (x) => {
                        answerFields[q.question_id] ||= {};
                        answerFields[q.question_id][
                          String(Number(i) + 1) + '_other'
                        ] = x;
                      }
                    " /></el-form-item></el-form
              ><el-button type="primary" @click="answer(q, 'answers')">{{
                t("confirm")
              }}</el-button
              ><el-button @click="answer(q, 'cancel')">{{
                t("cancel")
              }}</el-button>
            </div>
          </div>
          <form class="composer" @submit.prevent="send">
            <div class="attachment-list">
              <el-tag
                v-for="(a, i) in attachments"
                :key="a.attachment_id"
                closable
                @close="attachments.splice(i, 1)"
                ><a
                  :href="'/api/v1/attachments/' + a.attachment_id"
                  target="_blank"
                  >{{ a.name }}</a
                ></el-tag
              >
            </div>
            <el-input
              v-model="text"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 7 }"
              :placeholder="t('message')"
              @keydown.enter.exact.prevent="send"
            />
            <div class="composer-bottom">
              <el-button
                :icon="Paperclip"
                :loading="loading"
                @click="fileInput?.click()"
                >{{ t("attach") }}</el-button
              ><input
                ref="fileInput"
                type="file"
                multiple
                hidden
                @change="files"
              /><el-button
                type="primary"
                native-type="submit"
                :icon="Promotion"
                :disabled="
                  loading || sending || (!text.trim() && !attachments.length)
                "
                >{{ t("send") }}</el-button
              >
            </div>
          </form>
        </div>
        <div v-else class="page-content">
          <Settings v-if="tab === 'settings'" /><Workflow
            v-else-if="tab === 'workflows'"
          /><Manage v-else :kind="tab" :key="tab" />
        </div>
      </main>
    </div>
  </el-config-provider>
</template>
