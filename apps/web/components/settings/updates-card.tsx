"use client"

import { useTranslation } from "react-i18next"

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
  const { t } = useTranslation("settings")
  const update = useApi(() => api.GET("/api/system/update"))
  const info = update.status === "ok" ? update.data : null
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("updates.title")}</CardTitle>
        <CardDescription>{t("updates.description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        {update.status === "loading" ? (
          <Skeleton className="h-12 w-full" />
        ) : info === null ? (
          <p className="text-muted-foreground">{t("updates.readFailed")}</p>
        ) : (
          <>
            <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1">
              <dt className="text-muted-foreground">
                {t("updates.installed")}
              </dt>
              <dd>{info.current}</dd>
              <dt className="text-muted-foreground">{t("updates.latest")}</dt>
              <dd>
                {info.latest ??
                  (info.enabled
                    ? t("updates.unknown")
                    : t("updates.noticeOff"))}
              </dd>
              <dt className="text-muted-foreground">
                {t("updates.lastChecked")}
              </dt>
              <dd>
                {info.checked_at
                  ? formatRelative(parseServerTime(info.checked_at))
                  : t("updates.never")}
              </dd>
            </dl>
            {info.available ? (
              <UpdateAction info={info} />
            ) : (
              info.latest && <p>{t("updates.upToDate")}</p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
