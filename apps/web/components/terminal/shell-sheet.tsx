"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@workspace/ui/components/sheet"

import {
  TerminalSession,
  type SessionState,
} from "@/components/terminal/terminal-session"
import { SessionBadge } from "@/components/terminal/terminal-view"

/** A shell inside a running container (`docker exec -it … bash || sh`). */
export function ShellSheet({
  container,
  onClose,
}: {
  container: { id: string; name: string } | null
  onClose: () => void
}) {
  const { t } = useTranslation("terminal")
  const [state, setState] = React.useState<SessionState>({
    phase: "connecting",
  })

  return (
    <Sheet
      open={container !== null}
      onOpenChange={(open) => !open && onClose()}
    >
      <SheetContent
        side="right"
        className="w-full gap-0 data-[side=right]:sm:max-w-3xl"
      >
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            {t("shell.title", { name: container?.name ?? "" })}
            <SessionBadge state={state} />
          </SheetTitle>
          <SheetDescription>
            {state.phase === "closed"
              ? state.reason
              : t("shell.description")}
          </SheetDescription>
        </SheetHeader>
        <div className="flex min-h-0 flex-1 flex-col px-4 pb-4">
          {container && (
            <TerminalSession
              key={container.id}
              target={`container:${container.id}`}
              onStateChange={setState}
              className="flex-1"
            />
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
