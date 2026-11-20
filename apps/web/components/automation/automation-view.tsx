"use client"

import { WorkflowIcon } from "lucide-react"

import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@workspace/ui/components/empty"
import { Skeleton } from "@workspace/ui/components/skeleton"

import {
  useCapabilities,
  useCapability,
} from "@/components/capabilities-provider"
import { ExternalAutomationCard } from "@/components/automation/external-card"
import { JobRunsCard } from "@/components/automation/job-runs-card"
import { TriggersCard } from "@/components/automation/triggers-card"
import { useTriggers } from "@/components/automation/triggers"

/** Automation page: triggers (cron + webhook), their job runs, and how to connect n8n or MCP. */
export function AutomationView() {
  const { manifest } = useCapabilities()
  const capability = useCapability("automation")

  if (!manifest) return <Skeleton className="h-64 w-full" />
  if (!capability?.available) {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <WorkflowIcon />
          </EmptyMedia>
          <EmptyTitle>Automation isn&apos;t available</EmptyTitle>
          <EmptyDescription>
            {capability?.detail ?? "This host doesn't support automation."}
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }
  return <AutomationPanels />
}

function AutomationPanels() {
  const triggers = useTriggers()
  return (
    <div className="grid grid-cols-1 items-start gap-4 md:gap-6 xl:grid-cols-12">
      <div className="min-w-0 xl:col-span-7">
        <TriggersCard {...triggers} />
      </div>
      <div className="flex min-w-0 flex-col gap-4 md:gap-6 xl:col-span-5">
        <JobRunsCard triggers={triggers.triggers} />
        <ExternalAutomationCard />
      </div>
    </div>
  )
}
