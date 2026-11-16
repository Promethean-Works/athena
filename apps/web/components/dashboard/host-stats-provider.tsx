"use client"

import * as React from "react"

import { api, type Schemas } from "@workspace/api-client"

export type StatsSample = Schemas["StatsSample"]
/** What each SSE `stats` event carries: the snapshot without its history. */
export type HostStats = Omit<Schemas["StatsSnapshot"], "history">

type State = {
  /** "loading" until the first snapshot; "error" if it couldn't be loaded. */
  status: "loading" | "ok" | "error"
  host: HostStats | null
  history: StatsSample[]
  /** True while the SSE stream is connected. */
  live: boolean
}

const HostStatsContext = React.createContext<State | null>(null)

/** The Athena server origin. When set (e.g. `next dev` on port 3000 with Athena
 * on 8420), the EventSource connects directly to it, bypassing the Next.js dev
 * proxy which buffers SSE streams. In production the UI is served same-origin by
 * FastAPI, so this is undefined and a relative URL is used. */
const API_ORIGIN =
  typeof process !== "undefined" && process.env.NEXT_PUBLIC_ATHENA_API_ORIGIN
    ? process.env.NEXT_PUBLIC_ATHENA_API_ORIGIN
    : undefined

/**
 * Loads `/api/system/stats` (current stats plus about an hour of samples), then
 * follows `/api/system/stats/stream` and appends each new sample. After the stream
 * drops and reconnects, the snapshot is loaded again to fill the gap.
 */
export function HostStatsProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = React.useState<State>({
    status: "loading",
    host: null,
    history: [],
    live: false,
  })

  React.useEffect(() => {
    let cancelled = false

    async function loadSnapshot() {
      try {
        const { data } = await api.GET("/api/system/stats")
        if (cancelled) return
        if (!data) {
          setState((s) => ({ ...s, status: s.host ? s.status : "error" }))
          return
        }
        const { history, ...host } = data
        setState((s) => ({ ...s, status: "ok", host, history }))
      } catch {
        if (!cancelled)
          setState((s) => ({ ...s, status: s.host ? s.status : "error" }))
      }
    }

    loadSnapshot()
    // In `next dev`, the /api proxy buffers SSE streams, so connect directly to
    // the Athena server (same-site, so the session cookie travels with
    // withCredentials). CORS headers are added on the server.
    const streamUrl =
      API_ORIGIN && API_ORIGIN !== window.location.origin
        ? `${API_ORIGIN}/api/system/stats/stream`
        : "/api/system/stats/stream"
    const source = new EventSource(streamUrl, {
      withCredentials: !!API_ORIGIN,
    })
    let dropped = false
    source.onopen = () => {
      setState((s) => ({ ...s, live: true }))
      if (dropped) loadSnapshot()
      dropped = false
    }
    source.onerror = () => {
      // EventSource retries by itself while the server is reachable.
      dropped = true
      setState((s) => ({ ...s, live: false }))
    }
    source.addEventListener("stats", (event) => {
      const host = JSON.parse((event as MessageEvent<string>).data) as HostStats
      setState((s) => {
        const latest = host.latest
        const last = s.history[s.history.length - 1]
        let history = s.history
        if (latest && (!last || latest.t > last.t)) {
          const max = Math.ceil(3600 / host.interval)
          history = [
            ...(history.length >= max ? history.slice(-max + 1) : history),
            latest,
          ]
        }
        return { status: "ok", host, history, live: true }
      })
    })

    return () => {
      cancelled = true
      source.close()
    }
  }, [])

  return (
    <HostStatsContext.Provider value={state}>
      {children}
    </HostStatsContext.Provider>
  )
}

export function useHostStats(): State {
  const value = React.useContext(HostStatsContext)
  if (!value)
    throw new Error("useHostStats must be used inside <HostStatsProvider>")
  return value
}

/** Like useHostStats, but null outside a provider (for cards used on several pages). */
export function useOptionalHostStats(): State | null {
  return React.useContext(HostStatsContext)
}
