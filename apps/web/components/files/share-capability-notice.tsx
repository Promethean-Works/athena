"use client"

import { AlertCircleIcon } from "lucide-react"
import { useTranslation } from "react-i18next"

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
  const { t } = useTranslation("files")
  if (capability?.status === "ready") return null
  const title =
    capability?.status === "needs_privilege"
      ? t("network.notice.needsPrivilege", { kind })
      : capability?.status === "missing"
        ? t("network.notice.missing", { kind })
        : t("network.notice.unsupported", { kind })
  return (
    <Alert>
      <AlertCircleIcon />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        {capability?.detail ?? t("network.notice.fallback")}
      </AlertDescription>
    </Alert>
  )
}
