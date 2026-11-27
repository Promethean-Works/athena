"use client"

import {
  Avatar,
  AvatarFallback,
  AvatarImage,
} from "@workspace/ui/components/avatar"
import { cn } from "@workspace/ui/lib/utils"

function initial(label: string) {
  return (label.trim()[0] ?? "?").toUpperCase()
}

const query = (name: string, source?: string | null) =>
  new URLSearchParams({ name, ...(source ? { source } : {}) }).toString()

/**
 * The package manager's own logo, fetched by the server from the manager's official
 * site (nothing is bundled). Falls back to the first letter when there is none or
 * the host is offline.
 */
export function ManagerLogo({
  id,
  label,
  hasLogo,
  className,
}: {
  id: string
  label: string
  hasLogo: boolean
  className?: string
}) {
  return (
    <Avatar size="sm" className={cn("rounded-md after:rounded-md", className)}>
      {hasLogo ? (
        <AvatarImage
          src={`/api/packages/${id}/logo`}
          alt=""
          className="rounded-md object-contain"
        />
      ) : null}
      <AvatarFallback className="rounded-md text-xs">
        {initial(label)}
      </AvatarFallback>
    </Avatar>
  )
}

/** A package's icon from the manager's store (404 when it has none: the letter shows). */
export function PackageIcon({
  manager,
  name,
  source,
  label,
  hasIcon = true,
  size = "lg",
}: {
  manager: string
  name: string
  source?: string | null
  label: string
  hasIcon?: boolean
  size?: "default" | "sm" | "lg"
}) {
  return (
    <Avatar size={size} className="rounded-lg after:rounded-lg">
      {hasIcon ? (
        <AvatarImage
          src={`/api/packages/${manager}/icon?${query(name, source)}`}
          alt=""
          className="rounded-lg object-contain"
        />
      ) : null}
      <AvatarFallback className="rounded-lg">{initial(label)}</AvatarFallback>
    </Avatar>
  )
}
