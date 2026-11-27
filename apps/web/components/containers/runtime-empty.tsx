"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"
import type { ParseKeys } from "i18next"
import { BoxIcon, PlayIcon, RefreshCwIcon } from "lucide-react"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import { Button } from "@workspace/ui/components/button"
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@workspace/ui/components/empty"
import { Spinner } from "@workspace/ui/components/spinner"
import { toast } from "@workspace/ui/components/toast"

import {
  type Capability,
  useCapabilities,
} from "@/components/capabilities-provider"
import { JobDialog } from "@/components/job-dialog"

type Job = Schemas["JobOut"]

/** How to install a runtime on each OS (Windows is detect-only: docs/design/platform.md). */
const SETUP: Record<
  string,
  {
    title: ParseKeys<"containers">
    steps: ({ cmd: string } | { key: ParseKeys<"containers"> })[]
  }
> = {
  darwin: {
    title: "runtime.setup.darwin.title",
    steps: [
      { cmd: "brew install colima docker docker-compose" },
      { cmd: "colima start" },
    ],
  },
  linux: {
    title: "runtime.setup.linux.title",
    steps: [
      { cmd: "curl -fsSL https://get.docker.com | sudo sh" },
      { cmd: "sudo systemctl enable --now docker" },
    ],
  },
  windows: {
    title: "runtime.setup.windows.title",
    steps: [
      { key: "runtime.setup.windows.wsl" },
      { key: "runtime.setup.windows.podman" },
      { key: "runtime.setup.windows.rancher" },
    ],
  },
}

export function RuntimeEmpty({
  capability,
}: {
  capability: Capability | undefined
}) {
  const { t } = useTranslation("containers")
  const { manifest, refresh, refreshing } = useCapabilities()
  const [job, setJob] = React.useState<Job | null>(null)
  const [starting, setStarting] = React.useState(false)
  const canStart = capability?.actions.includes("start")
  const setup = SETUP[manifest?.os ?? "linux"]

  async function start() {
    setStarting(true)
    const { data, error } = await api.POST("/api/containers/runtime/start")
    setStarting(false)
    if (data) setJob(data)
    else
      toast.add({
        type: "error",
        title: t("runtime.startFailed"),
        description: errorMessage(error),
      })
  }

  const finished = React.useCallback(
    (ok: boolean) => {
      if (ok) {
        void refresh()
        toast.add({ type: "success", title: t("runtime.running") })
      }
    },
    [refresh, t]
  )

  return (
    <Empty className="border">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <BoxIcon />
        </EmptyMedia>
        <EmptyTitle>
          {capability?.status === "stopped"
            ? capability.provider
              ? t("runtime.providerStopped", { provider: capability.provider })
              : t("runtime.stopped")
            : t("runtime.none")}
        </EmptyTitle>
        <EmptyDescription>
          {capability?.detail ?? t("runtime.notFound")}
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        {canStart ? (
          <Button onClick={start} disabled={starting}>
            {starting ? (
              <Spinner data-icon="inline-start" />
            ) : (
              <PlayIcon data-icon="inline-start" />
            )}
            {t("runtime.start", { provider: capability?.provider ?? "" })}
          </Button>
        ) : setup ? (
          <div className="flex w-full flex-col gap-2 text-left">
            <p className="text-sm font-medium">{t(setup.title)}</p>
            <pre className="rounded-lg border bg-muted/50 p-3 font-mono text-xs whitespace-pre-wrap">
              {setup.steps
                .map((step) => ("cmd" in step ? step.cmd : t(step.key)))
                .join("\n")}
            </pre>
          </div>
        ) : null}
        <Button
          variant="outline"
          size="sm"
          onClick={refresh}
          disabled={refreshing}
        >
          {refreshing ? (
            <Spinner data-icon="inline-start" />
          ) : (
            <RefreshCwIcon data-icon="inline-start" />
          )}
          {t("runtime.redetect")}
        </Button>
      </EmptyContent>
      <JobDialog job={job} onClose={() => setJob(null)} onFinished={finished} />
    </Empty>
  )
}
