"use client"

import { CopyIcon } from "lucide-react"
import { useTranslation } from "react-i18next"

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
  const { t } = useTranslation("automation")
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
          aria-label={t("copyUrl.copy", { label })}
          onClick={async () => {
            const ok = await copyText(value)
            toast.add(
              ok
                ? { type: "success", title: t("copyUrl.copied", { label }) }
                : { type: "error", title: t("copyUrl.failed") }
            )
          }}
        >
          <CopyIcon />
        </InputGroupButton>
      </InputGroupAddon>
    </InputGroup>
  )
}
