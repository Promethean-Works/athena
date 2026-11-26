"use client"

import { AlertCircleIcon } from "lucide-react"

import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@workspace/ui/components/alert"
import type { Schemas } from "@workspace/api-client"

type Capability = Schemas["Capability"]

/** Why this host can't create shares of one kind, in the capability's own words.
 * Renders nothing when it can. */
export function ShareCapabilityNotice({
  capability,
  kind,
}: {
  capability: Capability | undefined
  kind: "SMB" | "NFS"
}) {
  if (capability?.status === "ready") return null
  const title =
    capability?.status === "needs_privilege"
      ? `${kind} sharing needs more permissions`
      : capability?.status === "missing"
        ? `${kind} sharing isn't set up yet`
        : `${kind} sharing isn't available on this computer`
  return (
    <Alert>
      <AlertCircleIcon />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        {capability?.detail ??
          "This host can't create these shares from Athena."}
      </AlertDescription>
    </Alert>
  )
}
