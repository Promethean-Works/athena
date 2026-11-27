"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"
import { DownloadIcon, PlayIcon, RefreshCwIcon } from "lucide-react"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import { Alert, AlertDescription } from "@workspace/ui/components/alert"
import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import { Field, FieldLabel } from "@workspace/ui/components/field"
import { RadioGroup, RadioGroupItem } from "@workspace/ui/components/radio-group"
import { Skeleton } from "@workspace/ui/components/skeleton"
import { Spinner } from "@workspace/ui/components/spinner"
import { toast } from "@workspace/ui/components/toast"

import { useCapabilities, useCapability } from "@/components/capabilities-provider"
import { JobDialog } from "@/components/job-dialog"
import { StepCard } from "@/components/onboarding/step-card"
import { useApi } from "@/hooks/use-api"

type Job = Schemas["JobOut"]

/** Pick, install and start a container runtime. Needs a `CapabilitiesProvider`. */
export function RuntimeStep({ onNext }: { onNext: () => void }) {
  const { t } = useTranslation("onboarding")
  const { refresh, refreshing } = useCapabilities()
  const capability = useCapability("containers")
  const options = useApi(() => api.GET("/api/containers/runtime/options"))
  const [chosen, setChosen] = React.useState<string | null>(null)
  const [job, setJob] = React.useState<Job | null>(null)
  const [busy, setBusy] = React.useState(false)
  const ready = capability?.status === "ready"
  const canStart = capability?.actions.includes("start")

  async function run(
    path: "/api/containers/runtime/install" | "/api/containers/runtime/start",
    failed: string
  ) {
    setBusy(true)
    const { data, error } =
      path === "/api/containers/runtime/install"
        ? await api.POST(path, { body: { id: chosen ?? "" } })
        : await api.POST(path)
    setBusy(false)
    if (data) setJob(data)
    else toast.add({ type: "error", title: failed, description: errorMessage(error) })
  }

  const finished = React.useCallback(
    (ok: boolean) => {
      if (!ok) return
      void refresh()
    },
    [refresh]
  )

  const list = options.status === "ok" ? options.data : []
  const selected =
    list.find((o) => o.id === (chosen ?? list.find((x) => x.recommended)?.id)) ??
    list[0]
  React.useEffect(() => {
    if (chosen === null && selected) setChosen(selected.id)
  }, [chosen, selected])

  return (
    <StepCard
      title={t("runtime.title")}
      description={t("runtime.description")}
      onContinue={onNext}
      onSkip={onNext}
    >
      {ready ? (
        <Alert>
          <AlertDescription>
            {t("runtime.ready", {
              provider: capability?.provider ?? "",
              detail: capability?.detail ?? "",
            })}
          </AlertDescription>
        </Alert>
      ) : (
        <>
          {capability?.status === "stopped" && (
            <Alert>
              <AlertDescription className="flex flex-col gap-2">
                {t("runtime.stopped", { provider: capability.provider ?? "" })}
                {canStart && (
                  <Button
                    size="sm"
                    className="self-start"
                    onClick={() =>
                      run("/api/containers/runtime/start", t("runtime.startFailed"))
                    }
                    disabled={busy}
                  >
                    <PlayIcon data-icon="inline-start" />
                    {t("runtime.start", { provider: capability.provider ?? "" })}
                  </Button>
                )}
              </AlertDescription>
            </Alert>
          )}
          {options.status === "loading" && <Skeleton className="h-24 w-full" />}
          {options.status === "error" && (
            <Alert variant="destructive">
              <AlertDescription>
                {t("runtime.loadFailed")}: {options.error}
              </AlertDescription>
            </Alert>
          )}
          {options.status === "ok" && list.length === 0 && (
            <p className="text-sm text-muted-foreground">{t("runtime.none")}</p>
          )}
          {list.length > 0 && (
            <RadioGroup
              value={selected?.id ?? ""}
              onValueChange={(v) => setChosen(v as string)}
              aria-label={t("runtime.title")}
            >
              {list.map((o) => (
                <FieldLabel key={o.id} htmlFor={`rt-${o.id}`}>
                  <Field orientation="horizontal">
                    <RadioGroupItem id={`rt-${o.id}`} value={o.id} />
                    <div className="flex flex-col gap-1">
                      <span className="flex flex-wrap items-center gap-2 text-sm font-medium">
                        {o.label}
                        {o.detected && (
                          <Badge variant="secondary">{t("runtime.detected")}</Badge>
                        )}
                        {o.recommended && (
                          <Badge variant="outline">{t("runtime.recommended")}</Badge>
                        )}
                        {o.tag === "new" || o.tag === "experimental" ? (
                          <Badge variant="outline">{t(`runtime.tag.${o.tag}`)}</Badge>
                        ) : null}
                      </span>
                      <span className="text-xs font-normal text-muted-foreground">
                        {o.description}
                      </span>
                    </div>
                  </Field>
                </FieldLabel>
              ))}
            </RadioGroup>
          )}
          {selected && selected.can_install && (
            <Button
              className="self-start"
              variant="secondary"
              onClick={() =>
                run("/api/containers/runtime/install", t("runtime.installFailed"))
              }
              disabled={busy}
            >
              {busy ? (
                <Spinner data-icon="inline-start" />
              ) : (
                <DownloadIcon data-icon="inline-start" />
              )}
              {t("runtime.install", { name: selected.label })}
            </Button>
          )}
          {selected && !selected.can_install && selected.manual.length > 0 && (
            <div className="flex flex-col gap-2">
              <p className="text-sm font-medium">{t("runtime.manualTitle")}</p>
              <ol className="list-decimal space-y-1 pl-5 text-xs text-muted-foreground">
                {selected.manual.map((line) => (
                  <li key={line} className="break-words">
                    {line}
                  </li>
                ))}
              </ol>
            </div>
          )}
          <Button
            className="self-start"
            variant="outline"
            size="sm"
            onClick={() => void refresh()}
            disabled={refreshing}
          >
            {refreshing ? (
              <Spinner data-icon="inline-start" />
            ) : (
              <RefreshCwIcon data-icon="inline-start" />
            )}
            {t("runtime.redetect")}
          </Button>
        </>
      )}
      <JobDialog job={job} onClose={() => setJob(null)} onFinished={finished} />
    </StepCard>
  )
}
