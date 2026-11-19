import { createI18n } from "vue-i18n";
import en from "./locales/en.json";
import zh from "./locales/zh-CN.json";
export const locales: Record<string, { name: string; messages: typeof en }> = {
  "zh-CN": { name: "简体中文", messages: zh },
  en: { name: "English", messages: en },
};
export const i18n = createI18n({
  legacy: false,
  locale:
    localStorage.getItem("locale") ||
    (navigator.language.startsWith("zh") ? "zh-CN" : "en"),
  fallbackLocale: "en",
  messages: Object.fromEntries(
    Object.entries(locales).map(([k, v]) => [k, v.messages]),
  ),
});
