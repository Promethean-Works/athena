"use client"

import { useTranslation } from "react-i18next"

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@workspace/ui/components/sheet"

import { LogView } from "@/components/log-view"
import { useEventStream } from "@/hooks/use-event-stream"

/** Follows a container's logs live while open. */
export function LogsSheet({
  container,
  onClose,
}: {
  container: { id: string; name: string } | null
  onClose: () => void
}) {
  const { t } = useTranslation("containers")
  const stream = useEventStream(
    container
      ? `/api/containers/${encodeURIComponent(container.id)}/logs/stream?tail=300`
      : null
  )
  const state =
    stream.phase === "open"
      ? t("logs.following")
      : stream.phase === "done"
        ? t("logs.stopped")
        : stream.phase === "error"
          ? t("logs.disconnected")
          : t("logs.connecting")

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
          <SheetTitle>{t("logs.title", { name: container?.name })}</SheetTitle>
          <SheetDescription>{state}</SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 px-4 pb-4">
          <LogView
            lines={stream.lines}
            className="h-full"
            placeholder={t("logs.empty")}
          />
        </div>
      </SheetContent>
    </Sheet>
  )
}
