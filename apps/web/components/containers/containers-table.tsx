"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"
import {
  EllipsisVerticalIcon,
  PlayIcon,
  RotateCwIcon,
  ScrollTextIcon,
  SquareTerminalIcon,
  SquareIcon,
  Trash2Icon,
} from "lucide-react"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@workspace/ui/components/alert-dialog"
import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
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
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@workspace/ui/components/empty"
import { Skeleton } from "@workspace/ui/components/skeleton"
import { Spinner } from "@workspace/ui/components/spinner"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@workspace/ui/components/table"
import { toast } from "@workspace/ui/components/toast"

import { LogsSheet } from "@/components/containers/logs-sheet"
import { ShellSheet } from "@/components/terminal/shell-sheet"
import { useTerminalAccess } from "@/components/terminal/use-terminal-access"

type Container = Schemas["ContainerOut"]
type Action = "start" | "stop" | "restart"

const REFRESH_MS = 10_000

function StateBadge({ c }: { c: Container }) {
  const { t } = useTranslation("containers")
  if (c.state === "running")
    return <Badge variant="secondary">{t("state.running")}</Badge>
  if (c.state === "dead")
    return <Badge variant="destructive">{t("state.dead")}</Badge>
  if (c.state === "exited") {
    return (
      <Badge variant="outline">
        {c.exit_code
          ? t("state.exitedWithCode", { code: c.exit_code })
          : t("state.exited")}
      </Badge>
    )
  }
  const other = ["paused", "created", "restarting"] as const
  const known = other.find((s) => s === c.state)
  return (
    <Badge variant="outline" className="capitalize">
      {known ? t(`state.${known}`) : c.state}
    </Badge>
  )
}

function groups(containers: Container[]): [string, Container[]][] {
  const byProject = new Map<string, Container[]>()
  for (const c of containers) {
    const key = c.project ?? ""
    byProject.set(key, [...(byProject.get(key) ?? []), c])
  }
  return [...byProject.entries()].sort(([a], [b]) =>
    a === "" ? 1 : b === "" ? -1 : a.localeCompare(b)
  )
}

export function ContainersTable() {
  const { t } = useTranslation("containers")
  const [containers, setContainers] = React.useState<Container[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState<string | null>(null)
  const [logsFor, setLogsFor] = React.useState<Container | null>(null)
  const [shellFor, setShellFor] = React.useState<Container | null>(null)
  const canShell = useTerminalAccess().state === "ready"
  const [removing, setRemoving] = React.useState<Container | null>(null)

  const load = React.useCallback(async () => {
    const { data, error: err } = await api.GET("/api/containers")
    if (data) {
      setContainers(data)
      setError(null)
    } else {
      setError(errorMessage(err, t("table.listFailed")))
    }
  }, [t])

  React.useEffect(() => {
    void load()
    const timer = window.setInterval(load, REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [load])

  async function act(c: Container, action: Action) {
    setBusy(c.id)
    const path = `/api/containers/{ref}/${action}` as const
    const { error: err } = await api.POST(path, {
      params: { path: { ref: c.id } },
    })
    setBusy(null)
    if (err) {
      toast.add({
        type: "error",
        title: t(`table.actionFailed.${action}`, { name: c.name }),
        description: errorMessage(err),
      })
    }
    await load()
  }

  async function remove(c: Container) {
    setBusy(c.id)
    const { error: err } = await api.DELETE("/api/containers/{ref}", {
      params: { path: { ref: c.id }, query: { force: c.state === "running" } },
    })
    setBusy(null)
    setRemoving(null)
    if (err) {
      toast.add({
        type: "error",
        title: t("table.removeFailed", { name: c.name }),
        description: errorMessage(err),
      })
    } else {
      toast.add({
        type: "success",
        title: t("table.removed", { name: c.name }),
      })
    }
    await load()
  }

  if (error && !containers) {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyTitle>{t("table.listFailed")}</EmptyTitle>
          <EmptyDescription>{error}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  if (!containers) {
    return (
      <div className="flex flex-col gap-2">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    )
  }

  if (containers.length === 0) {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyTitle>{t("table.emptyTitle")}</EmptyTitle>
          <EmptyDescription>{t("table.emptyDescription")}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  return (
    <>
      <div className="overflow-hidden rounded-lg border">
        <Table>
          <TableHeader className="bg-muted">
            <TableRow>
              <TableHead>{t("table.name")}</TableHead>
              <TableHead className="hidden md:table-cell">
                {t("table.image")}
              </TableHead>
              <TableHead>{t("table.state")}</TableHead>
              <TableHead className="hidden lg:table-cell">
                {t("table.ports")}
              </TableHead>
              <TableHead className="w-10">
                <span className="sr-only">{t("table.actions")}</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {groups(containers).map(([project, rows]) => (
              <React.Fragment key={project || "~standalone"}>
                <TableRow className="hover:bg-transparent">
                  <TableCell
                    colSpan={5}
                    className="bg-muted/40 text-xs font-medium text-muted-foreground"
                  >
                    {project || t("table.standalone")}
                  </TableCell>
                </TableRow>
                {rows.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell className="font-medium">
                      <div className="flex flex-col">
                        <span>{c.name}</span>
                        <span className="text-xs text-muted-foreground md:hidden">
                          {c.image}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="hidden max-w-64 truncate text-muted-foreground md:table-cell">
                      {c.image}
                    </TableCell>
                    <TableCell>
                      <StateBadge c={c} />
                    </TableCell>
                    <TableCell className="hidden text-muted-foreground lg:table-cell">
                      {c.ports.join(", ") || "—"}
                    </TableCell>
                    <TableCell>
                      <DropdownMenu>
                        <DropdownMenuTrigger
                          render={
                            <Button
                              variant="ghost"
                              size="icon"
                              disabled={busy === c.id}
                            />
                          }
                        >
                          {busy === c.id ? (
                            <Spinner />
                          ) : (
                            <EllipsisVerticalIcon />
                          )}
                          <span className="sr-only">
                            {t("table.actionsFor", { name: c.name })}
                          </span>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="min-w-40">
                          <DropdownMenuGroup>
                            <DropdownMenuItem onClick={() => setLogsFor(c)}>
                              <ScrollTextIcon />
                              {t("table.logs")}
                            </DropdownMenuItem>
                            {canShell && c.state === "running" && (
                              <DropdownMenuItem onClick={() => setShellFor(c)}>
                                <SquareTerminalIcon />
                                {t("table.shell")}
                              </DropdownMenuItem>
                            )}
                          </DropdownMenuGroup>
                          <DropdownMenuSeparator />
                          <DropdownMenuGroup>
                            {c.state === "running" ? (
                              <>
                                <DropdownMenuItem
                                  onClick={() => act(c, "restart")}
                                >
                                  <RotateCwIcon />
                                  {t("table.restart")}
                                </DropdownMenuItem>
                                <DropdownMenuItem
                                  onClick={() => act(c, "stop")}
                                >
                                  <SquareIcon />
                                  {t("table.stop")}
                                </DropdownMenuItem>
                              </>
                            ) : (
                              <DropdownMenuItem onClick={() => act(c, "start")}>
                                <PlayIcon />
                                {t("table.start")}
                              </DropdownMenuItem>
                            )}
                          </DropdownMenuGroup>
                          <DropdownMenuSeparator />
                          <DropdownMenuGroup>
                            <DropdownMenuItem
                              variant="destructive"
                              onClick={() => setRemoving(c)}
                            >
                              <Trash2Icon />
                              {t("table.remove")}
                            </DropdownMenuItem>
                          </DropdownMenuGroup>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                ))}
              </React.Fragment>
            ))}
          </TableBody>
        </Table>
      </div>

      <LogsSheet container={logsFor} onClose={() => setLogsFor(null)} />
      <ShellSheet container={shellFor} onClose={() => setShellFor(null)} />

      <AlertDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("table.removeTitle", { name: removing?.name ?? "" })}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {removing?.state === "running"
                ? t("table.removeRunningDescription")
                : t("table.removeDescription")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("table.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => removing && remove(removing)}
            >
              {t("table.remove")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
