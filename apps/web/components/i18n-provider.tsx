"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"

import { UiLabelsProvider } from "@workspace/ui/lib/ui-labels"

import { storedAppearance } from "@/lib/appearance"
import { setLanguage } from "@/lib/i18n"

/**
 * Starts the UI in the language this browser last used (or the browser's). The first
 * render, and the static HTML, are English; signed in, the account's language is applied
 * by AppearanceProvider once it loads.
 */
export function I18nProvider({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation()
  React.useLayoutEffect(() => {
    void setLanguage(storedAppearance()?.language ?? "auto")
  }, [])
  return (
    <UiLabelsProvider
      labels={{ close: t("close"), toggleSidebar: t("toggleSidebar") }}
    >
      {children}
    </UiLabelsProvider>
  )
}
