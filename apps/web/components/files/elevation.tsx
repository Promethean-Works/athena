"use client"

import { useTranslation } from "react-i18next"

import type { Schemas } from "@workspace/api-client"
type Capability = Schemas["Capability"]

/** True when Athena can create shares now, or after the admin approves (password or the
 * host's own prompt). */
export function canCreateShare(capability: Capability | undefined): boolean {
  return (
    capability?.status === "ready" ||
    (capability?.status === "needs_privilege" && !!capability.elevation)
  )
}

/** True when the host's account password has to come with the request (macOS). */
export function needsHostPassword(capability: Capability | undefined): boolean {
  return (
    capability?.status === "needs_privilege" &&
    capability.elevation === "password"
  )
}

/** The `params.header` of a share request: the password, only when one is needed. */
export function hostPasswordHeader(
  capability: Capability | undefined,
  password: string | null
): { "X-Host-Password"?: string } {
  return needsHostPassword(capability) && password
    ? { "X-Host-Password": password }
    : {}
}

/** Asks for the host password (through the shared dialog) when this share action needs
 * it. `undefined`: cancelled, stop; `null`: none needed. */
export async function passwordFor(
  capability: Capability | undefined,
  ask: (reason: string) => Promise<string | null>,
  reason: string
): Promise<string | null | undefined> {
  if (!needsHostPassword(capability)) return null
  return (await ask(reason)) ?? undefined
}

/** A note that the host will ask for approval on its own screen. Renders nothing for the
 * password case (the shared dialog asks) or when no approval is needed. */
export function ElevationHint({
  capability,
}: {
  capability: Capability | undefined
}) {
  const { t } = useTranslation("files")
  if (capability?.status !== "needs_privilege") return null
  if (capability.elevation !== "system") return null
  return (
    <p className="text-sm text-muted-foreground">
      {t("network.password.systemHint")}
    </p>
  )
}
