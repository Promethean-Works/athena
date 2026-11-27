"use client"

import { Trans, useTranslation } from "react-i18next"
import { type ParseKeys } from "i18next"
import { CircleAlertIcon } from "lucide-react"

import { api } from "@workspace/api-client"
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@workspace/ui/components/alert"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
import { Skeleton } from "@workspace/ui/components/skeleton"

import { useOptionalHostStats } from "@/components/dashboard/host-stats-provider"
import { useApi } from "@/hooks/use-api"
import { formatDuration } from "@/lib/format"

const OS_LABELS = {
  linux: "Linux",
  darwin: "macOS",
  windows: "Windows",
} as const

export function ServerOverview() {
  const { t } = useTranslation("dashboard")
  const info = useApi(() => api.GET("/api/system/info"))
  const stats = useOptionalHostStats()
  const host = stats?.host
  const uptime =
    host && host.boot_time > 0 && host.latest
      ? formatDuration(host.latest.t - host.boot_time)
      : undefined

  if (info.status === "error") {
    return (
      <Alert variant="destructive">
        <CircleAlertIcon />
        <AlertTitle>{t("server.unreachableTitle")}</AlertTitle>
        <AlertDescription>
          <Trans
            i18nKey="server.unreachableDescription"
            ns="dashboard"
            values={{ error: info.error }}
            components={{ code: <code /> }}
          />
        </AlertDescription>
      </Alert>
    )
  }

  type RowKey = ParseKeys<"dashboard">
  const rows: [RowKey, string | undefined][] =
    info.status === "ok"
      ? [
          ["server.host", info.data.hostname],
          ["server.os", info.data.os_version],
          ["server.platform", `${OS_LABELS[info.data.os]} · ${info.data.arch}`],
          ...(stats
            ? [["server.uptime", uptime] as [RowKey, string | undefined]]
            : []),
          ["server.athena", info.data.version],
          ["server.python", info.data.python],
        ]
      : [
          ["server.host", undefined],
          ["server.os", undefined],
          ["server.platform", undefined],
          ...(stats ? [["server.uptime", undefined] as [RowKey, undefined]] : []),
          ["server.athena", undefined],
          ["server.python", undefined],
        ]

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("server.title")}</CardTitle>
        <CardDescription>{t("server.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
          {rows.map(([label, value]) => (
            <div key={label} className="contents">
              <dt className="text-muted-foreground">{t(label)}</dt>
              <dd className="truncate">
                {value ?? <Skeleton className="h-4 w-40" />}
              </dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  )
}
