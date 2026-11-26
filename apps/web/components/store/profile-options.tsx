"use client"

import { ShieldAlertIcon } from "lucide-react"

import type { Schemas } from "@workspace/api-client"
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@workspace/ui/components/alert"
import { Badge } from "@workspace/ui/components/badge"
import { Checkbox } from "@workspace/ui/components/checkbox"
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldError,
  FieldLabel,
  FieldLegend,
  FieldSet,
  FieldTitle,
} from "@workspace/ui/components/field"

type Profile = Schemas["ProfileState"]

/** Warns that an app (or a part of it) can control every container on the server. */
export function DockerAccessAlert({
  title,
  children,
}: {
  title: string
  children?: React.ReactNode
}) {
  return (
    <Alert>
      <ShieldAlertIcon />
      <AlertTitle>{title}</AlertTitle>
      {children ? <AlertDescription>{children}</AlertDescription> : null}
    </Alert>
  )
}

/**
 * The optional parts of a store app (Compose profiles) as checkboxes. Parts this host
 * can't run are disabled with the reason.
 */
export function ProfileOptions({
  profiles,
  selected,
  onChange,
  error,
  hint = true,
}: {
  profiles: Profile[]
  selected: string[]
  onChange: (selected: string[]) => void
  error?: string
  /** Say they can be changed later (the install form; not on the app's own page). */
  hint?: boolean
}) {
  if (profiles.length === 0) return null
  const risky = profiles.filter(
    (p) => p.docker_access && selected.includes(p.id)
  )
  return (
    <FieldSet data-invalid={error ? true : undefined}>
      <FieldLegend variant="label">Optional parts</FieldLegend>
      <FieldDescription>
        Extra services that run next to the app.
        {hint ? " You can change this later from the app's page." : ""}
      </FieldDescription>
      <div className="grid gap-2">
        {profiles.map((p) => {
          const id = `profile-${p.id}`
          const disabled = Boolean(p.disabled_reason)
          return (
            <FieldLabel key={p.id} htmlFor={id}>
              <Field
                orientation="horizontal"
                data-disabled={disabled || undefined}
              >
                <Checkbox
                  id={id}
                  checked={selected.includes(p.id) && !disabled}
                  disabled={disabled}
                  onCheckedChange={(checked) =>
                    onChange(
                      checked
                        ? [...selected, p.id]
                        : selected.filter((s) => s !== p.id)
                    )
                  }
                />
                <FieldContent>
                  <FieldTitle>
                    {p.label}
                    {p.docker_access ? (
                      <Badge variant="outline">Controls Docker</Badge>
                    ) : null}
                  </FieldTitle>
                  {p.description ? (
                    <FieldDescription>{p.description}</FieldDescription>
                  ) : null}
                  {p.disabled_reason ? (
                    <FieldDescription>
                      Not available on this server: it {p.disabled_reason}.
                    </FieldDescription>
                  ) : null}
                </FieldContent>
              </Field>
            </FieldLabel>
          )
        })}
      </div>
      {error ? <FieldError>{error}</FieldError> : null}
      {risky.length > 0 ? (
        <DockerAccessAlert title="This gives the app control of this server's Docker">
          {risky.map((p) => p.label).join(", ")} can start, stop and read every
          container here, including your other apps.
        </DockerAccessAlert>
      ) : null}
    </FieldSet>
  )
}
