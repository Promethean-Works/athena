"use client"

import * as React from "react"
import { ClockIcon, FolderIcon, LayoutListIcon } from "lucide-react"
import { useTranslation } from "react-i18next"

import { type Schemas } from "@workspace/api-client"
import {
  useCapabilities,
  useCapability,
} from "@/components/capabilities-provider"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@workspace/ui/components/empty"
import { Skeleton } from "@workspace/ui/components/skeleton"
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@workspace/ui/components/tabs"
import { toast } from "@workspace/ui/components/toast"

import { AddDestinationDialog } from "./add-destination-dialog"
import { AddPlanDialog } from "./add-plan-dialog"
import { DestinationsCard } from "./destinations-card"
import { PlansCard } from "./plans-card"
import { VersionsCard } from "./versions-card"
import { usePlans } from "./use-backup"

/** Backups page: versions, destinations and plans. Gated by the `backup` capability. */
export function BackupsView() {
  const { t } = useTranslation("backup")
  const { manifest } = useCapabilities()
  const capability = useCapability("backup")
  const { load, run } = usePlans()
  const [addDestinationOpen, setAddDestinationOpen] = React.useState(false)
  const [addPlanOpen, setAddPlanOpen] = React.useState(false)

  if (!manifest) return <Skeleton className="h-64 w-full" />
  if (!capability?.available) {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <LayoutListIcon />
          </EmptyMedia>
          <EmptyTitle>{t("view.unavailable")}</EmptyTitle>
          <EmptyDescription>
            {capability?.detail ?? t("view.unsupported")}
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  async function handleRun(plan: Schemas["PlanOut"]) {
    const job = await run(plan.id)
    if (job) {
      toast.add({
        title: t("toast.backupStarted", { name: plan.name }),
        type: "success",
      })
      void load()
    }
  }

  function handleAddedDestination(destination: Schemas["DestinationOut"]) {
    toast.add({
      title: t("toast.destinationCreated", { name: destination.name }),
      type: "success",
    })
  }

  function handleAddedPlan(plan: Schemas["PlanOut"]) {
    toast.add({
      title: t("toast.planCreated", { name: plan.name }),
      type: "success",
    })
  }

  return (
    <div className="flex min-w-0 flex-col gap-4 md:gap-6">
      <Tabs defaultValue="versions" className="w-full">
        <TabsList className="w-full">
          <TabsTrigger value="versions">
            <LayoutListIcon data-icon="inline-start" />
            {t("view.tabs.versions")}
          </TabsTrigger>
          <TabsTrigger value="destinations">
            <FolderIcon data-icon="inline-start" />
            {t("view.tabs.destinations")}
          </TabsTrigger>
          <TabsTrigger value="plans">
            <ClockIcon data-icon="inline-start" />
            {t("view.tabs.plans")}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="versions" className="w-full pt-4">
          <VersionsCard />
        </TabsContent>
        <TabsContent value="destinations" className="w-full pt-4">
          <DestinationsCard onAdd={() => setAddDestinationOpen(true)} />
        </TabsContent>
        <TabsContent value="plans" className="w-full pt-4">
          <PlansCard onAdd={() => setAddPlanOpen(true)} onRun={handleRun} />
        </TabsContent>
      </Tabs>
      <AddDestinationDialog
        open={addDestinationOpen}
        onClose={() => setAddDestinationOpen(false)}
        onAdded={handleAddedDestination}
      />
      <AddPlanDialog
        open={addPlanOpen}
        onClose={() => setAddPlanOpen(false)}
        onAdded={handleAddedPlan}
      />
    </div>
  )
}
