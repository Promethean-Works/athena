"use client"

import { CopyIcon } from "lucide-react"
import { useTranslation } from "react-i18next"

import { Field, FieldLabel } from "@workspace/ui/components/field"
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupInput,
} from "@workspace/ui/components/input-group"
import { toast } from "@workspace/ui/components/toast"

import { copyText } from "@/lib/clipboard"

/** A read-only value (a URL, a path, a username) with a copy button. */
export function CopyField({
  id,
  label,
  value,
}: {
  id: string
  label: string
  value: string
}) {
  const { t } = useTranslation("settings")
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <InputGroup>
        <InputGroupInput id={id} readOnly value={value} className="font-mono" />
        <InputGroupAddon align="inline-end">
          <InputGroupButton
            size="icon-xs"
            aria-label={t("copyField.copy", { label: label.toLowerCase() })}
            onClick={async () => {
              const ok = await copyText(value)
              toast.add(
                ok
                  ? { type: "success", title: t("copyField.copied", { label }) }
                  : { type: "error", title: t("copyField.failed") }
              )
            }}
          >
            <CopyIcon />
          </InputGroupButton>
        </InputGroupAddon>
      </InputGroup>
    </Field>
  )
}
