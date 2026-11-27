"use client"

import * as React from "react"
import { ClockIcon, PlusIcon } from "lucide-react"
import { useTranslation } from "react-i18next"

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
  const { t } = useTranslation("backup")
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
        <h2 className="text-sm font-semibold">{t("plans.title")}</h2>
        <Button size="sm" onClick={onAdd}>
          <PlusIcon data-icon="inline-start" />
          {t("add")}
        </Button>
      </div>
      {plans.length === 0 ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <ClockIcon />
            </EmptyMedia>
            <EmptyTitle>{t("plans.empty.title")}</EmptyTitle>
            <EmptyDescription>
              {t("plans.empty.description")}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("plans.name")}</TableHead>
              <TableHead className="text-right">{t("plans.schedule")}</TableHead>
              <TableHead className="text-right">{t("plans.lastRun")}</TableHead>
              <TableHead className="text-right">{t("plans.status")}</TableHead>
              <TableHead className="text-right" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {plans.map((p) => (
              <TableRow key={p.id}>
                <TableCell>{p.name}</TableCell>
                <TableCell className="text-right">
                  {p.schedule ?? t("plans.manual")}
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
                    {t("plans.runNow")}
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
