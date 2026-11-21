"use client"

import { ZapIcon } from "lucide-react"

import { api, type Schemas } from "@workspace/api-client"
import { Badge } from "@workspace/ui/components/badge"

import {
  DashboardCard,
  Quiet,
  RowsSkeleton,
} from "@/components/dashboard/card-shell"
import { useApi } from "@/hooks/use-api"
import { formatRelative, parseServerTime } from "@/lib/time"

type Trigger = Schemas["TriggerOut"]
type Run = Schemas["JobRunOut"]

function RunBadge({ status }: { status: string }) {
  if (status === "succeeded") return <Badge variant="secondary">Succeeded</Badge>
  if (status === "failed") return <Badge variant="destructive">Failed</Badge>
  return <Badge variant="outline">{status}</Badge>
}

function AutomationBody() {
  const state = useApi(async () => {
    const [triggers, runs] = await Promise.all([
      api.GET("/api/automation/triggers"),
      api.GET("/api/automation/jobs", { params: { query: { limit: 5 } } }),
    ])
    return {
      data:
        triggers.data && runs.data
          ? { triggers: triggers.data, runs: runs.data }
          : undefined,
      response: triggers.data ? runs.response : triggers.response,
    }
  }, 30000)
  if (state.status === "loading") return <RowsSkeleton />
  if (state.status === "error")
    return <Quiet>Couldn&apos;t load automation: {state.error}</Quiet>

  const { triggers, runs } = state.data
  const names = new Map(triggers.map((t: Trigger) => [t.id, t.name]))
  const next = triggers
    .filter((t) => t.enabled && t.next_run_at)
    .sort((a, b) => (a.next_run_at! < b.next_run_at! ? -1 : 1))
    .slice(0, 3)
  const enabled = triggers.filter((t) => t.enabled).length

  if (triggers.length === 0)
    return (
      <Quiet>
        No triggers yet. Create one to restart an app or update packages on a
        schedule.
      </Quiet>
    )

  return (
    <div className="flex flex-col gap-4">
      <section className="flex flex-col gap-1">
        <h3 className="text-xs font-medium text-muted-foreground">
          Next runs · {enabled} of {triggers.length} triggers on
        </h3>
        {next.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Nothing scheduled. Webhook triggers run when they&apos;re called.
          </p>
        ) : (
          <ul className="flex flex-col divide-y">
            {next.map((t) => (
              <li key={t.id} className="flex items-center gap-2 py-2 text-sm">
                <span className="min-w-0 flex-1 truncate font-medium">
                  {t.name}
                </span>
                <span className="text-xs text-muted-foreground">
                  {formatRelative(parseServerTime(t.next_run_at!))}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="flex flex-col gap-1">
        <h3 className="text-xs font-medium text-muted-foreground">
          Recent runs
        </h3>
        {runs.length === 0 ? (
          <p className="text-sm text-muted-foreground">No runs yet.</p>
        ) : (
          <ul className="flex flex-col divide-y">
            {runs.map((r: Run) => (
              <li key={r.id} className="flex items-center gap-2 py-2 text-sm">
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">
                    {(r.trigger_id && names.get(r.trigger_id)) ?? "Deleted trigger"}
                  </span>
                  <span className="block text-xs text-muted-foreground">
                    {formatRelative(parseServerTime(r.started_at))}
                  </span>
                </span>
                <RunBadge status={r.status} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

export function AutomationCard() {
  return (
    <DashboardCard
      icon={ZapIcon}
      title="Automation"
      description="Scheduled and webhook triggers, and how their runs went."
      href="/automation/"
      linkLabel="Manage"
    >
      <AutomationBody />
    </DashboardCard>
  )
}
