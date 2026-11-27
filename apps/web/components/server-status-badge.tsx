"use client"

import { useTranslation } from "react-i18next"

import { api } from "@workspace/api-client"
import { Badge } from "@workspace/ui/components/badge"

import { useApi } from "@/hooks/use-api"

export function ServerStatusBadge() {
  const { t } = useTranslation("dashboard")
  const health = useApi(() => api.GET("/api/health"), 15_000)

  if (health.status === "loading") {
    return <Badge variant="outline">{t("serverStatus.connecting")}</Badge>
  }
  if (health.status === "error") {
    return <Badge variant="destructive">{t("serverStatus.unreachable")}</Badge>
  }
  return <Badge variant="secondary">{t("serverStatus.version", { version: health.data.version })}</Badge>
}
