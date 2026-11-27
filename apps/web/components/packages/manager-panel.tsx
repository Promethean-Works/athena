"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"

import { useLatest } from "@/hooks/use-latest"
import {
  ArrowUpCircleIcon,
  CircleAlertIcon,
  DownloadIcon,
  InfoIcon,
  RefreshCwIcon,
  SearchIcon,
  Trash2Icon,
} from "lucide-react"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@workspace/ui/components/alert"
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
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@workspace/ui/components/empty"
import { Input } from "@workspace/ui/components/input"
import { Skeleton } from "@workspace/ui/components/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@workspace/ui/components/table"
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@workspace/ui/components/tabs"
import { toast } from "@workspace/ui/components/toast"

import { JobDialog } from "@/components/job-dialog"
import {
  PackageDetailsSheet,
  type DetailsTarget,
} from "@/components/packages/package-details"
import { usePasswordPrompt } from "@/components/packages/password-dialog"

type Manager = Schemas["ManagerOut"]
type Job = Schemas["JobOut"]
type Installed = Schemas["InstalledPackage"]
type Upgradable = Schemas["UpgradablePackage"]
type Found = Schemas["PackageRef"]

const SHOWN = 200 // rows rendered at once; apt systems list thousands of packages

type Load<T> = { data: T | null; error: string | null; loading: boolean }

function useList<T>(fetcher: () => Promise<{ data?: T; error?: unknown }>) {
  const [state, setState] = React.useState<Load<T>>({
    data: null,
    error: null,
    loading: true,
  })
  const ref = useLatest(fetcher)
  const load = React.useCallback(async () => {
    setState((s) => ({ ...s, loading: true }))
    const { data, error } = await ref.current()
    setState({
      data: data ?? null,
      error: data ? null : errorMessage(error),
      loading: false,
    })
  }, [ref])
  React.useEffect(() => {
    void load()
  }, [load])
  return { ...state, load }
}

function PackageName({
  name,
  title,
  description,
}: {
  name: string
  title?: string | null
  description?: string | null
}) {
  // Show the id under the title only when it says something new ("J" vs "j" doesn't).
  const showId = title && title.toLowerCase() !== name.toLowerCase()
  return (
    <div className="flex min-w-0 flex-col">
      <span className="truncate font-medium">{title ?? name}</span>
      {showId ? (
        <span className="truncate font-mono text-xs text-muted-foreground">
          {name}
        </span>
      ) : null}
      {description ? (
        <span className="line-clamp-2 text-sm whitespace-normal text-muted-foreground">
          {description}
        </span>
      ) : null}
    </div>
  )
}

/** "formula" is Homebrew's default and says nothing; casks, remotes and buckets do. */
function sourceBadge(source?: string | null) {
  return source && source !== "formula" ? source : null
}

function DetailsButton({
  name,
  onOpen,
}: {
  name: string
  onOpen: () => void
}) {
  const { t } = useTranslation("packages")
  return (
    <Button
      variant="ghost"
      size="icon-sm"
      aria-label={t("details.buttonLabel", { name })}
      title={t("details.button")}
      onClick={onOpen}
    >
      <InfoIcon />
    </Button>
  )
}

function ListError({ error }: { error: string }) {
  const { t } = useTranslation("packages")
  return (
    <Alert variant="destructive">
      <CircleAlertIcon />
      <AlertTitle>{t("listError")}</AlertTitle>
      <AlertDescription className="font-mono text-xs break-all">
        {error}
      </AlertDescription>
    </Alert>
  )
}

function Confirm({
  open,
  title,
  description,
  action,
  destructive,
  onCancel,
  onConfirm,
}: {
  open: boolean
  title: string
  description: string
  action: string
  destructive?: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const { t } = useTranslation("packages")
  return (
    <AlertDialog open={open} onOpenChange={(o) => !o && onCancel()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
          <AlertDialogAction
            variant={destructive ? "destructive" : "default"}
            onClick={onConfirm}
          >
            {action}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

type Pending =
  { kind: "uninstall"; name: string } | { kind: "upgrade-all" } | null

/** One package manager: installed packages, available updates, and search. */
export function ManagerPanel({ manager }: { manager: Manager }) {
  const { t } = useTranslation("packages")
  const id = manager.id
  const path = { params: { path: { manager: id } } }
  const installed = useList<Installed[]>(() =>
    api.GET("/api/packages/{manager}/installed", path)
  )
  const updates = useList<Upgradable[]>(() =>
    api.GET("/api/packages/{manager}/upgradable", path)
  )
  const [job, setJob] = React.useState<Job | null>(null)
  const [pending, setPending] = React.useState<Pending>(null)
  const [filter, setFilter] = React.useState("")
  const [query, setQuery] = React.useState("")
  const [results, setResults] = React.useState<Found[] | null>(null)
  const [searching, setSearching] = React.useState(false)
  const [searchError, setSearchError] = React.useState<string | null>(null)
  const [lastQuery, setLastQuery] = React.useState("")
  const [details, setDetails] = React.useState<DetailsTarget | null>(null)

  const started = (result: { data?: Job; error?: unknown }, failTitle: string) => {
    if (result.data) setJob(result.data)
    else
      toast.add({
        type: "error",
        title: failTitle,
        description: errorMessage(result.error),
      })
  }

  async function runSearch(q: string) {
    setSearching(true)
    setSearchError(null)
    setLastQuery(q)
    const { data, error } = await api.GET("/api/packages/{manager}/search", {
      params: { path: { manager: id }, query: { q } },
    })
    setSearching(false)
    if (data) setResults(data)
    else {
      setResults(null)
      setSearchError(errorMessage(error))
    }
  }

  // A manager that installs system-wide (MacPorts) asks for the computer's password
  // before each change; reads don't need it.
  const needsPassword = !manager.available && manager.elevation === "password"
  const { ask, dialog: passwordDialog } = usePasswordPrompt()
  async function withPassword(run: (password: string | null) => Promise<void>) {
    if (!needsPassword) return run(null)
    const password = await ask(manager.label)
    if (password) await run(password)
  }

  const install = (pkg: Pick<Found, "name" | "source">) =>
    withPassword(async (password) =>
      started(
        await api.POST("/api/packages/{manager}/install", {
          ...path,
          body: { name: pkg.name, source: pkg.source ?? null, password },
        }),
        t("toast.installFailed", { name: pkg.name })
      )
    )
  const uninstall = (name: string) =>
    withPassword(async (password) =>
      started(
        await api.POST("/api/packages/{manager}/uninstall", {
          ...path,
          body: { name, password },
        }),
        t("toast.uninstallFailed", { name })
      )
    )
  const upgrade = (name: string | null) =>
    withPassword(async (password) =>
      started(
        await api.POST("/api/packages/{manager}/upgrade", {
          ...path,
          body: { name, password },
        }),
        name
          ? t("toast.upgradeFailed", { name })
          : t("toast.upgradeAllFailed")
      )
    )
  const refresh = () =>
    withPassword(async (password) =>
      started(
        await api.POST("/api/packages/{manager}/refresh", {
          ...path,
          body: { password },
        }),
        t("toast.refreshFailed")
      )
    )

  const afterJob = React.useCallback(() => {
    void installed.load()
    void updates.load()
    if (lastQuery) void runSearch(lastQuery)
    // runSearch only reads state setters and the stable manager id.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [installed.load, updates.load])

  if (!manager.available && !needsPassword) {
    return (
      <Alert>
        <InfoIcon />
        <AlertTitle>{t("unavailable", { name: manager.label })}</AlertTitle>
        <AlertDescription>
          {manager.detail ?? t("unavailableHint")}
        </AlertDescription>
      </Alert>
    )
  }

  const upgradeByName = new Map(
    (updates.data ?? []).map((u) => [u.name, u] as const)
  )
  const needle = filter.trim().toLowerCase()
  const filtered = (installed.data ?? []).filter(
    (p) =>
      !needle ||
      p.name.toLowerCase().includes(needle) ||
      (p.title ?? "").toLowerCase().includes(needle) ||
      (p.description ?? "").toLowerCase().includes(needle)
  )
  const updateCount = updates.data?.length ?? 0

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <p className="mr-auto text-sm text-muted-foreground">
          {manager.detail}
        </p>
        {manager.can_refresh ? (
          <Button variant="outline" size="sm" onClick={refresh}>
            <RefreshCwIcon data-icon="inline-start" />
            {t("refreshLists")}
          </Button>
        ) : null}
        <Button
          size="sm"
          disabled={updateCount === 0}
          onClick={() => setPending({ kind: "upgrade-all" })}
        >
          <ArrowUpCircleIcon data-icon="inline-start" />
          {t("upgradeAll")}
        </Button>
      </div>
      {manager.note ? (
        <Alert>
          <InfoIcon />
          <AlertDescription>{manager.note}</AlertDescription>
        </Alert>
      ) : null}

      <Tabs defaultValue="installed">
        <TabsList>
          <TabsTrigger value="installed">
            {t("tabs.installed")}
            {installed.data ? (
              <Badge variant="secondary">{installed.data.length}</Badge>
            ) : null}
          </TabsTrigger>
          <TabsTrigger value="updates">
            {t("tabs.updates")}
            {updateCount ? <Badge>{updateCount}</Badge> : null}
          </TabsTrigger>
          <TabsTrigger value="search">{t("tabs.search")}</TabsTrigger>
        </TabsList>

        <TabsContent value="installed" className="flex flex-col gap-3 pt-2">
          <Input
            aria-label={t("installed.filter")}
            placeholder={t("installed.filter")}
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="sm:max-w-xs"
          />
          {installed.error ? (
            <ListError error={installed.error} />
          ) : !installed.data ? (
            <Skeleton className="h-40 w-full" />
          ) : filtered.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {needle ? t("installed.noMatch") : t("installed.empty")}
            </p>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("table.package")}</TableHead>
                    <TableHead>{t("table.version")}</TableHead>
                    <TableHead className="hidden md:table-cell">
                      {t("table.description")}
                    </TableHead>
                    <TableHead className="w-0" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.slice(0, SHOWN).map((p) => {
                    const up = upgradeByName.get(p.name)
                    // winget shortens long ids in its table; a shortened id can't be
                    // passed back to it, so those rows can't be acted on here.
                    const shortened = p.name.endsWith("…")
                    return (
                      <TableRow key={`${p.source ?? ""}/${p.name}`}>
                        <TableCell className="max-w-56">
                          <PackageName name={p.name} title={p.title} />
                        </TableCell>
                        <TableCell className="font-mono text-xs">
                          {/* The badge wraps under the version on narrow screens,
                              so the row actions stay in view. */}
                          <div className="flex flex-wrap items-center gap-1">
                            <span
                              className="max-w-32 truncate"
                              title={p.version ?? undefined}
                            >
                              {p.version}
                            </span>
                            {up?.latest ? (
                              <Badge variant="outline">→ {up.latest}</Badge>
                            ) : null}
                          </div>
                        </TableCell>
                        <TableCell className="hidden max-w-md truncate text-muted-foreground md:table-cell">
                          {p.description}
                        </TableCell>
                        <TableCell>
                          <div className="flex justify-end gap-1">
                            {shortened ? null : (
                              <DetailsButton
                                name={p.name}
                                onOpen={() =>
                                  setDetails({
                                    name: p.name,
                                    source: p.source,
                                    upgradable: !!up,
                                  })
                                }
                              />
                            )}
                            {up && manager.can_upgrade_one && !shortened ? (
                              <Button
                                variant="ghost"
                                size="icon-sm"
                                aria-label={t("installed.upgradeLabel", { name: p.name })}
                                title={t("installed.upgrade")}
                                onClick={() => upgrade(p.name)}
                              >
                                <ArrowUpCircleIcon />
                              </Button>
                            ) : null}
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              aria-label={t("installed.uninstallLabel", { name: p.name })}
                              disabled={shortened}
                              title={
                                shortened
                                  ? t("installed.shortened", {
                                      manager: manager.label,
                                    })
                                  : t("installed.uninstall")
                              }
                              onClick={() =>
                                setPending({ kind: "uninstall", name: p.name })
                              }
                            >
                              <Trash2Icon />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
              {filtered.length > SHOWN ? (
                <p className="text-sm text-muted-foreground">
                  {t("installed.showing", { shown: SHOWN, total: filtered.length })}
                </p>
              ) : null}
            </>
          )}
        </TabsContent>

        <TabsContent value="updates" className="flex flex-col gap-3 pt-2">
          {updates.error ? (
            <ListError error={updates.error} />
          ) : !updates.data ? (
            <Skeleton className="h-24 w-full" />
          ) : updates.data.length === 0 ? (
            <Empty className="border py-8">
              <EmptyHeader>
                <EmptyTitle>{t("updates.upToDate")}</EmptyTitle>
                <EmptyDescription>
                  {manager.can_refresh
                    ? t("updates.upToDateRefresh")
                    : t("updates.nothing")}
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("table.package")}</TableHead>
                  <TableHead>{t("updates.installedColumn")}</TableHead>
                  <TableHead>{t("updates.availableColumn")}</TableHead>
                  <TableHead className="w-0" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {updates.data.slice(0, SHOWN).map((u) => (
                  <TableRow key={u.name}>
                    <TableCell className="max-w-56 truncate font-medium">
                      {u.name}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {u.version ?? "—"}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {u.latest ?? "—"}
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <DetailsButton
                          name={u.name}
                          onOpen={() =>
                            setDetails({ name: u.name, upgradable: true })
                          }
                        />
                        {manager.can_upgrade_one ? (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => upgrade(u.name)}
                          >
                            {t("installed.upgrade")}
                          </Button>
                        ) : null}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </TabsContent>

        <TabsContent value="search" className="flex flex-col gap-3 pt-2">
          <form
            className="flex gap-2 sm:max-w-md"
            onSubmit={(e) => {
              e.preventDefault()
              if (query.trim()) void runSearch(query.trim())
            }}
          >
            <Input
              aria-label={t("search.label", { manager: manager.label })}
              placeholder={t("search.label", { manager: manager.label })}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <Button type="submit" disabled={!query.trim() || searching}>
              <SearchIcon data-icon="inline-start" />
              {t("tabs.search")}
            </Button>
          </form>
          {searchError ? (
            <ListError error={searchError} />
          ) : searching ? (
            <Skeleton className="h-40 w-full" />
          ) : results === null ? null : results.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t("search.noMatch", { query: lastQuery })}
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("table.package")}</TableHead>
                  <TableHead>{t("table.version")}</TableHead>
                  <TableHead className="w-0" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {results.map((r) => (
                  <TableRow key={`${r.source ?? ""}/${r.name}`}>
                    <TableCell className="max-w-md min-w-48 whitespace-normal">
                      <PackageName
                        name={r.name}
                        title={r.title}
                        description={r.description}
                      />
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {/* Cask versions can be long build strings: cap the width so the
                          actions column stays in view. */}
                      <span
                        className="inline-block max-w-32 truncate align-middle"
                        title={r.version ?? undefined}
                      >
                        {r.version}
                      </span>
                      {sourceBadge(r.source) ? (
                        <Badge variant="outline" className="ml-2">
                          {sourceBadge(r.source)}
                        </Badge>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-1">
                        <DetailsButton
                          name={r.title ?? r.name}
                          onOpen={() =>
                            setDetails({ name: r.name, source: r.source })
                          }
                        />
                        {r.installed ? (
                          <Badge variant="secondary">
                            {t("tabs.installed")}
                          </Badge>
                        ) : (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => install(r)}
                          >
                            <DownloadIcon data-icon="inline-start" />
                            {t("search.install")}
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </TabsContent>
      </Tabs>

      <Confirm
        open={pending?.kind === "uninstall"}
        title={t("confirm.uninstallTitle", {
          name: pending?.kind === "uninstall" ? pending.name : "",
        })}
        description={t("confirm.uninstallDescription")}
        action={t("installed.uninstall")}
        destructive
        onCancel={() => setPending(null)}
        onConfirm={() => {
          if (pending?.kind === "uninstall") void uninstall(pending.name)
          setPending(null)
        }}
      />
      <Confirm
        open={pending?.kind === "upgrade-all"}
        title={t("confirm.upgradeAllTitle", { manager: manager.label })}
        description={t("confirm.upgradeAllDescription", { count: updateCount })}
        action={t("upgradeAll")}
        onCancel={() => setPending(null)}
        onConfirm={() => {
          void upgrade(null)
          setPending(null)
        }}
      />
      <PackageDetailsSheet
        manager={manager}
        target={details}
        onClose={() => setDetails(null)}
        onInstall={(name, source) => void install({ name, source })}
        onUninstall={(name) => setPending({ kind: "uninstall", name })}
        onUpgrade={(name) => void upgrade(name)}
      />
      {passwordDialog}
      <JobDialog job={job} onClose={() => setJob(null)} onFinished={afterJob} />
    </div>
  )
}
