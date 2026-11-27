"use client"

import { useRouter } from "next/navigation"
import { useTranslation } from "react-i18next"

import { OnboardingStepper } from "@/components/onboarding/onboarding-stepper"

// Run the setup again (Settings → Appearance, or the dashboard's Finish setup card).
export default function OnboardingPage() {
  const router = useRouter()
  const { t } = useTranslation("onboarding")
  return (
    <div className="mx-auto flex w-full max-w-xl flex-col gap-4">
      <div>
        <h1 className="text-xl font-semibold">{t("page.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("page.description")}</p>
      </div>
      <OnboardingStepper onFinish={() => router.push("/")} />
    </div>
  )
}
