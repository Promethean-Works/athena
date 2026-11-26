"use client"

import * as React from "react"
import Link from "next/link"
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

import { AppStatusBadge, DeleteAppDialog, webPorts } from "@/components/apps/app-bits"
import { useAppJobs } from "@/components/apps/use-app-jobs"
import { useAppsList } from "@/components/apps/use-apps-list"
import { isAllowed, useCapabilities } from "@/components/capabilities-provider"
import { RuntimeEmpty } from "@/components/containers/runtime-empty"
import { cn } from "@workspace/ui/lib/utils"
import { AppIcon } from "@/components/store/app-icon"

const STATUS_LABEL: Record<string, string> = {
  running: "Running",
  partial: "Partly running",
  stopped: "Stopped",
  not_deployed: "Not deployed",
}

function AppsList() {
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
            <EmptyTitle>No apps yet</EmptyTitle>
            <EmptyDescription>
              Install one from the store, or deploy your own compose file.
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button render={<Link href="/store/" />} nativeButton={false}>
              <StoreIcon data-icon="inline-start" />
              Browse the store
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
          const info = `${label} · ${STATUS_LABEL[app.status] ?? app.status} · ${
            app.total === 1 ? "1 container" : `${app.total} containers`
          }`
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
                      : "bg-muted-foreground/50",
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
              ) : (
                <Link
                  href={`/apps/view/?name=${encodeURIComponent(app.name)}`}
                  title={info}
                  className="relative rounded-xl outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  {icon}
                </Link>
              )}
              <span className="w-full truncate text-sm font-medium" title={info}>
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
                  <span className="sr-only">Actions for {app.name}</span>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="min-w-48">
                  <DropdownMenuGroup>
                    <DropdownMenuLabel className="flex flex-col gap-1">
                      <span className="text-sm font-medium text-foreground">
                        {label}
                      </span>
                      <span className="flex flex-wrap items-center gap-1.5 font-normal">
                        <AppStatusBadge app={app} />
                        {app.total === 1 ? "1 container" : `${app.total} containers`}
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
                          {webPorts(app).length > 1 ? `Open :${p}` : "Open"}
                        </DropdownMenuItem>
                      ))}
                    <DropdownMenuItem
                      render={
                        <Link href={`/apps/view/?name=${encodeURIComponent(app.name)}`} />
                      }
                    >
                      <InfoIcon />
                      Details
                    </DropdownMenuItem>
                  </DropdownMenuGroup>
                  <DropdownMenuSeparator />
                  <DropdownMenuGroup>
                    {running ? (
                      <>
                        <DropdownMenuItem
                          onClick={() => void jobs.action(app.name, "restart").then(load)}
                        >
                          <RotateCwIcon />
                          Restart
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={() => void jobs.action(app.name, "stop").then(load)}
                        >
                          <SquareIcon />
                          Stop
                        </DropdownMenuItem>
                      </>
                    ) : (
                      <DropdownMenuItem
                        onClick={() => void jobs.action(app.name, "start").then(load)}
                      >
                        <PlayIcon />
                        Start
                      </DropdownMenuItem>
                    )}
                    <DropdownMenuItem
                      onClick={() => void jobs.action(app.name, "update").then(load)}
                    >
                      <RefreshCcwIcon />
                      Update images
                    </DropdownMenuItem>
                  </DropdownMenuGroup>
                  <DropdownMenuSeparator />
                  <DropdownMenuGroup>
                    <DropdownMenuItem
                      variant="destructive"
                      onClick={() => setRemoving(app.name)}
                    >
                      <Trash2Icon />
                      Remove
                    </DropdownMenuItem>
                  </DropdownMenuGroup>
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
  const { manifest } = useCapabilities()
  const containers = manifest?.capabilities.find((c) => c.id === "containers")
  // Same rule as the Apps nav item: hidden only where containers can't work at all.
  if (manifest && !isAllowed(manifest, "containers", true)) return null

  return (
    <Card>
      <CardHeader>
        <CardTitle>Apps</CardTitle>
        <CardDescription>What&apos;s running on this server</CardDescription>
        <CardAction className="flex gap-2">
          <Button variant="outline" size="sm" render={<Link href="/store/" />} nativeButton={false}>
            <StoreIcon data-icon="inline-start" />
            Store
          </Button>
          <Button variant="ghost" size="sm" render={<Link href="/apps/" />} nativeButton={false}>
            All apps
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
