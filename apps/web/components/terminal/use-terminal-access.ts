"use client"

import { useTranslation } from "react-i18next"

import { api } from "@workspace/api-client"

import { useAuth } from "@/components/auth-provider"
import { useCapability } from "@/components/capabilities-provider"
import { useApi } from "@/hooks/use-api"

export type TerminalAccess =
  | { state: "loading" }
  | { state: "ready" }
  | { state: "unavailable"; reason: string; settingsLink?: boolean }

/**
 * Whether this user can open a terminal here: the host supports it, they're an admin,
 * and it's on in Settings → System. The server checks all of this again.
 */
export function useTerminalAccess(): TerminalAccess {
  const { t } = useTranslation("terminal")
  const { user } = useAuth()
  const capability = useCapability("terminal.host")
  const settings = useApi(() => api.GET("/api/settings/system"))

  if (!capability || settings.status === "loading") return { state: "loading" }
  if (!capability.available) {
    return {
      state: "unavailable",
      reason: capability.detail ?? t("access.noSupport"),
    }
  }
  if (!user.is_admin) {
    return { state: "unavailable", reason: t("access.adminsOnly") }
  }
  if (settings.status === "ok" && !settings.data.terminal_enabled) {
    return {
      state: "unavailable",
      reason: t("access.turnedOff"),
      settingsLink: true,
    }
  }
  return { state: "ready" }
}
