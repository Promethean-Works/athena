import i18n from "i18next"
import { initReactI18next } from "react-i18next"

import en from "@/locales/en"

/**
 * UI language (docs/specs/i18n.md). English is bundled and is the fallback; every other
 * language is a folder in `locales/` that loads the first time it is picked.
 */
export const LANGUAGES = [
  { code: "en", name: "English" },
  { code: "pt-BR", name: "Português (Brasil)" },
] as const

export type LanguageCode = (typeof LANGUAGES)[number]["code"]
export const DEFAULT_LANGUAGE: LanguageCode = "en"

type Resources = typeof en

const loaders: Record<LanguageCode, () => Promise<{ default: Resources }>> = {
  en: async () => ({ default: en }),
  "pt-BR": () => import("@/locales/pt-BR"),
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
    const exact = LANGUAGES.find((l) => l.code.toLowerCase() === tag.toLowerCase())
    if (exact) return exact.code
    const base = tag.split("-")[0]?.toLowerCase()
    const near = LANGUAGES.find((l) => l.code.split("-")[0]?.toLowerCase() === base)
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
