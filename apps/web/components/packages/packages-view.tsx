"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"
import { PackageIcon } from "lucide-react"

import { api, type Schemas } from "@workspace/api-client"
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

import { ManagerPanel } from "@/components/packages/manager-panel"
import { ManagerLogo } from "@/components/packages/package-icon"
import { useApi } from "@/hooks/use-api"

type Manager = Schemas["ManagerOut"]

/** A tab per package manager detected on this host (docs/design/platform.md). */
export function PackagesView() {
  const { t } = useTranslation("packages")
  const managers = useApi(() => api.GET("/api/packages"))
  const [tab, setTab] = React.useState<string | null>(null)

  if (managers.status === "loading") return <Skeleton className="h-64 w-full" />
  if (managers.status === "error" || managers.data.length === 0) {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <PackageIcon />
          </EmptyMedia>
          <EmptyTitle>{t("view.noManagers")}</EmptyTitle>
          <EmptyDescription>
            {managers.status === "error"
              ? managers.error
              : t("view.noManagersHint")}
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  const list: Manager[] = managers.data
  const current =
    tab ?? (list.find((m) => m.available) ?? list[0])?.id ?? list[0]!.id
  return (
    <Tabs value={current} onValueChange={(v) => setTab(v as string)}>
      <TabsList>
        {list.map((m) => (
          <TabsTrigger key={m.id} value={m.id}>
            <ManagerLogo
              id={m.id}
              label={m.label}
              hasLogo={m.has_logo}
              className="size-5"
            />
            {m.label}
          </TabsTrigger>
        ))}
      </TabsList>
      {list.map((m) => (
        <TabsContent key={m.id} value={m.id} className="pt-4">
          <ManagerPanel manager={m} />
        </TabsContent>
      ))}
    </Tabs>
  )
}
