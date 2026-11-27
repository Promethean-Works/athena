"use client"

import { useTranslation } from "react-i18next"
import { ShieldCheckIcon } from "lucide-react"

import { Badge } from "@workspace/ui/components/badge"

import {
  DashboardCard,
  Quiet,
  RowsSkeleton,
} from "@/components/dashboard/card-shell"
import { formatRelative, parseServerTime } from "@/lib/time"
import { usePlans } from "@/components/backup/use-backup"

function RunBadge({ status }: { status: string | null }) {
  const { t } = useTranslation("dashboard")
  if (status === "succeeded")
    return <Badge variant="secondary">{t("backup.succeeded")}</Badge>
  if (status === "failed") return <Badge variant="destructive">{t("backup.failed")}</Badge>
  if (status === "running") return <Badge variant="outline">{t("backup.running")}</Badge>
  return <Badge variant="outline">—</Badge>
}

function BackupBody() {
  const { t } = useTranslation("dashboard")
  const { plans, error } = usePlans()
  if (!plans) return <RowsSkeleton rows={3} />
  if (error) return <Quiet>{t("backup.loadError", { error })}</Quiet>

  const enabled = plans.filter((p) => p.enabled).length
  const failed = plans.filter((p) => p.last_status === "failed").length

  if (plans.length === 0)
    return <Quiet>{t("backup.empty")}</Quiet>

  const upcoming = plans
    .filter((p) => p.enabled && p.next_run_at !== null)
    .sort((a, b) => a.next_run_at!.localeCompare(b.next_run_at!))
    .slice(0, 3)

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="grid grid-cols-2 gap-2">
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-muted-foreground">
            {t("backup.plans")}
          </span>
          <span className="text-lg font-semibold">{plans.length}</span>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-muted-foreground">
            {t("backup.enabled")}
          </span>
          <span className="text-lg font-semibold">{enabled}</span>
        </div>
      </div>
      <div className="flex items-center gap-2 border-t pt-2">
        <RunBadge status={failed > 0 ? "failed" : null} />
        <span className="ml-auto text-xs text-muted-foreground">
          {failed > 0
            ? t("backup.plansFailed", { count: failed })
            : t("backup.noFailures")}
        </span>
      </div>
      <div>
        <span className="mb-1 block text-xs font-medium text-muted-foreground">
          {t("backup.nextRuns")}
        </span>
        {upcoming.length > 0 ? (
          <ul className="space-y-1 text-sm">
            {upcoming.map((p) => (
              <li
                key={p.id}
                className="flex items-center justify-between gap-2"
              >
                <span className="truncate">{p.name}</span>
                <span className="text-xs text-muted-foreground">
                  {formatRelative(parseServerTime(p.next_run_at!))}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-muted-foreground">{t("backup.noScheduled")}</p>
        )}
      </div>
    </div>
  )
}

export function BackupCard() {
  const { t } = useTranslation("dashboard")
  return (
    <DashboardCard
      icon={ShieldCheckIcon}
      title={t("backup.title")}
      description={t("backup.description")}
      href="/settings/backups"
      linkLabel={t("common.manage")}
    >
      <BackupBody />
    </DashboardCard>
  )
}
