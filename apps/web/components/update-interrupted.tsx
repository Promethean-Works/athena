"use client"

import * as React from "react"
import { TriangleAlertIcon, XIcon } from "lucide-react"
import { useTranslation } from "react-i18next"

import { api } from "@workspace/api-client"
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@workspace/ui/components/alert"
import { Button } from "@workspace/ui/components/button"

import { useAuth } from "@/components/auth-provider"
import { useApi } from "@/hooks/use-api"

const KEY = "athena.update-interrupted"

function Banner({ from, to, id }: { from: string; to: string; id: string }) {
  const { t } = useTranslation()
  const [hidden, setHidden] = React.useState(
    () => window.localStorage.getItem(KEY) === id
  )
  if (hidden) return null
  return (
    <Alert variant="destructive">
      <TriangleAlertIcon />
      <AlertTitle>{t("update.interrupted.title")}</AlertTitle>
      <AlertDescription className="flex flex-col gap-3">
        <p>
          {t("update.interrupted.body", { from, to })}
        </p>
        <Button
          variant="outline"
          size="sm"
          className="self-start"
          onClick={() => {
            window.localStorage.setItem(KEY, id)
            setHidden(true)
          }}
        >
          <XIcon data-icon="inline-start" />
          {t("update.interrupted.dismiss")}
        </Button>
      </AlertDescription>
    </Alert>
  )
}

/**
 * A warning for admins when an update began and its helper vanished without a last word
 * (`phase: "interrupted"` from `GET /api/system/update/status`). Dismissing it is
 * remembered for that update; the next update replaces the state, so a new one shows again.
 */
export function UpdateInterrupted() {
  const { user } = useAuth()
  if (!user.is_admin) return null
  return <InterruptedForAdmin />
}

function InterruptedForAdmin() {
  const { t } = useTranslation()
  const status = useApi(() => api.GET("/api/system/update/status"))
  if (status.status !== "ok" || status.data.phase !== "interrupted") return null
  const { from_version, to_version, started_at } = status.data
  return (
    <Banner
      from={from_version ?? t("update.interrupted.oldVersion")}
      to={to_version ?? t("update.interrupted.newVersion")}
      id={`${from_version}>${to_version}@${started_at}`}
    />
  )
}
