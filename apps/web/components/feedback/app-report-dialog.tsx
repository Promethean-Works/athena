"use client"

import * as React from "react"
import { ExternalLinkIcon, FlagIcon } from "lucide-react"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import { Button } from "@workspace/ui/components/button"
import { Checkbox } from "@workspace/ui/components/checkbox"
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
  FieldDescription,
  FieldLabel,
} from "@workspace/ui/components/field"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import { Spinner } from "@workspace/ui/components/spinner"
import { Textarea } from "@workspace/ui/components/textarea"
import { Diagnostics } from "@/components/feedback/feedback-dialog"

type Detail = Schemas["StoreAppDetail"]

const LOG_LINES = 50

/** "Report a problem" on a store app page, and its dialog. */
export function AppReportButton({ app }: { app: Detail }) {
  const [open, setOpen] = React.useState(false)
  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <FlagIcon data-icon="inline-start" />
        Report a problem
      </Button>
      {open ? (
        <AppReportDialog app={app} onClose={() => setOpen(false)} />
      ) : null}
    </>
  )
}

function AppReportDialog({
  app,
  onClose,
}: {
  app: Detail
  onClose: () => void
}) {
  const [info, setInfo] = React.useState<Schemas["FeedbackInfo"] | null>(null)
  const [issue, setIssue] = React.useState<Schemas["IssueUrl"] | null>(null)
  const [building, setBuilding] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [includeLogs, setIncludeLogs] = React.useState(false)
  const [installName, setInstallName] = React.useState(app.installed[0] ?? "")
  const [logs, setLogs] = React.useState("")
  const [loadingLogs, setLoadingLogs] = React.useState(false)

  React.useEffect(() => {
    api.GET("/api/feedback").then(({ data }) => setInfo(data ?? null))
  }, [])

  // Fetch the installed copy's logs only once the user asks for them.
  React.useEffect(() => {
    if (!includeLogs || !installName) return
    let cancelled = false
    setLoadingLogs(true)
    loadLogs(installName)
      .then((text) => !cancelled && setLogs(text))
      .catch((err: unknown) => {
        if (!cancelled) setLogs(`Couldn't load logs: ${String(err)}`)
      })
      .finally(() => !cancelled && setLoadingLogs(false))
    return () => {
      cancelled = true
    }
  }, [includeLogs, installName])

  // Rebuild the link (debounced) whenever what goes into it changes.
  React.useEffect(() => {
    let cancelled = false
    setBuilding(true)
    const timer = window.setTimeout(() => {
      api
        .POST("/api/feedback/issue-url", {
          body: {
            kind: "app",
            title: "",
            catalog: app.catalog,
            app_id: app.id,
            logs: includeLogs ? logs : "",
          },
        })
        .then(({ data, error: err }) => {
          if (cancelled) return
          setIssue(data ?? null)
          setError(
            data ? null : errorMessage(err, "Couldn't prepare the report")
          )
          setBuilding(false)
        })
    }, 300)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [app.catalog, app.id, includeLogs, logs])

  const where =
    issue?.target === "catalog"
      ? `the ${issue.target_name} catalog, which maintains this app`
      : (issue?.target_name ?? "Athena")

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Report a problem with {app.title}</DialogTitle>
          <DialogDescription>
            Opens a new issue for {where} in a new tab, with the app and this
            server&apos;s details filled in. You review it there before
            it&apos;s posted; issues are public.
          </DialogDescription>
        </DialogHeader>

        {app.installed.length ? (
          <Field>
            <div className="flex items-center gap-2">
              <Checkbox
                id="report-logs"
                checked={includeLogs}
                onCheckedChange={(checked) => setIncludeLogs(checked === true)}
              />
              <FieldLabel htmlFor="report-logs">
                Include the last {LOG_LINES} log lines
              </FieldLabel>
            </div>
            {includeLogs ? (
              <>
                {app.installed.length > 1 ? (
                  <Select
                    value={installName}
                    onValueChange={(value) =>
                      setInstallName(String(value ?? ""))
                    }
                  >
                    <SelectTrigger aria-label="Installed copy">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectGroup>
                        {app.installed.map((name) => (
                          <SelectItem key={name} value={name}>
                            {name}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                ) : null}
                <Textarea
                  aria-label="Logs to include"
                  value={loadingLogs ? "Loading logs…" : logs}
                  disabled={loadingLogs}
                  onChange={(e) => setLogs(e.target.value)}
                  className="max-h-60 min-h-32 font-mono text-xs"
                />
                <FieldDescription>
                  Remove passwords, tokens and addresses before you continue.
                  {issue?.logs_truncated
                    ? " Only the end of the logs fits in the link."
                    : null}
                </FieldDescription>
              </>
            ) : null}
          </Field>
        ) : null}

        <Diagnostics info={info} />
        {error ? <p className="text-sm text-destructive">{error}</p> : null}

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          {issue && !building && !loadingLogs ? (
            <Button
              nativeButton={false}
              render={
                <a
                  href={issue.url}
                  target="_blank"
                  rel="noreferrer"
                  onClick={onClose}
                />
              }
            >
              Open issue
              <ExternalLinkIcon data-icon="inline-end" />
            </Button>
          ) : (
            <Button aria-disabled>
              <Spinner data-icon="inline-start" />
              Preparing…
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

async function loadLogs(name: string): Promise<string> {
  const { data, error } = await api.GET("/api/apps/{name}", {
    params: { path: { name } },
  })
  if (!data) throw new Error(errorMessage(error, "app not found"))
  const parts = await Promise.all(
    data.containers.map(async (c) => {
      const res = await api.GET("/api/containers/{ref}/logs", {
        params: { path: { ref: c.id }, query: { tail: LOG_LINES } },
      })
      const lines = res.data?.lines ?? []
      return `== ${c.name} (${c.image}, ${c.state}) ==\n${lines.join("\n")}`
    })
  )
  return parts.join("\n\n") || "No containers found for this app."
}
