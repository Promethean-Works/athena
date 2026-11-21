"use client"

import { CopyIcon } from "lucide-react"

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
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <InputGroup>
        <InputGroupInput id={id} readOnly value={value} className="font-mono" />
        <InputGroupAddon align="inline-end">
          <InputGroupButton
            size="icon-xs"
            aria-label={`Copy ${label.toLowerCase()}`}
            onClick={async () => {
              const ok = await copyText(value)
              toast.add(
                ok
                  ? { type: "success", title: `${label} copied` }
                  : { type: "error", title: "Couldn't copy" }
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
