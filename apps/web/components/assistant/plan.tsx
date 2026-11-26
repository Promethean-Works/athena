"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"
import {
  ChevronDownIcon,
  CircleCheckIcon,
  CircleIcon,
  CircleSlashIcon,
  ListChecksIcon,
  LoaderCircleIcon,
} from "lucide-react"

import type { Schemas } from "@workspace/api-client"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@workspace/ui/components/collapsible"
import { cn } from "@workspace/ui/lib/utils"

export type PlanStep = Schemas["PlanStep"]

function StepIcon({
  status,
  running,
}: {
  status: PlanStep["status"]
  running: boolean
}) {
  const cls = "size-4 shrink-0"
  if (status === "completed")
    return <CircleCheckIcon className={cn(cls, "text-primary")} />
  if (status === "cancelled")
    return <CircleSlashIcon className={cn(cls, "text-muted-foreground")} />
  if (status === "in_progress")
    return running ? (
      <LoaderCircleIcon className={cn(cls, "animate-spin")} />
    ) : (
      <CircleIcon className={cn(cls, "fill-primary/20 text-primary")} />
    )
  return <CircleIcon className={cn(cls, "text-muted-foreground")} />
}

/** The assistant's plan for this chat (`write_plan`), as a checklist above the prompt bar.
 * Open while steps are left; folded once they're all done. */
export function PlanChecklist({
  steps,
  running,
}: {
  steps: PlanStep[]
  /** A reply is streaming, so the step in progress spins. */
  running: boolean
}) {
  const { t } = useTranslation("assistant")
  const [open, setOpen] = React.useState<boolean>()
  if (steps.length === 0) return null
  const done = steps.filter(
    (s) => s.status === "completed" || s.status === "cancelled"
  ).length
  const current = steps.find((s) => s.status === "in_progress")
  const allDone = done === steps.length
  return (
    <Collapsible
      open={open ?? !allDone}
      onOpenChange={setOpen}
      className="rounded-lg border bg-card text-sm text-card-foreground"
    >
      <CollapsibleTrigger className="group flex w-full items-center gap-2 px-3 py-2 text-left">
        <ListChecksIcon className="size-4 shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate">
          <span className="font-medium">{t("plan.title")}</span>
          <span className="text-muted-foreground">
            {" · "}
            {t("plan.progress", { done, total: steps.length })}
            {current ? ` · ${current.active_form || current.content}` : ""}
          </span>
        </span>
        <ChevronDownIcon className="size-4 shrink-0 text-muted-foreground transition-transform group-data-[panel-open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ol
          aria-label={t("plan.steps")}
          className="flex max-h-40 flex-col gap-1.5 overflow-y-auto px-3 pb-2"
        >
          {steps.map((s) => (
            <li key={s.id} className="flex items-start gap-2">
              <span className="mt-0.5">
                <StepIcon status={s.status} running={running} />
              </span>
              <span
                className={cn(
                  "min-w-0",
                  (s.status === "completed" || s.status === "cancelled") &&
                    "text-muted-foreground line-through"
                )}
              >
                {s.status === "in_progress" && s.active_form
                  ? s.active_form
                  : s.content}
                <span className="sr-only">
                  {` (${t(`plan.status.${s.status}`)})`}
                </span>
              </span>
            </li>
          ))}
        </ol>
      </CollapsibleContent>
    </Collapsible>
  )
}
