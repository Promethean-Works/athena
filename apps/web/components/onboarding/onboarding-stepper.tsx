"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"

import { api, errorMessage } from "@workspace/api-client"
import { Button } from "@workspace/ui/components/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
import { FieldError } from "@workspace/ui/components/field"
import { Progress } from "@workspace/ui/components/progress"
import { Spinner } from "@workspace/ui/components/spinner"

import { CapabilitiesProvider } from "@/components/capabilities-provider"
import { LanguageStep } from "@/components/onboarding/language-step"
import { LocationsStep } from "@/components/onboarding/locations-step"
import { NetworkStep } from "@/components/onboarding/network-step"
import { RuntimeStep } from "@/components/onboarding/runtime-step"
import { AiSetupStep } from "@/components/settings/ai-setup-step"

const STEPS = ["language", "runtime", "locations", "network", "ai", "done"] as const

/**
 * The steps after the account, one at a time, each skippable. Used by /setup (right
 * after the admin is created) and by /onboarding (run again from Settings).
 * Needs a signed-in admin. `onFinish` runs after the wizard is marked completed.
 */
export function OnboardingStepper({ onFinish }: { onFinish: () => void }) {
  const { t } = useTranslation("onboarding")
  const [index, setIndex] = React.useState(0)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const step = STEPS[index] ?? "language"
  const next = () => setIndex((i) => Math.min(i + 1, STEPS.length - 1))

  async function finish() {
    setBusy(true)
    setError(null)
    const { error: err } = await api.POST("/api/onboarding/complete")
    setBusy(false)
    if (err) return setError(errorMessage(err, t("done.finishFailed")))
    onFinish()
  }

  return (
    <CapabilitiesProvider>
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>{t(`steps.${step}`)}</span>
            <span>
              {t("progress", { current: index + 1, total: STEPS.length })}
            </span>
          </div>
          <Progress
            value={((index + 1) / STEPS.length) * 100}
            aria-label={t("progress", { current: index + 1, total: STEPS.length })}
          />
        </div>
        {step === "language" && <LanguageStep onNext={next} />}
        {step === "runtime" && <RuntimeStep onNext={next} />}
        {step === "locations" && <LocationsStep onNext={next} />}
        {step === "network" && <NetworkStep onNext={next} />}
        {step === "ai" && <AiSetupStep onDone={next} />}
        {step === "done" && (
          <Card>
            <CardHeader>
              <CardTitle className="text-xl">{t("done.title")}</CardTitle>
              <CardDescription>{t("done.description")}</CardDescription>
            </CardHeader>
            <CardContent>{error && <FieldError>{error}</FieldError>}</CardContent>
            <CardFooter>
              <Button className="w-full sm:w-auto" onClick={finish} disabled={busy}>
                {busy ? <Spinner data-icon="inline-start" /> : null}
                {t("done.finish")}
              </Button>
            </CardFooter>
          </Card>
        )}
      </div>
    </CapabilitiesProvider>
  )
}
