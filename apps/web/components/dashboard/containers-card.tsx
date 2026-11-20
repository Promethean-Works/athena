"use client"

import { BoxIcon } from "lucide-react"

import { api, type Schemas } from "@workspace/api-client"
import { Badge } from "@workspace/ui/components/badge"

import { useCapability } from "@/components/capabilities-provider"
import {
  DashboardCard,
  Quiet,
  RowsSkeleton,
} from "@/components/dashboard/card-shell"
import { useApi } from "@/hooks/use-api"

type Container = Schemas["ContainerOut"]

/** Needs attention first, then running, then the rest. */
function rank(c: Container): number {
  if (c.state === "restarting" || c.state === "dead") return 0
  if (c.state === "exited" && c.exit_code) return 0
  if (c.state === "running") return 1
  return 2
}

function StateBadge({ c }: { c: Container }) {
  if (c.state === "running") return <Badge variant="secondary">Running</Badge>
  if (rank(c) === 0)
    return (
      <Badge variant="destructive">
        {c.state === "exited" ? `Exited (${c.exit_code})` : c.state}
      </Badge>
    )
  return <Badge variant="outline">{c.state}</Badge>
}

function Count({ value, label }: { value: number; label: string }) {
  return (
    <div className="flex flex-col rounded-lg bg-muted/50 px-3 py-2">
      <span className="font-heading text-xl font-medium tabular-nums">
        {value}
      </span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  )
}

function ContainersBody() {
  // Refreshed every 15 s; the full list lives on /containers.
  const state = useApi(() => api.GET("/api/containers"), 15000)
  if (state.status === "loading") return <RowsSkeleton />
  if (state.status === "error")
    return <Quiet>Couldn&apos;t load containers: {state.error}</Quiet>
  const all = state.data
  const running = all.filter((c) => c.state === "running").length
  const attention = all.filter((c) => rank(c) === 0).length
  const top = [...all].sort((a, b) => rank(a) - rank(b)).slice(0, 5)
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-3 gap-2">
        <Count value={running} label="Running" />
        <Count value={all.length - running} label="Not running" />
        <Count value={attention} label="Need attention" />
      </div>
      {top.length === 0 ? (
        <Quiet>No containers on this server yet.</Quiet>
      ) : (
        <ul className="flex flex-col divide-y">
          {top.map((c) => (
            <li key={c.id} className="flex items-center gap-2 py-2 text-sm">
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{c.name}</span>
                <span className="block truncate text-xs text-muted-foreground">
                  {c.image}
                </span>
              </span>
              <StateBadge c={c} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function ContainersCard() {
  const containers = useCapability("containers")
  return (
    <DashboardCard
      icon={BoxIcon}
      title="Containers"
      description="Everything the container engine runs, apps included."
      href="/containers/"
      linkLabel="All containers"
    >
      {!containers ? (
        <RowsSkeleton />
      ) : containers.available ? (
        <ContainersBody />
      ) : (
        <Quiet>{containers.detail ?? "The container engine isn't running."}</Quiet>
      )}
    </DashboardCard>
  )
}
