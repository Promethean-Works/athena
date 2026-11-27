import { AppearanceForm } from "@/components/settings/appearance-form"
import { RunSetupAgainCard } from "@/components/onboarding/run-again-card"

export default function AppearanceSettingsPage() {
  return (
    <div className="flex flex-col gap-4">
      <AppearanceForm />
      <RunSetupAgainCard />
    </div>
  )
}
