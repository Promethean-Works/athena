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
  SquareIcon,
  StoreIcon,
  Trash2Icon,
} from "lucide-react"

import { Button } from "@workspace/ui/components/button"
import { Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@workspace/ui/components/card"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
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

import { DeleteAppDialog } from "@/components/apps/app-bits"
import { useAppJobs } from "@/components/apps/use-app-jobs"
import { type AppOut, useAppsList } from "@/components/apps/use-apps-list"
import { isAllowed, useCapabilities } from "@/components/capabilities-provider"
import { RuntimeEmpty } from "@/components/containers/runtime-empty"
import { AppIcon } from "@/components/store/app-icon"

function getStatusColor(status: AppOut["status"]) {
  switch (status) {
    case "running":
      return "bg-green-500"
    case "partial":
      return "bg-yellow-500"
    case "stopped":
      return "bg-gray-400"
    default:
      return "bg-gray-400"
  }
}

function getStatusLabel(status: AppOut["status"]) {
  switch (status) {
    case "running":
      return "Running"
    case "partial":
      return "Partial"
    case "stopped":
      return "Stopped"
    default:
      return "Not deployed"
  }
}

function AppCard({
  app,
  onAction,
  onRemove,
}: {
  app: AppOut
  onAction: (name: string, action: "start" | "stop" | "restart" | "update") => void
  onRemove: (name: string) => void
}) {
  const href = `/apps/view/?name=${encodeURIComponent(app.name)}`

  return (
    <Card
      key={app.name}
      className="group relative flex flex-col items-center p-4 min-h-[160px] hover:shadow-lg transition-shadow"
    >
      <CardHeader className="flex flex-col items-center w-full pb-2">
        <div className="relative">
          <Link href={href}>
            <AppIcon title={app.title ?? app.name} icon={app.icon} className="size-20" />
          </Link>
          {/* Status indicator dot on bottom right of icon */}
          <span
            className={`absolute bottom-1 right-1 size-3.5 rounded-full border-2 border-card ${getStatusColor(app.status)}`}
            title={getStatusLabel(app.status)}
          />
        </div>
        <Link
          href={href}
          className="mt-2 text-center text-sm font-medium truncate w-full max-w-[140px] hover:underline"
        >
          {app.name}
        </Link>
        <CardDescription className="text-center text-xs text-muted-foreground">
          {app.total === 1 ? "1 container" : `${app.total} containers`}
          {app.source === "docker-run" ? " · from docker run" : ""}
        </CardDescription>
      </CardHeader>

      {/* Three dots menu - visible on hover */}
      <div className="opacity-0 group-hover:opacity-100 transition-opacity duration-200 absolute top-2 right-2">
        <DropdownMenu>
          <DropdownMenuTrigger render={<Button variant="ghost" size="icon" className="h-8 w-8" />}>
            <EllipsisVerticalIcon className="h-4 w-4" />
            <span className="sr-only">Actions for {app.name}</span>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-48">
            <DropdownMenuGroup>
              {app.status === "running" ? (
                <>
                  <DropdownMenuItem
                    onClick={() => void onAction(app.name, "restart")}
                  >
                    <RotateCwIcon className="h-4 w-4" />
                    Restart
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() => void onAction(app.name, "stop")}
                  >
                    <SquareIcon className="h-4 w-4" />
                    Stop
                  </DropdownMenuItem>
                </>
              ) : (
                <DropdownMenuItem
                  onClick={() => void onAction(app.name, "start")}
                >
                  <PlayIcon className="h-4 w-4" />
                  Start
                </DropdownMenuItem>
              )}
              <DropdownMenuItem
                onClick={() => void onAction(app.name, "update")}
              >
                <RefreshCcwIcon className="h-4 w-4" />
                Update images
              </DropdownMenuItem>
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              <DropdownMenuItem
                onClick={() => window.open(`${window.location.protocol}//${window.location.hostname}:${app.web_port}`, '_blank', 'noopener,noreferrer')}
                className="flex items-center gap-2"
              >
                <ExternalLinkIcon className="h-4 w-4" />
                Open
              </DropdownMenuItem>
              <DropdownMenuItem
                variant="destructive"
                onClick={() => onRemove(app.name)}
              >
                <Trash2Icon className="h-4 w-4" />
                Remove
              </DropdownMenuItem>
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </Card>
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
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
        {[0, 1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-40 w-full" />
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
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
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
