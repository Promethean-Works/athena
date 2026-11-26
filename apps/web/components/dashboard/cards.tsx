"use client"

import * as React from "react"
import { type ParseKeys } from "i18next"
import {
  ActivityIcon,
  BoxIcon,
  GlobeIcon,
  HardDriveIcon,
  HistoryIcon,
  LayoutGridIcon,
  PlugZapIcon,
  ServerIcon,
  ShieldCheckIcon,
  ThermometerIcon,
  ZapIcon,
  type LucideIcon,
} from "lucide-react"

import { ActivityCard } from "@/components/dashboard/activity-card"
import { AutomationCard } from "@/components/dashboard/automation-card"
import { ContainersCard } from "@/components/dashboard/containers-card"
import { DashboardApps } from "@/components/dashboard/dashboard-apps"
import { HostStatsCards } from "@/components/dashboard/host-stats-cards"
import {
  StorageCard,
  TemperaturesCard,
} from "@/components/dashboard/storage-card"
import { PowerCard } from "@/components/dashboard/power-card"
import { RemoteAccessCard } from "@/components/dashboard/remote-access-card"
import { HostCapabilities } from "@/components/host-capabilities"
import { BackupCard } from "@/components/dashboard/backup-card"
import { ServerOverview } from "@/components/server-overview"

export type CardSize = "half" | "full"

export type DashboardCardDef = {
  /** Stored in the user's layout; `^[a-z][a-z0-9-]{0,39}$` (checked by the server). */
  id: string
  /** Translation key of the title (translated at render, never at load). */
  titleKey: ParseKeys<"dashboard">
  /** Key of the one line for the Add card picker. */
  descriptionKey: ParseKeys<"dashboard">
  icon: LucideIcon
  defaultSize: CardSize
  /** Hidden from the picker when this capability isn't reported on the host. */
  capability?: string
  /** Hidden from the picker for users who aren't admins. */
  adminOnly?: boolean
  render: () => React.ReactNode
}

/**
 * Every card the dashboard can show, in default order. A card renders its own
 * `<Card>` and may render nothing (Temperatures on a host without sensors); the
 * grid hides empty cells. Ids are stored per user, so never rename one.
 */
export const DASHBOARD_CARDS: DashboardCardDef[] = [
  {
    id: "stats",
    titleKey: "cards.stats.title",
    descriptionKey: "cards.stats.description",
    icon: ActivityIcon,
    defaultSize: "full",
    render: () => <HostStatsCards />,
  },
  {
    id: "apps",
    titleKey: "cards.apps.title",
    descriptionKey: "cards.apps.description",
    icon: LayoutGridIcon,
    defaultSize: "full",
    capability: "containers",
    render: () => <DashboardApps />,
  },
  {
    id: "containers",
    titleKey: "cards.containers.title",
    descriptionKey: "cards.containers.description",
    icon: BoxIcon,
    defaultSize: "half",
    capability: "containers",
    render: () => <ContainersCard />,
  },
  {
    id: "automation",
    titleKey: "cards.automation.title",
    descriptionKey: "cards.automation.description",
    icon: ZapIcon,
    defaultSize: "half",
    capability: "automation",
    render: () => <AutomationCard />,
  },
  {
    id: "storage",
    titleKey: "cards.storage.title",
    descriptionKey: "cards.storage.description",
    icon: HardDriveIcon,
    defaultSize: "half",
    render: () => <StorageCard />,
  },
  {
    id: "server",
    titleKey: "cards.server.title",
    descriptionKey: "cards.server.description",
    icon: ServerIcon,
    defaultSize: "half",
    render: () => <ServerOverview />,
  },
  {
    id: "temperatures",
    titleKey: "cards.temperatures.title",
    descriptionKey: "cards.temperatures.description",
    icon: ThermometerIcon,
    defaultSize: "half",
    render: () => <TemperaturesCard />,
  },
  {
    id: "power",
    titleKey: "cards.power.title",
    descriptionKey: "cards.power.description",
    icon: PlugZapIcon,
    defaultSize: "half",
    capability: "host.power",
    render: () => <PowerCard />,
  },
  {
    id: "activity",
    titleKey: "cards.activity.title",
    descriptionKey: "cards.activity.description",
    icon: HistoryIcon,
    defaultSize: "half",
    adminOnly: true,
    render: () => <ActivityCard />,
  },
  {
    id: "remote-access",
    titleKey: "cards.remoteAccess.title",
    descriptionKey: "cards.remoteAccess.description",
    icon: GlobeIcon,
    defaultSize: "half",
    capability: "tunnel.*",
    render: () => <RemoteAccessCard />,
  },
  {
    id: "capabilities",
    titleKey: "cards.capabilities.title",
    descriptionKey: "cards.capabilities.description",
    icon: ShieldCheckIcon,
    defaultSize: "half",
    render: () => <HostCapabilities />,
  },
  {
    id: "backups",
    titleKey: "cards.backups.title",
    descriptionKey: "cards.backups.description",
    icon: ShieldCheckIcon,
    defaultSize: "half",
    capability: "backup",
    render: () => <BackupCard />,
  },
]

export const CARDS_BY_ID = new Map(DASHBOARD_CARDS.map((c) => [c.id, c]))

export type LayoutCard = { id: string; size: CardSize }

export const DEFAULT_LAYOUT: LayoutCard[] = DASHBOARD_CARDS.map((c) => ({
  id: c.id,
  size: c.defaultSize,
}))
