"use client"

import * as React from "react"
import {
  ActivityIcon,
  HardDriveIcon,
  LayoutGridIcon,
  ServerIcon,
  ShieldCheckIcon,
  ThermometerIcon,
  type LucideIcon,
} from "lucide-react"

import { DashboardApps } from "@/components/dashboard/dashboard-apps"
import { HostStatsCards } from "@/components/dashboard/host-stats-cards"
import {
  StorageCard,
  TemperaturesCard,
} from "@/components/dashboard/storage-card"
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
