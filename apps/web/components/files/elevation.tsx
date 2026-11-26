"use client"

import { useTranslation } from "react-i18next"

import type { Schemas } from "@workspace/api-client"
import {
  Field,
  FieldDescription,
  FieldLabel,
} from "@workspace/ui/components/field"
import { Input } from "@workspace/ui/components/input"

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
  password: string
): { "X-Host-Password"?: string } {
  return needsHostPassword(capability) ? { "X-Host-Password": password } : {}
}

/** The "computer password" field, or a note that the host will ask on its own screen.
 * Renders nothing when no approval is needed. */
export function HostPasswordField({
  id,
  capability,
  value,
  onChange,
  disabled,
}: {
  id: string
  capability: Capability | undefined
  value: string
  onChange: (value: string) => void
  disabled?: boolean
}) {
  const { t } = useTranslation("files")
  if (capability?.status !== "needs_privilege") return null
  if (capability.elevation === "system") {
    return (
      <p className="text-sm text-muted-foreground">
        {t("network.password.systemHint")}
      </p>
    )
  }
  if (capability.elevation !== "password") return null
  return (
    <Field>
      <FieldLabel htmlFor={id}>{t("network.password.label")}</FieldLabel>
      <FieldDescription>{t("network.password.hint")}</FieldDescription>
      <Input
        id={id}
        type="password"
        autoComplete="current-password"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
      />
    </Field>
  )
}
