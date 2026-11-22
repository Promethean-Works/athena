"use client"

import { api } from "@workspace/api-client"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
import { Skeleton } from "@workspace/ui/components/skeleton"

import { UpdateAction } from "@/components/update-action"
import { useApi } from "@/hooks/use-api"
import { formatRelative, parseServerTime } from "@/lib/time"

/** Settings → System → Updates: the installed and latest version, and the way to update. */
export function UpdatesCard() {
  const update = useApi(() => api.GET("/api/system/update"))
  const info = update.status === "ok" ? update.data : null
  return (
    <Card>
      <CardHeader>
        <CardTitle>Updates</CardTitle>
        <CardDescription>
          Athena checks for a new release once a day (the switch above).
          Updating restarts Athena; your apps keep running.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        {update.status === "loading" ? (
          <Skeleton className="h-12 w-full" />
        ) : info === null ? (
          <p className="text-muted-foreground">
            Couldn&apos;t read the update status.
          </p>
        ) : (
          <>
            <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1">
              <dt className="text-muted-foreground">Installed</dt>
              <dd>{info.current}</dd>
              <dt className="text-muted-foreground">Latest</dt>
              <dd>
                {info.latest ??
                  (info.enabled ? "Not known yet" : "The update notice is off")}
              </dd>
              <dt className="text-muted-foreground">Last checked</dt>
              <dd>
                {info.checked_at
                  ? formatRelative(parseServerTime(info.checked_at))
                  : "Never"}
              </dd>
            </dl>
            {info.available ? (
              <UpdateAction info={info} />
            ) : (
              info.latest && <p>Athena is up to date.</p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
