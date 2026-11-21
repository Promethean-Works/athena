"use client"

import * as React from "react"
import {
  ActivityIcon,
  BoxIcon,
  GlobeIcon,
  HardDriveIcon,
  HistoryIcon,
  LayoutGridIcon,
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
import { RemoteAccessCard } from "@/components/dashboard/remote-access-card"
import { HostCapabilities } from "@/components/host-capabilities"
import { ServerOverview } from "@/components/server-overview"

export type CardSize = "half" | "full"

export type DashboardCardDef = {
  /** Stored in the user's layout; `^[a-z][a-z0-9-]{0,39}$` (checked by the server). */
  id: string
  title: string
  /** One line for the Add card picker. */
  description: string
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
    title: "System",
    description: "Live CPU, memory, network and disk activity.",
    icon: ActivityIcon,
    defaultSize: "full",
    render: () => <HostStatsCards />,
  },
  {
    id: "apps",
    title: "Apps",
    description: "Your apps, with their status and an Open button.",
    icon: LayoutGridIcon,
    defaultSize: "full",
    capability: "containers",
    render: () => <DashboardApps />,
  },
  {
    id: "containers",
    title: "Containers",
    description: "Running and stopped counts, and which ones need attention.",
    icon: BoxIcon,
    defaultSize: "half",
    capability: "containers",
    render: () => <ContainersCard />,
  },
  {
    id: "automation",
    title: "Automation",
    description: "Next scheduled runs and how recent runs went.",
    icon: ZapIcon,
    defaultSize: "half",
    capability: "automation",
    render: () => <AutomationCard />,
  },
  {
    id: "storage",
    title: "Storage",
    description: "Space used on each disk.",
    icon: HardDriveIcon,
    defaultSize: "half",
    render: () => <StorageCard />,
  },
  {
    id: "server",
    title: "Server",
    description: "Host name, operating system, uptime and versions.",
    icon: ServerIcon,
    defaultSize: "half",
    render: () => <ServerOverview />,
  },
  {
    id: "temperatures",
    title: "Temperatures",
    description: "Sensor readings, where the host reports them.",
    icon: ThermometerIcon,
    defaultSize: "half",
    render: () => <TemperaturesCard />,
  },
  {
    id: "activity",
    title: "Recent activity",
    description: "The latest changes from the audit log (admins only).",
    icon: HistoryIcon,
    defaultSize: "half",
    adminOnly: true,
    render: () => <ActivityCard />,
  },
  {
    id: "remote-access",
    title: "Remote access",
    description: "Tunnel status and the public address.",
    icon: GlobeIcon,
    defaultSize: "half",
    capability: "tunnel.*",
    render: () => <RemoteAccessCard />,
  },
  {
    id: "capabilities",
    title: "Capabilities",
    description: "What Athena found on this host.",
    icon: ShieldCheckIcon,
    defaultSize: "half",
    render: () => <HostCapabilities />,
  },
]

export const CARDS_BY_ID = new Map(DASHBOARD_CARDS.map((c) => [c.id, c]))

export type LayoutCard = { id: string; size: CardSize }

export const DEFAULT_LAYOUT: LayoutCard[] = DASHBOARD_CARDS.map((c) => ({
  id: c.id,
  size: c.defaultSize,
}))
