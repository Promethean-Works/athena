"use client"

import * as React from "react"
import Link from "next/link"
import { useTranslation } from "react-i18next"
import { ListChecksIcon } from "lucide-react"

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
import { Progress } from "@workspace/ui/components/progress"
import { toast } from "@workspace/ui/components/toast"

import { useAuth } from "@/components/auth-provider"
import { useApi } from "@/hooks/use-api"

/** The dashboard's "Finish setup" card: nothing at all once the wizard is completed. */
export function FinishSetupCard() {
  const { t } = useTranslation("onboarding")
  const { user } = useAuth()
  const [dismissed, setDismissed] = React.useState(false)
  const state = useApi(() => api.GET("/api/onboarding"))
  if (!user.is_admin || dismissed || state.status !== "ok" || state.data.completed)
    return null
  const done = state.data.steps.filter((s) => s.done).length
  const total = state.data.steps.length

  async function dismiss() {
    const { error } = await api.POST("/api/onboarding/complete")
    if (error)
      toast.add({
        type: "error",
        title: t("card.dismissFailed"),
        description: errorMessage(error),
      })
    else setDismissed(true)
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ListChecksIcon className="size-4 text-muted-foreground" />
          {t("card.title")}
        </CardTitle>
        <CardDescription>{t("card.description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <p className="text-sm text-muted-foreground">{t("card.body")}</p>
        <Progress
          value={(done / total) * 100}
          aria-label={t("progress", { current: done, total })}
        />
      </CardContent>
      <CardFooter className="gap-2">
        <Button nativeButton={false} render={<Link href="/onboarding/" />}>
          {t("card.open")}
        </Button>
        <Button variant="ghost" onClick={dismiss}>
          {t("card.dismiss")}
        </Button>
      </CardFooter>
    </Card>
  )
}
