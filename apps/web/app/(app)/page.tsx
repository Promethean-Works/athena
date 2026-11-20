import { DashboardGrid } from "@/components/dashboard/dashboard-grid"
import { HostStatsProvider } from "@/components/dashboard/host-stats-provider"

export default function DashboardPage() {
  return (
    <HostStatsProvider>
      <DashboardGrid />
    </HostStatsProvider>
  )
}
