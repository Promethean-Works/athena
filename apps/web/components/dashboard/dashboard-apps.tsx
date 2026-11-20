"use client"

import * as React from "react"
import Link from "next/link"
import {
  EllipsisVerticalIcon,
  ExternalLinkIcon,
  LayoutGridIcon,
  PlayIcon,
  RefreshCcwIcon,
  RotateCwIcon,
  SettingsIcon,
  SquareIcon,
  StoreIcon,
  Trash2Icon,
} from "lucide-react"

import { Button } from "@workspace/ui/components/button"
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@workspace/ui/components/card"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@workspace/ui/components/dropdown-menu"
import { Skeleton } from "@workspace/ui/components/skeleton"

import { DeleteAppDialog, webPorts } from "@/components/apps/app-bits"
import { useAppJobs } from "@/components/apps/use-app-jobs"
import { type AppOut, useAppsList } from "@/components/apps/use-apps-list"
import { isAllowed, useCapabilities } from "@/components/capabilities-provider"
import { RuntimeEmpty } from "@/components/containers/runtime-empty"
import { AppIcon } from "@/components/store/app-icon"

const STATUS: Record<string, { label: string; dot: string }> = {
  running: { label: "Running", dot: "bg-primary" },
  partial: { label: "Partly running", dot: "bg-primary/50" },
  stopped: { label: "Stopped", dot: "bg-muted-foreground/40" },
  not_deployed: { label: "Not deployed", dot: "border border-muted-foreground/60" },
}

function statusOf(app: AppOut) {
  const s = STATUS[app.status] ?? STATUS.not_deployed!
  return app.status === "partial"
    ? { ...s, label: `${app.running} of ${app.total} running` }
    : s
}

/** One app: icon, name and status, an Open button when it serves a web page, and a menu. */
function AppCard({
  app,
  onAction,
  onRemove,
}: {
  app: AppOut
  onAction: (name: string, action: "start" | "stop" | "restart" | "update") => void
  onRemove: (name: string) => void
}) {
  const settingsHref = `/apps/view/?name=${encodeURIComponent(app.name)}`
  const port = webPorts(app)[0]
  const up = app.status === "running" || app.status === "partial"
  const appUrl =
    port && up
      ? `${window.location.protocol}//${window.location.hostname}:${port}`
      : null
  const title = app.title ?? app.name
  const status = statusOf(app)

  return (
    <div className="group/app flex items-center gap-3 rounded-xl border bg-card p-3 transition-colors hover:bg-accent/50">
      <Link
        href={settingsHref}
        className="flex min-w-0 flex-1 items-center gap-3 rounded-lg outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <AppIcon title={title} icon={app.icon} className="size-11 shrink-0" />
        <span className="flex min-w-0 flex-col">
          <span className="truncate text-sm font-medium">{title}</span>
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span
              aria-hidden
              className={`size-2 shrink-0 rounded-full ${status.dot}`}
            />
            <span className="truncate">{status.label}</span>
          </span>
        </span>
      </Link>
      {appUrl ? (
        <Button
          variant="outline"
          size="sm"
          nativeButton={false}
          render={<a href={appUrl} target="_blank" rel="noopener noreferrer" />}
          aria-label={`Open ${title}`}
        >
          <ExternalLinkIcon data-icon="inline-start" />
          Open
        </Button>
      ) : null}
      <DropdownMenu>
        <DropdownMenuTrigger
          render={<Button variant="ghost" size="icon-sm" />}
          aria-label={`Actions for ${title}`}
        >
          <EllipsisVerticalIcon />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="min-w-44">
          <DropdownMenuGroup>
            {up ? (
              <>
                <DropdownMenuItem onClick={() => onAction(app.name, "restart")}>
                  <RotateCwIcon />
                  Restart
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => onAction(app.name, "stop")}>
                  <SquareIcon />
                  Stop
                </DropdownMenuItem>
              </>
            ) : (
              <DropdownMenuItem onClick={() => onAction(app.name, "start")}>
                <PlayIcon />
                Start
              </DropdownMenuItem>
            )}
            <DropdownMenuItem onClick={() => onAction(app.name, "update")}>
              <RefreshCcwIcon />
              Update images
            </DropdownMenuItem>
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuItem render={<Link href={settingsHref} />}>
              <SettingsIcon />
              Settings and logs
            </DropdownMenuItem>
            <DropdownMenuItem
              variant="destructive"
              onClick={() => onRemove(app.name)}
            >
              <Trash2Icon />
              Remove
            </DropdownMenuItem>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
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
      <div className="grid gap-3 @2xl/main:grid-cols-2 @5xl/main:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-17 w-full" />
        ))}
      </div>
    )
  }
  if (apps.length === 0) {
    return (
      <>
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-dashed p-4">
          <span className="flex size-9 items-center justify-center rounded-lg bg-muted">
            <LayoutGridIcon className="size-4" />
          </span>
          <div className="mr-auto flex flex-col">
            <span className="text-sm font-medium">No apps yet</span>
            <span className="text-sm text-muted-foreground">
              Install one from the store, or deploy your own compose file.
            </span>
          </div>
          <Button size="sm" render={<Link href="/store/" />} nativeButton={false}>
            <StoreIcon data-icon="inline-start" />
            Browse the store
          </Button>
        </div>
        {jobs.dialog}
      </>
    )
  }

  return (
    <>
      <div className="grid gap-3 @2xl/main:grid-cols-2 @5xl/main:grid-cols-3">
        {apps.map((app) => (
          <AppCard
            key={app.name}
            app={app}
            onAction={(name, act) => void jobs.action(name, act).then(load)}
            onRemove={setRemoving}
          />
        ))}
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
