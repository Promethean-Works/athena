"use client"

import * as React from "react"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import { toast } from "@workspace/ui/components/toast"

export type Destination = Schemas["DestinationOut"]
export type Plan = Schemas["PlanOut"]
export type Version = Schemas["VersionOut"]
export type VersionFile = Schemas["VersionFileOut"]
export type Job = Schemas["JobOut"]

const REFRESH_MS = 10_000

export function useDestinations() {
  const [destinations, setDestinations] = React.useState<Destination[] | null>(
    null
  )
  const [error, setError] = React.useState<string | null>(null)

  const load = React.useCallback(async () => {
    const { data, error: err } = await api.GET("/api/backup/destinations")
    if (data) {
      setDestinations(data)
      setError(null)
    } else setError(errorMessage(err, "Couldn't list backup destinations"))
  }, [])

  React.useEffect(() => {
    void load()
    const timer = window.setInterval(load, REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [load])

  async function create(destination: Schemas["DestinationIn"]) {
    const { data, error: err } = await api.POST("/api/backup/destinations", {
      body: destination,
    })
    if (data) {
      toast.add({
        title: `Destination "${data.name}" created`,
        type: "success",
      })
      void load()
      return data
    }
    toast.add({
      title: errorMessage(err, "Couldn't create destination"),
      type: "error",
    })
    return null
  }

  async function del(id: string, deleteBackups = false) {
    const { error: err } = await api.DELETE(
      "/api/backup/destinations/{destination_id}",
      {
        params: {
          path: { destination_id: id },
          query: { delete_backups: deleteBackups },
        },
      }
    )
    if (err) {
      toast.add({
        title: errorMessage(err, "Couldn't delete destination"),
        type: "error",
      })
      return false
    }
    void load()
    return true
  }

  return { destinations, error, load, create, delete: del }
}

export function usePlans() {
  const [plans, setPlans] = React.useState<Plan[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)

  const load = React.useCallback(async () => {
    const { data, error: err } = await api.GET("/api/backup/plans")
    if (data) {
      setPlans(data)
      setError(null)
    } else setError(errorMessage(err, "Couldn't list backup plans"))
  }, [])

  React.useEffect(() => {
    void load()
    const timer = window.setInterval(load, REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [load])

  async function create(body: Schemas["PlanIn"]) {
    const { data, error: err } = await api.POST("/api/backup/plans", { body })
    if (data) {
      toast.add({ title: `Plan "${data.name}" created`, type: "success" })
      void load()
      return data
    }
    toast.add({
      title: errorMessage(err, "Couldn't create plan"),
      type: "error",
    })
    return null
  }

  async function update(id: string, body: Schemas["PlanIn"]) {
    const { data, error: err } = await api.PUT("/api/backup/plans/{plan_id}", {
      params: { path: { plan_id: id } },
      body,
    })
    if (data) {
      toast.add({ title: `Plan "${data.name}" updated`, type: "success" })
      void load()
      return data
    }
    toast.add({
      title: errorMessage(err, "Couldn't update plan"),
      type: "error",
    })
    return null
  }

  async function del(id: string) {
    const { error: err } = await api.DELETE("/api/backup/plans/{plan_id}", {
      params: { path: { plan_id: id } },
    })
    if (err) {
      toast.add({
        title: errorMessage(err, "Couldn't delete plan"),
        type: "error",
      })
      return false
    }
    void load()
    return true
  }

  async function run(id: string): Promise<Job | null> {
    const { data, error: err } = await api.POST(
      "/api/backup/plans/{plan_id}/run",
      { params: { path: { plan_id: id } } }
    )
    if (data) return data
    toast.add({
      title: errorMessage(err, "Couldn't start backup"),
      type: "error",
    })
    return null
  }

  return { plans, error, load, create, update, delete: del, run }
}

export function useVersions(destinationId?: string | null, item?: string) {
  const [versions, setVersions] = React.useState<Version[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)

  const load = React.useCallback(async () => {
    const { data, error: err } = await api.GET("/api/backup/versions", {
      params: {
        query: {
          destination_id: destinationId ?? null,
          item: item ?? null,
        },
      },
    })
    if (data) {
      setVersions(data)
      setError(null)
    } else setError(errorMessage(err, "Couldn't list backup versions"))
  }, [destinationId, item])

  React.useEffect(() => {
    void load()
  }, [load])

  return { versions, error, load }
}

export function useVersionFiles(destinationId: string, versionId: string) {
  const [files, setFiles] = React.useState<VersionFile[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [root, setRoot] = React.useState<string>("/")

  const load = React.useCallback(async () => {
    const { data, error: err } = await api.GET(
      "/api/backup/versions/{version_id}/files",
      {
        params: {
          path: { version_id: versionId },
          query: { destination_id: destinationId, path: root },
        },
      }
    )
    if (data) {
      setFiles(data.entries)
      setRoot(data.root)
      setError(null)
    } else setError(errorMessage(err, "Couldn't list version files"))
  }, [destinationId, versionId, root])

  React.useEffect(() => {
    void load()
  }, [load])

  return { files, error, load, root, setRoot }
}

export function useRestoreApp() {
  async function restore(body: Schemas["RestoreAppIn"]): Promise<Job | null> {
    const { data, error: err } = await api.POST("/api/backup/restore/app", {
      body,
    })
    if (data) return data
    toast.add({
      title: errorMessage(err, "Couldn't restore app"),
      type: "error",
    })
    return null
  }
  return { restore }
}
