"use client"

import * as React from "react"
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
  const order: Step[] = ["prepare", "swap", "check"]
  const labels: Record<Step, string> = {
    prepare: "Download and check the release",
    swap: "Stop Athena, install and start it again",
    check: "Wait for the new version to answer",
  }
  return (
    <ol className="flex flex-col gap-2 text-sm" aria-label="Update steps">
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
  if (!lines.length) return null
  return (
    <Collapsible className="flex w-full max-w-md flex-col gap-2 text-left">
      <div className="flex items-center justify-between gap-2">
        <CollapsibleTrigger render={<Button variant="ghost" size="sm" />}>
          <ChevronDownIcon
            data-icon="inline-start"
            className="transition-transform in-data-[panel-open]:rotate-180"
          />
          Log
        </CollapsibleTrigger>
        <Button
          variant="outline"
          size="sm"
          onClick={async () => {
            const ok = await copyText(lines.join("\n"))
            toast.add(
              ok
                ? { type: "success", title: "Log copied" }
                : { type: "error", title: "Couldn't copy" }
            )
          }}
        >
          <CopyIcon data-icon="inline-start" />
          Copy log
        </Button>
      </div>
      <CollapsibleContent>
        <LogView lines={lines} className="h-48" />
      </CollapsibleContent>
    </Collapsible>
  )
}

function Result({ status }: { status: Status | null }) {
  const to = status?.to_version ?? "the new version"
  const from = status?.from_version ?? "the old one"
  const log = status?.log_tail ?? []
  if (status?.phase === "done") {
    return (
      <>
        <CircleCheckIcon className="size-8 text-primary" />
        <p className="text-lg font-medium">Updated to {to}</p>
        <p className="text-sm text-muted-foreground">Reloading the page…</p>
      </>
    )
  }
  if (status?.phase === "rolled_back") {
    return (
      <>
        <TriangleAlertIcon className="size-8 text-foreground" />
        <p className="text-lg font-medium">
          Update to {to} failed, still on {from}
        </p>
        <p className="max-w-md text-sm text-muted-foreground">
          Athena went back to the version you had, with your data as it was
          before the update.
          {status.error ? ` Reason: ${status.error}` : null}
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
            ? `Update to ${to} was stopped`
            : `Update to ${to} failed and Athena isn't running`}
        </p>
        <p className="max-w-md text-sm text-muted-foreground">
          {status.error ? `${status.error}. ` : null}
          {status.phase === "aborted"
            ? "Nothing was installed. Start Athena again, or run the installer command from the README."
            : "Run the installer command from the README on the server to repair it."}
        </p>
        <LogDetails lines={log} />
      </>
    )
  }
  return (
    <>
      <p className="text-lg font-medium">Athena is back</p>
      <p className="max-w-sm text-sm text-muted-foreground">
        Reload the page to see which version is running.
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
      setError(stream.final?.error ?? "The update couldn't be prepared")
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
                ? "Update Athena?"
                : error
                  ? "The update didn't start"
                  : "Preparing the update"}
            </DialogTitle>
            <DialogDescription>
              Athena {current} to {latest}.{" "}
              {releaseUrl && (
                <a
                  href={releaseUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="underline underline-offset-4"
                >
                  See what&apos;s new
                </a>
              )}
            </DialogDescription>
          </DialogHeader>
          {stage === "confirm" ? (
            <div className="flex flex-col gap-3 text-sm">
              <p>
                Athena restarts for a minute or two and the page reconnects.
                Your apps and containers keep running. If the new version
                doesn&apos;t start, Athena goes back to this one.
              </p>
              {stops.length || terminals ? (
                <Alert>
                  <TriangleAlertIcon />
                  <AlertDescription>
                    <p>These stop when Athena restarts:</p>
                    <ul className="list-disc pl-5">
                      {stops.map((title, index) => (
                        <li key={`${title}-${index}`}>{title}</li>
                      ))}
                      {terminals ? (
                        <li>
                          {terminals} open terminal
                          {terminals === 1 ? "" : "s"}
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
                      Back up Athena first
                    </FieldLabel>
                    <FieldDescription>
                      Saves Athena&apos;s settings and data with the backup plan
                      &ldquo;{backupPlan}&rdquo; before anything is stopped.
                      Your apps aren&apos;t touched.
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
                    {error.replace(/\.$/, "")}. Nothing was changed; Athena
                    still runs {current}.
                  </AlertDescription>
                </Alert>
              ) : null}
              <LogView lines={stream.lines} className="h-40" />
            </div>
          )}
          <DialogFooter>
            {stage === "confirm" || error ? (
              <Button variant="outline" onClick={onClose} disabled={starting}>
                {error && stage === "preparing" ? "Close" : "Cancel"}
              </Button>
            ) : null}
            {backupFailed ? (
              <Button
                variant="destructive"
                onClick={() => void start(false)}
                disabled={starting}
              >
                {starting ? <Spinner data-icon="inline-start" /> : null}
                Update anyway
              </Button>
            ) : null}
            {stage === "confirm" ? (
              <Button
                onClick={() => void start(backupPlan !== null && backup)}
                disabled={starting}
              >
                {starting ? <Spinner data-icon="inline-start" /> : null}
                Update
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
              <p className="text-lg font-medium">Restarting…</p>
              <p className="text-sm text-muted-foreground">
                Updating to {latest}. This page reloads when Athena is back.
              </p>
              <StepList active={back ? "check" : "swap"} />
            </>
          ) : stage === "late" ? (
            <>
              <p className="text-lg font-medium">
                Athena hasn&apos;t come back yet
              </p>
              <p className="max-w-sm text-sm text-muted-foreground">
                It can take longer on a slow host. If it stays down, check the
                update log in the data folder (logs/update.log).
              </p>
              <Button onClick={() => window.location.reload()}>
                Reload the page
              </Button>
            </>
          ) : (
            <>
              <Result status={result} />
              {result?.phase !== "done" ? (
                <Button onClick={() => window.location.reload()}>
                  Reload the page
                </Button>
              ) : null}
            </>
          )}
        </div>
      ) : null}
    </>
  )
}
