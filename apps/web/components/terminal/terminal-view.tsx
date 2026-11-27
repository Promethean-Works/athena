"use client"

import * as React from "react"
import Link from "next/link"
import { useTranslation } from "react-i18next"
import { RotateCwIcon, SquareTerminalIcon } from "lucide-react"

import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@workspace/ui/components/empty"
import { Skeleton } from "@workspace/ui/components/skeleton"

import {
  TerminalSession,
  type SessionState,
} from "@/components/terminal/terminal-session"
import { useTerminalAccess } from "@/components/terminal/use-terminal-access"

export function SessionBadge({ state }: { state: SessionState }) {
  const { t } = useTranslation("terminal")
  switch (state.phase) {
    case "connecting":
      return <Badge variant="outline">{t("session.connecting")}</Badge>
    case "open":
      return <Badge variant="secondary">{t("session.connected")}</Badge>
    case "exited":
      return (
        <Badge variant={state.code === 0 ? "outline" : "destructive"}>
          {t("session.exited", { code: state.code })}
        </Badge>
      )
    case "closed":
      return <Badge variant="destructive">{t("session.disconnected")}</Badge>
  }
}

export function TerminalUnavailable({
  reason,
  settingsLink,
}: {
  reason: string
  settingsLink?: boolean
}) {
  const { t } = useTranslation("terminal")
  return (
    <Empty className="border">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <SquareTerminalIcon />
        </EmptyMedia>
        <EmptyTitle>{t("view.unavailableTitle")}</EmptyTitle>
        <EmptyDescription>{reason}</EmptyDescription>
      </EmptyHeader>
      {settingsLink && (
        <EmptyContent>
          <Button variant="outline" render={<Link href="/settings/system/" />} nativeButton={false}>
            {t("view.openSettings")}
          </Button>
        </EmptyContent>
      )}
    </Empty>
  )
}

/** The host shell, full height, with a status badge and a New session button. */
export function TerminalView() {
  const { t } = useTranslation("terminal")
  const access = useTerminalAccess()
  const [session, setSession] = React.useState(0)
  const [state, setState] = React.useState<SessionState>({
    phase: "connecting",
  })

  if (access.state === "loading") return <Skeleton className="h-96 w-full" />
  if (access.state === "unavailable") {
    return (
      <TerminalUnavailable
        reason={access.reason}
        settingsLink={access.settingsLink}
      />
    )
  }

  const ended = state.phase === "exited" || state.phase === "closed"
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <p className="text-sm text-muted-foreground">
            {t("view.description")}
          </p>
          <SessionBadge state={state} />
        </div>
        <Button
          variant={ended ? "default" : "outline"}
          size="sm"
          onClick={() => setSession((n) => n + 1)}
        >
          <RotateCwIcon data-icon="inline-start" />
          {t("view.newSession")}
        </Button>
      </div>
      {state.phase === "closed" && (
        <p role="alert" className="text-sm text-destructive">
          {state.reason}
        </p>
      )}
      <TerminalSession
        key={session}
        target="host"
        onStateChange={setState}
        className="h-[calc(100svh-var(--header-height)-9rem)] min-h-72"
      />
    </div>
  )
}
