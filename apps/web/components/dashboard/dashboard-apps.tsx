"use client"

import * as React from "react"
import Link from "next/link"
import { useTranslation } from "react-i18next"
import { type ParseKeys } from "i18next"
import {
  EllipsisVerticalIcon,
  ExternalLinkIcon,
  InfoIcon,
  LayoutGridIcon,
  PlayIcon,
  RefreshCcwIcon,
  RotateCwIcon,
  SquareIcon,
  StoreIcon,
  Trash2Icon,
} from "lucide-react"

import { Button } from "@workspace/ui/components/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@workspace/ui/components/dropdown-menu"
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
  AppStatusBadge,
  DeleteAppDialog,
  webPorts,
} from "@/components/apps/app-bits"
import { useAppJobs } from "@/components/apps/use-app-jobs"
import { useAppsList } from "@/components/apps/use-apps-list"
import { useAuth } from "@/components/auth-provider"
import { isAllowed, useCapabilities } from "@/components/capabilities-provider"
import { RuntimeEmpty } from "@/components/containers/runtime-empty"
import { cn } from "@workspace/ui/lib/utils"
import { AppIcon } from "@/components/store/app-icon"

const STATUS_LABEL: Record<string, ParseKeys<"dashboard">> = {
  running: "apps.status.running",
  partial: "apps.status.partial",
  stopped: "apps.status.stopped",
  not_deployed: "apps.status.notDeployed",
}

function AppsList() {
  const { user } = useAuth()
  const { t } = useTranslation("dashboard")
  const { apps, error, load } = useAppsList()
  const [removing, setRemoving] = React.useState<string | null>(null)

  const jobs = useAppJobs(() => void load())

  if (error && !apps) {
    return <p className="text-sm text-destructive">{error}</p>
  }
  if (!apps) {
    return (
      <div className="grid grid-cols-[repeat(auto-fill,minmax(6.5rem,1fr))] gap-2">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-36 w-full" />
        ))}
      </div>
    )
  }
  if (apps.length === 0) {
    return (
      <>
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <LayoutGridIcon />
            </EmptyMedia>
            <EmptyTitle>{t("apps.emptyTitle")}</EmptyTitle>
            <EmptyDescription>{t("apps.emptyDescription")}</EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button render={<Link href="/store/" />} nativeButton={false}>
              <StoreIcon data-icon="inline-start" />
              {t("apps.browseStore")}
            </Button>
          </EmptyContent>
        </Empty>
        {jobs.dialog}
      </>
    )
  }

  return (
    <>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(6.5rem,1fr))] gap-2">
        {apps.map((app) => {
          const running = app.status === "running"
          const port = webPorts(app)[0]
          const label = app.title ?? app.name
          const statusKey = STATUS_LABEL[app.status]
          const info = `${label} · ${
            statusKey ? t(statusKey) : app.status
          } · ${t("apps.containerCount", { count: app.total })}`
          const icon = (
            <>
              <AppIcon title={label} icon={app.icon} className="size-21" />
              <span
                aria-hidden
                className={cn(
                  "absolute right-1 bottom-1 size-3 rounded-full ring-2 ring-background",
                  running
                    ? "bg-emerald-500"
                    : app.status === "partial"
                      ? "bg-amber-500"
                      : "bg-muted-foreground/50"
                )}
              />
            </>
          )
          return (
            <div
              key={app.name}
              className="group relative flex flex-col items-center gap-1.5 rounded-xl p-2 text-center hover:bg-muted/50"
            >
              {running && port ? (
                <a
                  href={`${window.location.protocol}//${window.location.hostname}:${port}`}
                  target="_blank"
                  rel="noreferrer"
                  title={info}
                  className="relative rounded-xl outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  {icon}
                </a>
              ) : user.is_admin ? (
                <Link
                  href={`/apps/view/?name=${encodeURIComponent(app.name)}`}
                  title={info}
                  className="relative rounded-xl outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  {icon}
                </Link>
              ) : (
                <span title={info} className="relative rounded-xl">
                  {icon}
                </span>
              )}
              <span
                className="w-full truncate text-sm font-medium"
                title={info}
              >
                {label}
              </span>
              <DropdownMenu>
                <DropdownMenuTrigger
                  render={
                    <Button
                      variant="ghost"
                      size="icon-xs"
                      className="absolute top-0.5 right-0.5 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 aria-expanded:opacity-100 [@media(hover:none)]:opacity-100"
                    />
                  }
                >
                  <EllipsisVerticalIcon />
                  <span className="sr-only">
                    {t("apps.actionsFor", { name: app.name })}
                  </span>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="min-w-48">
                  <DropdownMenuGroup>
                    <DropdownMenuLabel className="flex flex-col gap-1">
                      <span className="text-sm font-medium text-foreground">
                        {label}
                      </span>
                      <span className="flex flex-wrap items-center gap-1.5 font-normal">
                        <AppStatusBadge app={app} />
                        {t("apps.containerCount", { count: app.total })}
                        {app.source === "docker-run" ? " · docker run" : ""}
                      </span>
                    </DropdownMenuLabel>
                  </DropdownMenuGroup>
                  <DropdownMenuSeparator />
                  <DropdownMenuGroup>
                    {running &&
                      webPorts(app).map((p) => (
                        <DropdownMenuItem
                          key={p}
                          render={
                            <a
                              href={`${window.location.protocol}//${window.location.hostname}:${p}`}
                              target="_blank"
                              rel="noreferrer"
                            />
                          }
                        >
                          <ExternalLinkIcon />
                          {webPorts(app).length > 1
                            ? t("apps.openPort", { port: p })
                            : t("apps.open")}
                        </DropdownMenuItem>
                      ))}
                    {user.is_admin ? (
                      <DropdownMenuItem
                        render={
                          <Link
                            href={`/apps/view/?name=${encodeURIComponent(app.name)}`}
                          />
                        }
                      >
                        <InfoIcon />
                        {t("apps.details")}
                      </DropdownMenuItem>
                    ) : null}
                  </DropdownMenuGroup>
                  <DropdownMenuSeparator />
                  <DropdownMenuGroup>
                    {running ? (
                      <>
                        <DropdownMenuItem
                          onClick={() =>
                            void jobs.action(app.name, "restart").then(load)
                          }
                        >
                          <RotateCwIcon />
                          {t("apps.restart")}
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={() =>
                            void jobs.action(app.name, "stop").then(load)
                          }
                        >
                          <SquareIcon />
                          {t("apps.stop")}
                        </DropdownMenuItem>
                      </>
                    ) : (
                      <DropdownMenuItem
                        onClick={() =>
                          void jobs.action(app.name, "start").then(load)
                        }
                      >
                        <PlayIcon />
                        {t("apps.start")}
                      </DropdownMenuItem>
                    )}
                    {user.is_admin ? (
                      <DropdownMenuItem
                        onClick={() =>
                          void jobs.action(app.name, "update").then(load)
                        }
                      >
                        <RefreshCcwIcon />
                        {t("apps.updateImages")}
                      </DropdownMenuItem>
                    ) : null}
                  </DropdownMenuGroup>
                  {user.is_admin ? (
                    <>
                      <DropdownMenuSeparator />
                      <DropdownMenuGroup>
                        <DropdownMenuItem
                          variant="destructive"
                          onClick={() => setRemoving(app.name)}
                        >
                          <Trash2Icon />
                          {t("apps.remove")}
                        </DropdownMenuItem>
                      </DropdownMenuGroup>
                    </>
                  ) : null}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          )
        })}
      </div>
      <DeleteAppDialog
        name={removing}
        onCancel={() => setRemoving(null)}
        onConfirm={(deleteData) => {
          const name = removing
          setRemoving(null)
          if (name) void jobs.remove(name, deleteData).then(load)
        }}
      />
      {jobs.dialog}
    </>
  )
}

/** The dashboard's app grid: status, Open links and start/stop, or the runtime's Start/setup. */
export function DashboardApps() {
  const { t } = useTranslation("dashboard")
  const { manifest } = useCapabilities()
  const containers = manifest?.capabilities.find((c) => c.id === "containers")
  // Same rule as the Apps nav item: hidden only where containers can't work at all.
  if (manifest && !isAllowed(manifest, "containers", true)) return null

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("apps.title")}</CardTitle>
        <CardDescription>{t("apps.subtitle")}</CardDescription>
        <CardAction className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            render={<Link href="/store/" />}
            nativeButton={false}
          >
            <StoreIcon data-icon="inline-start" />
            {t("apps.store")}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            render={<Link href="/apps/" />}
            nativeButton={false}
          >
            {t("apps.all")}
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        {!manifest ? (
          <Skeleton className="h-16 w-full" />
        ) : containers?.available ? (
          <AppsList />
        ) : (
          <RuntimeEmpty capability={containers} />
        )}
      </CardContent>
    </Card>
  )
}
