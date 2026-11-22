"use client"

import { ArrowUpCircleIcon } from "lucide-react"

import { api } from "@workspace/api-client"
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@workspace/ui/components/alert"

import { CopyField } from "@/components/settings/copy-field"
import { useApi } from "@/hooks/use-api"

/**
 * "Athena x.y.z is available" with the upgrade command. The server checks GitHub once
 * a day (Settings → System turns it off), so this only reads its answer; it renders
 * nothing when there's no newer release, the check is off or it couldn't run.
 */
export function UpdateNotice() {
  const update = useApi(() => api.GET("/api/system/update"))
  if (update.status !== "ok" || !update.data.available) return null
  const { latest, current, command, release_url } = update.data
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
        <p>
          To upgrade, run this on the server (it installs the new version and
          restarts Athena; your data and settings stay):
        </p>
        <CopyField
          id="update-command"
          label="Upgrade command"
          value={command}
        />
      </AlertDescription>
    </Alert>
  )
}
