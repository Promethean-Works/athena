"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"
import {
  CheckIcon,
  ChevronDownIcon,
  CircleCheckIcon,
  CircleXIcon,
  CopyIcon,
  TriangleAlertIcon,
} from "lucide-react"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import { Alert, AlertDescription } from "@workspace/ui/components/alert"
import { Button } from "@workspace/ui/components/button"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@workspace/ui/components/collapsible"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldLabel,
} from "@workspace/ui/components/field"
import { Spinner } from "@workspace/ui/components/spinner"
import { Switch } from "@workspace/ui/components/switch"
import { toast } from "@workspace/ui/components/toast"
import { cn } from "@workspace/ui/lib/utils"

import { LogView } from "@/components/log-view"
import { useEventStream } from "@/hooks/use-event-stream"
import { copyText } from "@/lib/clipboard"
import i18n from "@/lib/i18n"

type Status = Schemas["UpdateStatus"]

const POLL_MS = 1500
const GIVE_UP_MS = 4 * 60 * 1000
const RESULT_WAIT_MS = 90 * 1000
const FINISHED = ["done", "rolled_back", "failed", "aborted"]
/** How the server starts the error of an update job whose backup failed. */
const BACKUP_FAILED = "The backup failed"

type Stage = "confirm" | "preparing" | "waiting" | "result" | "late"
type Step = "prepare" | "swap" | "check"

async function serverStart(): Promise<string | null> {
  try {
    const { data } = await api.GET("/api/health")
    return data?.started_at ?? null
  } catch {
    return null // the server is down: the swap is in progress
  }
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

/** The three things an update does: a check mark for each one that's done. */
function StepList({ active }: { active: Step }) {
  const { t } = useTranslation()
  const order: Step[] = ["prepare", "swap", "check"]
  const labels: Record<Step, string> = {
    prepare: t("update.dialog.stepPrepare"),
    swap: t("update.dialog.stepSwap"),
    check: t("update.dialog.stepCheck"),
  }
  return (
    <ol
      className="flex flex-col gap-2 text-sm"
      aria-label={t("update.dialog.steps")}
    >
      {order.map((step, index) => {
        const done = index < order.indexOf(active)
        const running = step === active
        return (
          <li key={step} className="flex items-center gap-2">
            <span
              className={cn(
                "flex size-5 shrink-0 items-center justify-center rounded-full border",
                done && "border-primary bg-primary text-primary-foreground"
              )}
            >
              {done ? (
                <CheckIcon className="size-3" />
              ) : running ? (
                <Spinner className="size-3" />
              ) : null}
            </span>
            <span className={cn(!done && !running && "text-muted-foreground")}>
              {labels[step]}
            </span>
          </li>
        )
      })}
    </ol>
  )
}

function LogDetails({ lines }: { lines: string[] }) {
  const { t } = useTranslation()
  if (!lines.length) return null
  return (
    <Collapsible className="flex w-full max-w-md flex-col gap-2 text-left">
      <div className="flex items-center justify-between gap-2">
        <CollapsibleTrigger render={<Button variant="ghost" size="sm" />}>
          <ChevronDownIcon
            data-icon="inline-start"
            className="transition-transform in-data-[panel-open]:rotate-180"
          />
          {t("log.title")}
        </CollapsibleTrigger>
        <Button
          variant="outline"
          size="sm"
          onClick={async () => {
            const ok = await copyText(lines.join("\n"))
            toast.add(
              ok
                ? { type: "success", title: t("log.copied") }
                : { type: "error", title: t("log.copyFailed") }
            )
          }}
        >
          <CopyIcon data-icon="inline-start" />
          {t("log.copy")}
        </Button>
      </div>
      <CollapsibleContent>
        <LogView lines={lines} className="h-48" />
      </CollapsibleContent>
    </Collapsible>
  )
}

function Result({ status }: { status: Status | null }) {
  const { t } = useTranslation()
  const to = status?.to_version ?? t("update.dialog.newVersion")
  const from = status?.from_version ?? t("update.dialog.oldVersion")
  const log = status?.log_tail ?? []
  if (status?.phase === "done") {
    return (
      <>
        <CircleCheckIcon className="size-8 text-primary" />
        <p className="text-lg font-medium">
          {t("update.dialog.updated", { to })}
        </p>
        <p className="text-sm text-muted-foreground">
          {t("update.dialog.reloading")}
        </p>
      </>
    )
  }
  if (status?.phase === "rolled_back") {
    return (
      <>
        <TriangleAlertIcon className="size-8 text-foreground" />
        <p className="text-lg font-medium">
          {t("update.dialog.rolledBackTitle", { to, from })}
        </p>
        <p className="max-w-md text-sm text-muted-foreground">
          {t("update.dialog.rolledBackBody")}
          {status.error
            ? t("update.dialog.reason", { reason: status.error })
            : null}
        </p>
        <LogDetails lines={log} />
      </>
    )
  }
  if (status) {
    return (
      <>
        <CircleXIcon className="size-8 text-destructive" />
        <p className="text-lg font-medium">
          {status.phase === "aborted"
            ? t("update.dialog.abortedTitle", { to })
            : t("update.dialog.failedTitle", { to })}
        </p>
        <p className="max-w-md text-sm text-muted-foreground">
          {status.error ? `${status.error}. ` : null}
          {status.phase === "aborted"
            ? t("update.dialog.abortedBody")
            : t("update.dialog.failedBody")}
        </p>
        <LogDetails lines={log} />
      </>
    )
  }
  return (
    <>
      <p className="text-lg font-medium">{t("update.dialog.back")}</p>
      <p className="max-w-sm text-sm text-muted-foreground">
        {t("update.dialog.backBody")}
      </p>
    </>
  )
}

/**
 * "Update Athena": confirm (what stops, what keeps running), then the server downloads
 * and checks the release (a job), then a full-screen wait while a helper swaps Athena
 * (the server is down), then the helper's own report from `GET /api/system/update/status`.
 * Mount it when the admin clicks the button; it stays until the page reloads.
 */
export function UpdateAthenaDialog({
  current,
  latest,
  releaseUrl,
  onClose,
}: {
  current: string
  latest: string
  releaseUrl: string | null
  onClose: () => void
}) {
  const { t } = useTranslation()
  const [stage, setStage] = React.useState<Stage>("confirm")
  const [before, setBefore] = React.useState<Status | null>(null)
  const [jobId, setJobId] = React.useState<string | null>(null)
  const [starting, setStarting] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [result, setResult] = React.useState<Status | null>(null)
  const [back, setBack] = React.useState(false)
  const [backup, setBackup] = React.useState(true)
  const bootId = React.useRef<string | null>(null)
  const stream = useEventStream(jobId ? `/api/jobs/${jobId}/events` : null)

  React.useEffect(() => {
    api.GET("/api/system/update/status").then(({ data }) => {
      if (data) setBefore(data)
    })
  }, [])

  // The job's end: succeeded means the helper has the plan and the server is about to exit.
  const jobStatus = stream.final?.status
  React.useEffect(() => {
    if (stage !== "preparing") return
    if (jobStatus === "succeeded" || (stream.phase === "error" && !jobStatus)) {
      setStage("waiting")
    } else if (jobStatus === "failed") {
      setError(stream.final?.error ?? i18n.t("update.dialog.prepareFailed"))
    }
  }, [stage, jobStatus, stream.phase, stream.final])

  // The swap: wait for a server with a new start time, then for the helper's last word.
  React.useEffect(() => {
    if (stage !== "waiting") return
    let cancelled = false
    void (async () => {
      const began = Date.now()
      for (;;) {
        await sleep(POLL_MS)
        if (cancelled) return
        const now = await serverStart()
        if (now && now !== bootId.current) break
        if (Date.now() - began > GIVE_UP_MS) {
          setStage("late")
          return
        }
      }
      setBack(true)
      const waited = Date.now()
      let last: Status | null = null
      while (Date.now() - waited < RESULT_WAIT_MS) {
        try {
          const { data } = await api.GET("/api/system/update/status")
          if (data) {
            last = data
            const mine = data.started_at !== before?.started_at
            if (FINISHED.includes(data.phase) && mine) break
          }
        } catch {
          // still coming up
        }
        await sleep(POLL_MS)
        if (cancelled) return
      }
      if (cancelled) return
      const finished =
        last &&
        FINISHED.includes(last.phase) &&
        last.started_at !== before?.started_at
      setResult(finished ? last : null)
      setStage("result")
    })()
    return () => {
      cancelled = true
    }
  }, [stage, before?.started_at])

  React.useEffect(() => {
    if (stage === "result" && result?.phase === "done") {
      const timer = window.setTimeout(() => window.location.reload(), 2500)
      return () => window.clearTimeout(timer)
    }
  }, [stage, result])

  async function start(withBackup: boolean) {
    setStarting(true)
    setError(null)
    bootId.current = await serverStart()
    const { data, error: failure } = await api.POST("/api/system/update", {
      body: { backup: withBackup },
    })
    setStarting(false)
    if (!data) {
      setError(errorMessage(failure))
      return
    }
    setJobId(data.id)
    setStage("preparing")
  }

  const backupPlan = before?.backup_plan ?? null
  const backupFailed = error?.startsWith(BACKUP_FAILED) ?? false
  const stops = before?.running_jobs ?? []
  const terminals = before?.terminals ?? 0
  const overlay = stage === "waiting" || stage === "result" || stage === "late"

  return (
    <>
      <Dialog
        open={stage === "confirm" || stage === "preparing"}
        onOpenChange={(open) => {
          if (!open && (stage === "confirm" || error)) onClose()
        }}
      >
        <DialogContent
          className="sm:max-w-lg"
          showCloseButton={stage === "confirm" || error !== null}
        >
          <DialogHeader>
            <DialogTitle>
              {stage === "confirm"
                ? t("update.dialog.confirmTitle")
                : error
                  ? t("update.dialog.notStartedTitle")
                  : t("update.dialog.preparingTitle")}
            </DialogTitle>
            <DialogDescription>
              {t("update.dialog.versions", { current, latest })}{" "}
              {releaseUrl && (
                <a
                  href={releaseUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="underline underline-offset-4"
                >
                  {t("update.notice.whatsNew")}
                </a>
              )}
            </DialogDescription>
          </DialogHeader>
          {stage === "confirm" ? (
            <div className="flex flex-col gap-3 text-sm">
              <p>{t("update.dialog.confirmBody")}</p>
              {stops.length || terminals ? (
                <Alert>
                  <TriangleAlertIcon />
                  <AlertDescription>
                    <p>{t("update.dialog.stopsTitle")}</p>
                    <ul className="list-disc pl-5">
                      {stops.map((title, index) => (
                        <li key={`${title}-${index}`}>{title}</li>
                      ))}
                      {terminals ? (
                        <li>
                          {t("update.dialog.terminals", { count: terminals })}
                        </li>
                      ) : null}
                    </ul>
                  </AlertDescription>
                </Alert>
              ) : null}
              {backupPlan ? (
                <Field orientation="horizontal">
                  <FieldContent>
                    <FieldLabel htmlFor="backup-first">
                      {t("update.dialog.backupFirst")}
                    </FieldLabel>
                    <FieldDescription>
                      {t("update.dialog.backupFirstHelp", { plan: backupPlan })}
                    </FieldDescription>
                  </FieldContent>
                  <Switch
                    id="backup-first"
                    checked={backup}
                    onCheckedChange={setBackup}
                  />
                </Field>
              ) : null}
              {error ? (
                <Alert variant="destructive">
                  <CircleXIcon />
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              ) : null}
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              {error ? null : <StepList active="prepare" />}
              {error ? (
                <Alert variant="destructive">
                  <CircleXIcon />
                  <AlertDescription>
                    {t("update.dialog.notChanged", {
                      error: error.replace(/\.$/, ""),
                      current,
                    })}
                  </AlertDescription>
                </Alert>
              ) : null}
              <LogView lines={stream.lines} className="h-40" />
            </div>
          )}
          <DialogFooter>
            {stage === "confirm" || error ? (
              <Button variant="outline" onClick={onClose} disabled={starting}>
                {error && stage === "preparing" ? t("close") : t("cancel")}
              </Button>
            ) : null}
            {backupFailed ? (
              <Button
                variant="destructive"
                onClick={() => void start(false)}
                disabled={starting}
              >
                {starting ? <Spinner data-icon="inline-start" /> : null}
                {t("update.dialog.updateAnyway")}
              </Button>
            ) : null}
            {stage === "confirm" ? (
              <Button
                onClick={() => void start(backupPlan !== null && backup)}
                disabled={starting}
              >
                {starting ? <Spinner data-icon="inline-start" /> : null}
                {t("update.dialog.update")}
              </Button>
            ) : null}
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {overlay ? (
        <div
          role="alert"
          aria-live="assertive"
          className="fixed inset-0 z-[100] flex flex-col items-center justify-center gap-4 overflow-y-auto bg-background p-6 text-center"
        >
          {stage === "waiting" ? (
            <>
              <Spinner className="size-6" />
              <p className="text-lg font-medium">
                {t("update.dialog.restarting")}
              </p>
              <p className="text-sm text-muted-foreground">
                {t("update.dialog.updatingTo", { latest })}
              </p>
              <StepList active={back ? "check" : "swap"} />
            </>
          ) : stage === "late" ? (
            <>
              <p className="text-lg font-medium">{t("update.notBackYet")}</p>
              <p className="max-w-sm text-sm text-muted-foreground">
                {t("update.dialog.lateBody")}
              </p>
              <Button onClick={() => window.location.reload()}>
                {t("update.reload")}
              </Button>
            </>
          ) : (
            <>
              <Result status={result} />
              {result?.phase !== "done" ? (
                <Button onClick={() => window.location.reload()}>
                  {t("update.reload")}
                </Button>
              ) : null}
            </>
          )}
        </div>
      ) : null}
    </>
  )
}
