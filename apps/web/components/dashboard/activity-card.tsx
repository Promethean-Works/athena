"use client"

import { useTranslation } from "react-i18next"
import { HistoryIcon } from "lucide-react"

import { api } from "@workspace/api-client"

import {
  DashboardCard,
  Quiet,
  RowsSkeleton,
} from "@/components/dashboard/card-shell"
import { useApi } from "@/hooks/use-api"
import { currentLocale } from "@/lib/i18n"
import { formatRelative, parseServerTime } from "@/lib/time"

/** "app.start" → "App start", "container.stop" → "Container stop". */
function readable(action: string): string {
  const text = action.replace(/[._]/g, " ")
  return text.charAt(0).toUpperCase() + text.slice(1)
}

function ActivityBody() {
  const { t } = useTranslation("dashboard")
  const state = useApi(
    () => api.GET("/api/audit", { params: { query: { limit: 5 } } }),
    30000
  )
  if (state.status === "loading") return <RowsSkeleton rows={4} />
  if (state.status === "error")
    return <Quiet>{t("activity.loadError", { error: state.error })}</Quiet>
  if (state.data.length === 0)
    return <Quiet>{t("activity.empty")}</Quiet>
  return (
    <ol className="flex flex-col divide-y">
      {state.data.map((e) => {
        const at = parseServerTime(e.at)
        return (
          <li key={e.id} className="flex items-start gap-3 py-2 text-sm">
            <span className="min-w-0 flex-1">
              <span className="block truncate">
                <span className="font-medium">{readable(e.action)}</span>
                {e.target ? (
                  <span className="text-muted-foreground"> · {e.target}</span>
                ) : null}
              </span>
              <span className="block text-xs text-muted-foreground">
                {t("activity.by", { username: e.username })}
              </span>
            </span>
            <time
              dateTime={at.toISOString()}
              title={at.toLocaleString(currentLocale())}
              className="shrink-0 text-xs text-muted-foreground"
            >
              {formatRelative(at)}
            </time>
          </li>
        )
      })}
    </ol>
  )
}

/** The latest audit entries (admins only; the picker hides it from others). */
export function ActivityCard() {
  const { t } = useTranslation("dashboard")
  return (
    <DashboardCard
      icon={HistoryIcon}
      title={t("activity.title")}
      description={t("activity.description")}
    >
      <ActivityBody />
    </DashboardCard>
  )
}
