"use client"

import * as React from "react"
import Link from "next/link"
import { useTranslation } from "react-i18next"
import {
  CloudIcon,
  FolderIcon,
  HardDriveIcon,
  ServerIcon,
  ThermometerIcon,
} from "lucide-react"

import { api } from "@workspace/api-client"
import { Badge } from "@workspace/ui/components/badge"

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
import {
  Progress,
  ProgressLabel,
  ProgressValue,
} from "@workspace/ui/components/progress"
import { Skeleton } from "@workspace/ui/components/skeleton"

import { useCapabilities } from "@/components/capabilities-provider"
import { useRemotes } from "@/components/cloud/use-remotes"
import type { Location } from "@/components/files/file-utils"
import { useHostStats } from "@/components/dashboard/host-stats-provider"
import { formatBytes } from "@/lib/format"

type NetworkShare = {
  key: string
  name: string
  location_name: string
  read_only: boolean
}

function Section({
  icon: Icon,
  title,
  href,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>
  title: string
  href: string
  children: React.ReactNode
}) {
  return (
    <div className="flex min-w-0 flex-col gap-2 border-t pt-3">
      <Link
        href={href}
        className="flex items-center gap-2 text-xs font-medium text-muted-foreground hover:text-foreground"
      >
        <Icon className="size-3.5" />
        {title}
      </Link>
      <ul className="flex flex-col gap-1.5 text-sm">{children}</ul>
    </div>
  )
}

function Row({
  name,
  detail,
  badge,
}: {
  name: string
  detail?: string
  badge?: string
}) {
  return (
    <li className="flex min-w-0 items-center gap-2">
      <span className="min-w-0 truncate" title={detail}>
        {name}
      </span>
      {detail ? (
        <span className="min-w-0 truncate text-xs text-muted-foreground">
          {detail}
        </span>
      ) : null}
      {badge ? (
        <Badge variant="outline" className="ml-auto shrink-0">
          {badge}
        </Badge>
      ) : null}
    </li>
  )
}

/** Everything configured as storage: disks, file locations, cloud remotes, SMB and NFS shares. */
export function StorageCard() {
  const { t } = useTranslation("dashboard")
  const { host } = useHostStats()
  const { manifest } = useCapabilities()
  const { remotes } = useRemotes()
  const [locations, setLocations] = React.useState<Location[]>([])
  const [smb, setSmb] = React.useState<NetworkShare[]>([])
  const [nfs, setNfs] = React.useState<NetworkShare[]>([])
  const smbReady =
    manifest?.capabilities.find((c) => c.id === "shares.smb")?.status ===
    "ready"
  const nfsReady =
    manifest?.capabilities.find((c) => c.id === "shares.nfs")?.status ===
    "ready"

  React.useEffect(() => {
    void api.GET("/api/files/locations").then(({ data }) => {
      if (data) setLocations(data)
    })
  }, [])
  React.useEffect(() => {
    if (!smbReady) return
    void api.GET("/api/shares/smb").then(({ data }) => {
      if (data)
        setSmb(
          data.map((x) => ({
            key: `smb-${x.id}`,
            name: x.name,
            location_name: x.location_name,
            read_only: x.read_only,
          }))
        )
    })
  }, [smbReady])
  React.useEffect(() => {
    if (!nfsReady) return
    void api.GET("/api/shares/nfs").then(({ data }) => {
      if (data)
        setNfs(
          data.map((x) => ({
            key: `nfs-${x.id}`,
            name: `${x.location_name} (NFS)`,
            location_name: x.path,
            read_only: x.read_only,
          }))
        )
    })
  }, [nfsReady])
  const network = [...smb, ...nfs]
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <HardDriveIcon className="size-4 text-muted-foreground" />
          {t("storage.title")}
        </CardTitle>
        <CardDescription>{t("storage.description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {!host ? (
          <Skeleton className="h-10 w-full" />
        ) : host.disks.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {t("storage.noDisks")}
          </p>
        ) : (
          host.disks.map((disk) => (
            <Progress key={disk.mountpoint} value={disk.percent}>
              <ProgressLabel className="min-w-0 truncate" title={disk.device}>
                {disk.mountpoint}
                <span className="ml-2 text-xs font-normal text-muted-foreground">
                  {disk.fstype}
                </span>
              </ProgressLabel>
              <ProgressValue>
                {() =>
                  t("storage.diskUsage", {
                    used: formatBytes(disk.used),
                    total: formatBytes(disk.total),
                  })
                }
              </ProgressValue>
            </Progress>
          ))
        )}
        {locations.length > 0 ? (
          <Section
            icon={FolderIcon}
            title={t("storage.folders")}
            href="/files/"
          >
            {locations.map((l) => (
              <Row
                key={l.id}
                name={l.name}
                detail={l.path}
                badge={!l.available ? t("storage.unavailable") : undefined}
              />
            ))}
          </Section>
        ) : null}
        {remotes && remotes.length > 0 ? (
          <Section icon={CloudIcon} title={t("storage.cloud")} href="/cloud/">
            {remotes.map((r) => (
              <Row key={r.name} name={r.name} detail={r.type} />
            ))}
          </Section>
        ) : null}
        {network.length > 0 ? (
          <Section
            icon={ServerIcon}
            title={t("storage.shares")}
            href="/files/network/"
          >
            {network.map((x) => (
              <Row
                key={x.key}
                name={x.name}
                detail={x.location_name}
                badge={x.read_only ? t("storage.readOnly") : undefined}
              />
            ))}
          </Section>
        ) : null}
      </CardContent>
    </Card>
  )
}

/** Hardware sensors. Rendered only on hosts that report them (Linux). */
export function TemperaturesCard() {
  const { t: tr } = useTranslation("dashboard")
  const { host } = useHostStats()
  const temps = host?.temperatures
  if (!temps || temps.length === 0) return null
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ThermometerIcon className="size-4 text-muted-foreground" />
          {tr("temperatures.title")}
        </CardTitle>
        <CardDescription>{tr("temperatures.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-2 text-sm">
          {temps.map((t) => {
            const hot =
              t.high !== null && t.high !== undefined && t.current >= t.high
            return (
              <div key={t.label} className="contents">
                <dt className="truncate text-muted-foreground">{t.label}</dt>
                <dd
                  className={`tabular-nums ${hot ? "font-medium text-destructive" : ""}`}
                >
                  {t.current.toFixed(0)} °C
                </dd>
              </div>
            )
          })}
        </dl>
      </CardContent>
    </Card>
  )
}
