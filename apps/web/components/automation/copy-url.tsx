"use client"

import { CopyIcon } from "lucide-react"

import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupInput,
} from "@workspace/ui/components/input-group"
import { toast } from "@workspace/ui/components/toast"

import { copyText } from "@/lib/clipboard"

/** A read-only URL with a copy button. */
export function CopyUrl({
  id,
  label,
  value,
}: {
  id?: string
  label: string
  value: string
}) {
  return (
    <InputGroup>
      <InputGroupInput
        id={id}
        readOnly
        value={value}
        aria-label={id ? undefined : label}
        className="font-mono text-xs"
        onFocus={(e) => e.currentTarget.select()}
      />
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
  )
}
