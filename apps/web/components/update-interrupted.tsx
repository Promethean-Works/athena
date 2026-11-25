"use client"

import * as React from "react"
import { TriangleAlertIcon, XIcon } from "lucide-react"

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
  const [hidden, setHidden] = React.useState(
    () => window.localStorage.getItem(KEY) === id
  )
  if (hidden) return null
  return (
    <Alert variant="destructive">
      <TriangleAlertIcon />
      <AlertTitle>The last update didn&apos;t finish</AlertTitle>
      <AlertDescription className="flex flex-col gap-3">
        <p>
          An update from {from} to {to} started but never reported back (the
          host may have lost power, or the update was stopped). Athena is up,
          but check that it&apos;s the version you expect. The update log is in
          the data folder (logs/update.log). To repair an install, run the
          installer command from the README on the server.
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
          Dismiss
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
  const status = useApi(() => api.GET("/api/system/update/status"))
  if (status.status !== "ok" || status.data.phase !== "interrupted") return null
  const { from_version, to_version, started_at } = status.data
  return (
    <Banner
      from={from_version ?? "the old version"}
      to={to_version ?? "the new one"}
      id={`${from_version}>${to_version}@${started_at}`}
    />
  )
}
