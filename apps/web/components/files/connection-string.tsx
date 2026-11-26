"use client"

import { CopyIcon } from "lucide-react"

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
  return (
    <div className="flex items-center gap-1">
      <span className="truncate font-mono text-xs text-muted-foreground">
        {value}
      </span>
      <Button
        variant="ghost"
        size="icon-xs"
        aria-label={`Copy ${label}`}
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
      </Button>
    </div>
  )
}
