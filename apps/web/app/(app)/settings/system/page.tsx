import { SettingsFileCard } from "@/components/settings/settings-file-card"
import { SystemForm } from "@/components/settings/system-form"
import { TunnelCard } from "@/components/settings/tunnel-card"
import { UpdatesCard } from "@/components/settings/updates-card"
import { WebDavCard } from "@/components/settings/webdav-card"

export default function SystemSettingsPage() {
  return (
    <div className="flex flex-col gap-4 md:gap-6">
      <SystemForm />
      <UpdatesCard />
      <TunnelCard />
      <WebDavCard />
      <SettingsFileCard />
    </div>
  )
}
