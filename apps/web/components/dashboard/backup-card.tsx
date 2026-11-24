"use client"

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
  if (status === "succeeded")
    return <Badge variant="secondary">Succeeded</Badge>
  if (status === "failed") return <Badge variant="destructive">Failed</Badge>
  if (status === "running") return <Badge variant="outline">Running</Badge>
  return <Badge variant="outline">—</Badge>
}

function BackupBody() {
  const { plans, error } = usePlans()
  if (!plans) return <RowsSkeleton rows={3} />
  if (error) return <Quiet>Couldn&apos;t load backup plans: {error}</Quiet>

  const enabled = plans.filter((p) => p.enabled).length
  const failed = plans.filter((p) => p.last_status === "failed").length

  if (plans.length === 0)
    return (
      <Quiet>No backup plans yet. Add one in Settings &rarr; Backups.</Quiet>
    )

  const upcoming = plans
    .filter((p) => p.enabled && p.next_run_at !== null)
    .sort((a, b) => a.next_run_at!.localeCompare(b.next_run_at!))
    .slice(0, 3)

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="grid grid-cols-2 gap-2">
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-muted-foreground">
            Plans
          </span>
          <span className="text-lg font-semibold">{plans.length}</span>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-muted-foreground">
            Enabled
          </span>
          <span className="text-lg font-semibold">{enabled}</span>
        </div>
      </div>
      <div className="flex items-center gap-2 border-t pt-2">
        <RunBadge status={failed > 0 ? "failed" : null} />
        <span className="ml-auto text-xs text-muted-foreground">
          {failed > 0 ? `${failed} plan(s) failed` : "No recent failures"}
        </span>
      </div>
      <div>
        <span className="mb-1 block text-xs font-medium text-muted-foreground">
          Next scheduled runs
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
          <p className="text-xs text-muted-foreground">No scheduled runs</p>
        )}
      </div>
    </div>
  )
}

export function BackupCard() {
  return (
    <DashboardCard
      icon={ShieldCheckIcon}
      title="Backups"
      description="Backup plans, last runs and the next scheduled run."
      href="/settings/backups"
      linkLabel="Manage"
    >
      <BackupBody />
    </DashboardCard>
  )
}
