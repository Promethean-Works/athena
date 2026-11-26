"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import { toast } from "@workspace/ui/components/toast"

import { JobDialog } from "@/components/job-dialog"

type Job = Schemas["JobOut"]
export type AppAction = "start" | "stop" | "restart" | "update"

/**
 * Runs app operations as jobs and shows their live progress. Render `dialog` once;
 * `onDone` runs after each job finishes (e.g. to reload the list).
 */
export function useAppJobs(onDone: (succeeded: boolean) => void) {
  const { t } = useTranslation("apps")
  const [job, setJob] = React.useState<Job | null>(null)

  const show = React.useCallback(
    (result: { data?: Job; error?: unknown }, failedTitle: string) => {
      if (result.data) setJob(result.data)
      else
        toast.add({
          type: "error",
          title: failedTitle,
          description: errorMessage(result.error),
        })
    },
    []
  )

  const action = React.useCallback(
    async (name: string, act: AppAction) =>
      show(
        await api.POST("/api/apps/{name}/{action}", {
          params: { path: { name, action: act } },
        }),
        t(`jobs.failed.${act}`, { name })
      ),
    [show, t]
  )

  const remove = React.useCallback(
    async (name: string, deleteData: boolean) =>
      show(
        await api.DELETE("/api/apps/{name}", {
          params: { path: { name }, query: { delete_data: deleteData } },
        }),
        t("jobs.failed.remove", { name })
      ),
    [show, t]
  )

  const dialog = (
    <JobDialog job={job} onClose={() => setJob(null)} onFinished={onDone} />
  )
  return { action, remove, show, dialog }
}
