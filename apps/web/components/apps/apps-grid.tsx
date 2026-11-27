"use client"

import * as React from "react"
import { Trans, useTranslation } from "react-i18next"
import Link from "next/link"
import {
  EllipsisVerticalIcon,
  LayoutGridIcon,
  PlayIcon,
  PlusIcon,
  RefreshCcwIcon,
  RotateCwIcon,
  SquareIcon,
  Trash2Icon,
} from "lucide-react"

import { Button } from "@workspace/ui/components/button"
import {
  Card,
  CardAction,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
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

import {
  AppStatusBadge,
  DeleteAppDialog,
  OpenLinks,
} from "@/components/apps/app-bits"
import { useAuth } from "@/components/auth-provider"
import { useAppJobs } from "@/components/apps/use-app-jobs"
import { useAppsList } from "@/components/apps/use-apps-list"
import { AppIcon } from "@/components/store/app-icon"

export function AppsGrid() {
  const { t } = useTranslation("apps")
  const { user } = useAuth()
  const { apps, error, load } = useAppsList()
  const [removing, setRemoving] = React.useState<string | null>(null)

  const jobs = useAppJobs(() => void load())

  if (error && !apps) {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyTitle>{t("list.failed")}</EmptyTitle>
          <EmptyDescription>{error}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  if (!apps) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
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
            <EmptyTitle>{t("grid.emptyTitle")}</EmptyTitle>
            <EmptyDescription>
              <Trans
                i18nKey="grid.emptyDescription"
                ns="apps"
                components={{ code: <code /> }}
              />
            </EmptyDescription>
          </EmptyHeader>
          {user.is_admin ? (
            <EmptyContent>
              <Button render={<Link href="/apps/new/" />} nativeButton={false}>
                <PlusIcon data-icon="inline-start" />
                {t("newApp")}
              </Button>
            </EmptyContent>
          ) : null}
        </Empty>
        {jobs.dialog}
      </>
    )
  }

  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {apps.map((app) => (
          <Card key={app.name}>
            <CardHeader>
              <CardTitle className="flex min-w-0 items-center gap-2">
                <AppIcon
                  title={app.title ?? app.name}
                  icon={app.icon}
                  className="size-6"
                />
                {user.is_admin ? (
                  <Link
                    href={`/apps/view/?name=${encodeURIComponent(app.name)}`}
                    className="truncate hover:underline"
                  >
                    {app.name}
                  </Link>
                ) : (
                  <span className="truncate">{app.name}</span>
                )}
              </CardTitle>
              <CardDescription>
                {t("grid.containerCount", { count: app.total })}
                {app.source === "docker-run"
                  ? ` · ${t("grid.fromDockerRun")}`
                  : ""}
              </CardDescription>
              <CardAction>
                <DropdownMenu>
                  <DropdownMenuTrigger
                    render={<Button variant="ghost" size="icon" />}
                  >
                    <EllipsisVerticalIcon />
                    <span className="sr-only">
                      {t("grid.actionsFor", { name: app.name })}
                    </span>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="min-w-44">
                    <DropdownMenuGroup>
                      {app.status === "running" ? (
                        <>
                          <DropdownMenuItem
                            onClick={() => jobs.action(app.name, "restart")}
                          >
                            <RotateCwIcon />
                            {t("actions.restart")}
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onClick={() => jobs.action(app.name, "stop")}
                          >
                            <SquareIcon />
                            {t("actions.stop")}
                          </DropdownMenuItem>
                        </>
                      ) : (
                        <DropdownMenuItem
                          onClick={() => jobs.action(app.name, "start")}
                        >
                          <PlayIcon />
                          {t("actions.start")}
                        </DropdownMenuItem>
                      )}
                      {user.is_admin ? (
                        <DropdownMenuItem
                          onClick={() => jobs.action(app.name, "update")}
                        >
                          <RefreshCcwIcon />
                          {t("actions.updateImages")}
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
                            {t("actions.remove")}
                          </DropdownMenuItem>
                        </DropdownMenuGroup>
                      </>
                    ) : null}
                  </DropdownMenuContent>
                </DropdownMenu>
              </CardAction>
            </CardHeader>
            <CardFooter className="mt-auto flex flex-wrap items-center gap-2">
              <AppStatusBadge app={app} />
              <div className="ml-auto flex flex-wrap gap-2">
                <OpenLinks app={app} />
              </div>
            </CardFooter>
          </Card>
        ))}
      </div>
      <DeleteAppDialog
        name={removing}
        onCancel={() => setRemoving(null)}
        onConfirm={(deleteData) => {
          const name = removing
          setRemoving(null)
          if (name) void jobs.remove(name, deleteData)
        }}
      />
      {jobs.dialog}
    </>
  )
}
