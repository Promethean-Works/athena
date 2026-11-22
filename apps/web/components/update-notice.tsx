"use client"

import { ArrowUpCircleIcon } from "lucide-react"

import { api } from "@workspace/api-client"
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@workspace/ui/components/alert"

import { UpdateAction } from "@/components/update-action"
import { useApi } from "@/hooks/use-api"

/**
 * "Athena x.y.z is available" with an Update now button (or the upgrade command). The server checks GitHub once
 * a day (Settings → System turns it off), so this only reads its answer; it renders
 * nothing when there's no newer release, the check is off or it couldn't run.
 */
export function UpdateNotice() {
  const update = useApi(() => api.GET("/api/system/update"))
  if (update.status !== "ok" || !update.data.available) return null
  const { latest, current, release_url } = update.data
  return (
    <Alert>
      <ArrowUpCircleIcon />
      <AlertTitle>Athena {latest} is available</AlertTitle>
      <AlertDescription className="flex flex-col gap-3">
        <p>
          This server runs {current}.{" "}
          {release_url && (
            <a
              href={release_url}
              target="_blank"
              rel="noreferrer"
              className="underline underline-offset-4"
            >
              See what&apos;s new
            </a>
          )}
        </p>
        <UpdateAction info={update.data} />
      </AlertDescription>
    </Alert>
  )
}
