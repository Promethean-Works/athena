"use client"

import { CopyIcon } from "lucide-react"
import { useTranslation } from "react-i18next"

import { Button } from "@workspace/ui/components/button"
import { toast } from "@workspace/ui/components/toast"

import { copyText } from "@/lib/clipboard"

/** The address other computers type to reach this host. */
export function serverHost(): string {
  return typeof window === "undefined" ? "server" : window.location.hostname
}

/** A mono-spaced address with a copy button. */
export function ConnectionString({
  value,
  label,
}: {
  value: string
  label: string
}) {
  const { t } = useTranslation("files")
  return (
    <div className="flex items-center gap-1">
      <span className="truncate font-mono text-xs text-muted-foreground">
        {value}
      </span>
      <Button
        variant="ghost"
        size="icon-xs"
        aria-label={t("network.copy", { label })}
        onClick={async () => {
          const ok = await copyText(value)
          toast.add(
            ok
              ? { type: "success", title: t("network.copied", { label }) }
              : { type: "error", title: t("network.copyFailed") }
          )
        }}
      >
        <CopyIcon />
      </Button>
    </div>
  )
}
