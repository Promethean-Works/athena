"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"

import { api, errorMessage } from "@workspace/api-client"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@workspace/ui/components/alert-dialog"
import { Button } from "@workspace/ui/components/button"
import { Spinner } from "@workspace/ui/components/spinner"
import { toast } from "@workspace/ui/components/toast"

const POLL_MS = 1000
const GIVE_UP_MS = 2 * 60 * 1000

async function startedAt(): Promise<string | null> {
  try {
    const { data } = await api.GET("/api/health")
    return data?.started_at ?? null
  } catch {
    return null // the server is down: the restart is in progress
  }
}

/**
 * "Restart Athena": a confirm dialog, then a full-screen wait that polls
 * `/api/health` until a server with a new start time answers, then reloads.
 */
export function RestartAthenaDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useTranslation()
  const [phase, setPhase] = React.useState<
    "idle" | "sending" | "waiting" | "late"
  >("idle")

  async function restart() {
    setPhase("sending")
    const before = await startedAt()
    const { error } = await api.POST("/api/system/restart")
    if (error) {
      setPhase("idle")
      onOpenChange(false)
      toast.add({
        type: "error",
        title: t("restart.failed"),
        description: errorMessage(error),
      })
      return
    }
    onOpenChange(false)
    setPhase("waiting")
    const began = Date.now()
    for (;;) {
      await new Promise((resolve) => setTimeout(resolve, POLL_MS))
      const now = await startedAt()
      if (now && now !== before) {
        window.location.reload()
        return
      }
      if (Date.now() - began > GIVE_UP_MS) {
        setPhase("late")
        return
      }
    }
  }

  return (
    <>
      <AlertDialog open={open} onOpenChange={onOpenChange}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("restart.title")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("restart.description")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={phase === "sending"}>
              {t("cancel")}
            </AlertDialogCancel>
            <AlertDialogAction onClick={restart} disabled={phase === "sending"}>
              {t("restart.confirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      {phase === "waiting" || phase === "late" ? (
        <div
          role="alert"
          aria-live="assertive"
          className="fixed inset-0 z-[100] flex flex-col items-center justify-center gap-4 bg-background p-6 text-center"
        >
          {phase === "waiting" ? (
            <>
              <Spinner className="size-6" />
              <p className="text-lg font-medium">{t("restart.waitingTitle")}</p>
              <p className="text-sm text-muted-foreground">
                {t("restart.waitingBody")}
              </p>
            </>
          ) : (
            <>
              <p className="text-lg font-medium">
                {t("update.notBackYet")}
              </p>
              <p className="max-w-sm text-sm text-muted-foreground">
                {t("restartLateBody")}
              </p>
              <Button onClick={() => window.location.reload()}>
                {t("update.reload")}
              </Button>
            </>
          )}
        </div>
      ) : null}
    </>
  )
}
