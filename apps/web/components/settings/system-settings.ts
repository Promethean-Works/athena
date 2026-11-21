import { api, type Schemas } from "@workspace/api-client"

type SystemSettings = Schemas["SystemSettings"]

/**
 * Saves some system settings without undoing others. The PUT replaces the
 * whole row, and Security and Remote access each held their own copy, so a
 * save from one card used to send the other card's old values back (turning
 * the terminal switch also turned the tunnel off again). Read the latest row
 * first and change only `changes`.
 */
export async function patchSystemSettings(changes: Partial<SystemSettings>) {
  const latest = await api.GET("/api/settings/system")
  if (!latest.data) return latest
  return api.PUT("/api/settings/system", {
    body: { ...latest.data, ...changes },
  })
}
