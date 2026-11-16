"use client"

/* eslint-disable @next/next/no-img-element */

import * as React from "react"

import { cn } from "@workspace/ui/lib/utils"

import { AppIcon } from "@/components/store/app-icon"

/**
 * An app's cover image: its first screenshot, or a tinted panel with the app icon.
 * Screenshots come from the project's own repository, so a failed load falls back
 * to the icon instead of a broken image.
 */
export function StoreCover({
  title,
  icon,
  screenshot,
  className,
}: {
  title: string
  icon?: string | null
  screenshot?: string | null
  className?: string
}) {
  const [failed, setFailed] = React.useState(false)

  React.useEffect(() => setFailed(false), [screenshot])

  const showImage = Boolean(screenshot) && !failed

  return (
    <div
      className={cn(
        "relative aspect-video w-full overflow-hidden bg-muted",
        className
      )}
    >
      {showImage ? (
        <img
          src={screenshot ?? undefined}
          alt=""
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
          className="size-full object-cover object-top"
        />
      ) : (
        <div className="flex size-full items-center justify-center bg-linear-to-br from-primary/15 via-muted to-background">
          <AppIcon title={title} icon={icon} className="size-14 shadow-sm" />
        </div>
      )}
    </div>
  )
}
