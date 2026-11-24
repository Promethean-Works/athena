"use client"

import * as React from "react"
import { ClockIcon, PlusIcon } from "lucide-react"

import { type Schemas } from "@workspace/api-client"
import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import { Skeleton } from "@workspace/ui/components/skeleton"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@workspace/ui/components/empty"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@workspace/ui/components/table"
import { formatServerTime } from "@/components/automation/triggers"

import { usePlans } from "./use-backup"

type Plan = Schemas["PlanOut"]

/** The list of backup plans. */
export function PlansCard({
  onAdd,
  onRun,
}: {
  onAdd: () => void
  onRun: (plan: Plan) => void
}) {
  const { plans, error } = usePlans()

  if (!plans) {
    return (
      <div className="flex min-w-0 flex-col gap-4 md:gap-6">
        <Skeleton className="h-24 w-full" />
      </div>
    )
  }

  return (
    <div className="flex min-w-0 flex-col gap-4 md:gap-6">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">Plans</h2>
        <Button size="sm" onClick={onAdd}>
          <PlusIcon data-icon="inline-start" />
          Add
        </Button>
      </div>
      {plans.length === 0 ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <ClockIcon />
            </EmptyMedia>
            <EmptyTitle>No plans yet</EmptyTitle>
            <EmptyDescription>
              A plan picks Athena, apps, a destination and a schedule, then runs
              on a timer.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead className="text-right">Schedule</TableHead>
              <TableHead className="text-right">Last run</TableHead>
              <TableHead className="text-right">Status</TableHead>
              <TableHead className="text-right" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {plans.map((p) => (
              <TableRow key={p.id}>
                <TableCell>{p.name}</TableCell>
                <TableCell className="text-right">
                  {p.schedule ?? "manual"}
                </TableCell>
                <TableCell className="text-right">
                  {formatServerTime(p.last_run_at)}
                </TableCell>
                <TableCell className="text-right">
                  <Badge variant={statusVariant(p.last_status)}>
                    {p.last_status ?? "—"}
                  </Badge>
                </TableCell>
                <TableCell className="text-right">
                  <Button variant="outline" size="sm" onClick={() => onRun(p)}>
                    Run now
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  )
}

function statusVariant(status: string | null) {
  switch (status) {
    case "ok":
      return "default"
    case "failed":
      return "destructive"
    case "skipped":
      return "outline"
    default:
      return "secondary"
  }
}
