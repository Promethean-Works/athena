import i18n from "i18next"
import { initReactI18next } from "react-i18next"

import en from "@/locales/en"

/**
 * UI language (docs/specs/i18n.md). English is bundled and is the fallback; every other
 * language is a folder in `locales/` that loads the first time it is picked.
 */
export const LANGUAGES = [
  { code: "en", name: "English" },
  { code: "es", name: "Español" },
  { code: "fr", name: "Français" },
  { code: "de", name: "Deutsch" },
  { code: "it", name: "Italiano" },
  { code: "pt-BR", name: "Português (Brasil)" },
  { code: "pt-PT", name: "Português (Portugal)" },
  { code: "nl", name: "Nederlands" },
  { code: "pl", name: "Polski" },
  { code: "ru", name: "Русский" },
  { code: "uk", name: "Українська" },
  { code: "tr", name: "Türkçe" },
  { code: "ja", name: "日本語" },
  { code: "ko", name: "한국어" },
  { code: "zh-CN", name: "简体中文" },
  { code: "zh-TW", name: "繁體中文" },
  { code: "hi", name: "हिन्दी" },
  { code: "id", name: "Bahasa Indonesia" },
  { code: "vi", name: "Tiếng Việt" },
  { code: "sv", name: "Svenska" },
  { code: "cs", name: "Čeština" },
  { code: "ro", name: "Română" },
] as const

export type LanguageCode = (typeof LANGUAGES)[number]["code"]
export const DEFAULT_LANGUAGE: LanguageCode = "en"

// Other languages can have other plural forms (_few, _many, no _one), so only English is
// typed; scripts/check-i18n.mjs checks the others against it.
type Resources = Record<string, object>

const loaders: Record<LanguageCode, () => Promise<{ default: Resources }>> = {
  en: async () => ({ default: en }),
  es: () => import("@/locales/es"),
  fr: () => import("@/locales/fr"),
  de: () => import("@/locales/de"),
  it: () => import("@/locales/it"),
  "pt-BR": () => import("@/locales/pt-BR"),
  "pt-PT": () => import("@/locales/pt-PT"),
  nl: () => import("@/locales/nl"),
  pl: () => import("@/locales/pl"),
  ru: () => import("@/locales/ru"),
  uk: () => import("@/locales/uk"),
  tr: () => import("@/locales/tr"),
  ja: () => import("@/locales/ja"),
  ko: () => import("@/locales/ko"),
  "zh-CN": () => import("@/locales/zh-CN"),
  "zh-TW": () => import("@/locales/zh-TW"),
  hi: () => import("@/locales/hi"),
  id: () => import("@/locales/id"),
  vi: () => import("@/locales/vi"),
  sv: () => import("@/locales/sv"),
  cs: () => import("@/locales/cs"),
  ro: () => import("@/locales/ro"),
}

export function isLanguageCode(value: unknown): value is LanguageCode {
  return LANGUAGES.some((l) => l.code === value)
}

/**
 * The language to show: the saved choice, else the first browser language we have
 * ("pt-PT" and "pt" use "pt-BR"), else English. "auto" means follow the browser.
 */
export function resolveLanguage(
  setting: string,
  browser: readonly string[]
): LanguageCode {
  if (isLanguageCode(setting)) return setting
  for (const tag of browser) {
    // Chinese written for Taiwan, Hong Kong or in traditional script uses zh-TW.
    if (/^zh\b/i.test(tag) && /-(tw|hk|mo|hant)\b/i.test(tag)) return "zh-TW"
    const exact = LANGUAGES.find(
      (l) => l.code.toLowerCase() === tag.toLowerCase()
    )
    if (exact) return exact.code
    const base = tag.split("-")[0]?.toLowerCase()
    const near = LANGUAGES.find(
      (l) => l.code.split("-")[0]?.toLowerCase() === base
    )
    if (near) return near.code
  }
  return DEFAULT_LANGUAGE
}

void i18n.use(initReactI18next).init({
  lng: DEFAULT_LANGUAGE,
  fallbackLng: DEFAULT_LANGUAGE,
  defaultNS: "common",
  ns: Object.keys(en),
  resources: { en },
  interpolation: { escapeValue: false }, // React escapes
  returnNull: false,
})

/** Switch the UI (loading the language first) and set `<html lang>`. */
export async function setLanguage(setting: string): Promise<void> {
  const code = resolveLanguage(
    setting,
    typeof navigator === "undefined" ? [] : navigator.languages
  )
  if (code !== i18n.resolvedLanguage) {
    if (!i18n.hasResourceBundle(code, "common")) {
      const { default: bundles } = await loaders[code]()
      for (const [ns, bundle] of Object.entries(bundles)) {
        i18n.addResourceBundle(code, ns, bundle, true, true)
      }
    }
    await i18n.changeLanguage(code)
  }
  if (typeof document !== "undefined") document.documentElement.lang = code
}

/** The language for `Intl` formatting (dates, numbers). */
export function currentLocale(): string {
  return i18n.resolvedLanguage ?? DEFAULT_LANGUAGE
}

export default i18n
