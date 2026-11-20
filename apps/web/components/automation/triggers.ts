"use client"

import * as React from "react"

import { api, errorMessage, type Schemas } from "@workspace/api-client"

export type Trigger = Schemas["TriggerOut"]
export type JobRun = Schemas["JobRunOut"]
export type TriggerAction = Schemas["TriggerIn"]["action"]

const JOBS_REFRESH_MS = 5_000
const JOBS_SHOWN = 20

/** The trigger list; call `load()` after every change. */
export function useTriggers() {
  const [triggers, setTriggers] = React.useState<Trigger[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)

  const load = React.useCallback(async () => {
    const { data, error: err } = await api.GET("/api/automation/triggers")
    if (data) {
      setTriggers(data)
      setError(null)
    } else setError(errorMessage(err, "Couldn't list triggers"))
  }, [])

  React.useEffect(() => {
    void load()
  }, [load])

  return { triggers, error, load }
}

/** The most recent job runs, refreshed every 5 s so a firing trigger shows up on its own. */
export function useJobRuns() {
  const [runs, setRuns] = React.useState<JobRun[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)

  const load = React.useCallback(async () => {
    const { data, error: err } = await api.GET("/api/automation/jobs", {
      params: { query: { limit: JOBS_SHOWN } },
    })
    if (data) {
      setRuns(data)
      setError(null)
    } else setError(errorMessage(err, "Couldn't list job runs"))
  }, [])

  React.useEffect(() => {
    void load()
    const timer = window.setInterval(load, JOBS_REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [load])

  return { runs, error, load }
}

export function actionSummary(action: TriggerAction): string {
  if (action.kind === "app")
    return `${capitalize(action.verb)} app ${action.name}`
  if (action.verb === "refresh")
    return `Refresh ${action.manager} package lists`
  return `${capitalize(action.verb)} ${action.name} (${action.manager})`
}

function capitalize(word: string): string {
  return word.charAt(0).toUpperCase() + word.slice(1)
}

/** The full URL that fires a webhook trigger (POST, no session needed). */
export function webhookUrl(token: string): string {
  return `${window.location.origin}/api/automation/webhook/${token}`
}

/**
 * The server stores UTC times without an offset (SQLite drops it), so a bare
 * timestamp is read as UTC, not as the browser's local time.
 */
export function formatServerTime(value: string | null | undefined): string {
  if (!value) return "—"
  const hasOffset = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value)
  const date = new Date(hasOffset ? value : `${value}Z`)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}
