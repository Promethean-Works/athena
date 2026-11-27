"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"

import { Button } from "@workspace/ui/components/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
import { Spinner } from "@workspace/ui/components/spinner"

/** The frame every wizard step shares: title, body, and Continue / Skip for now. */
export function StepCard({
  title,
  description,
  children,
  onContinue,
  continueLabel,
  onSkip,
  busy,
  canContinue = true,
}: {
  title: string
  description: string
  children: React.ReactNode
  onContinue: () => void
  continueLabel?: string
  onSkip: () => void
  busy?: boolean
  canContinue?: boolean
}) {
  const { t } = useTranslation("onboarding")
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xl">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">{children}</CardContent>
      <CardFooter className="flex flex-col gap-2 sm:flex-row-reverse">
        <Button
          className="w-full sm:w-auto"
          onClick={onContinue}
          disabled={busy || !canContinue}
        >
          {busy ? <Spinner data-icon="inline-start" /> : null}
          {continueLabel ?? t("continue")}
        </Button>
        <Button
          className="w-full sm:w-auto"
          variant="ghost"
          onClick={onSkip}
          disabled={busy}
        >
          {t("skip")}
        </Button>
      </CardFooter>
    </Card>
  )
}
