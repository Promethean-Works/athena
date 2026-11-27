"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"
import {
  ArrowUpCircleIcon,
  CircleAlertIcon,
  DownloadIcon,
  ExternalLinkIcon,
  Trash2Icon,
} from "lucide-react"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@workspace/ui/components/alert"
import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import { ScrollArea } from "@workspace/ui/components/scroll-area"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@workspace/ui/components/sheet"
import { Skeleton } from "@workspace/ui/components/skeleton"

import { PackageIcon } from "@/components/packages/package-icon"

type Manager = Schemas["ManagerOut"]
type Details = Schemas["PackageDetails"]

export type DetailsTarget = {
  name: string
  source?: string | null
  /** Upgrade available, from the Updates list. */
  upgradable?: boolean
}

type Load =
  | { status: "loading" }
  | { status: "ok"; data: Details }
  | { status: "error"; error: string }

function Row({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="grid grid-cols-[7rem_1fr] gap-2 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  )
}

/** Only web links are shown as links: a homepage field is text from a package. */
function safeUrl(url: string) {
  return /^https?:\/\//i.test(url) ? url : null
}

/**
 * What the manager knows about one package, like the details page in its own store:
 * icon (when the store has one), description, links, size, dependencies, and the
 * install, upgrade and uninstall actions.
 */
export function PackageDetailsSheet({
  manager,
  target,
  onClose,
  onInstall,
  onUninstall,
  onUpgrade,
}: {
  manager: Manager
  target: DetailsTarget | null
  onClose: () => void
  onInstall: (name: string, source: string | null) => void
  onUninstall: (name: string) => void
  onUpgrade: (name: string) => void
}) {
  const { t } = useTranslation("packages")
  const [state, setState] = React.useState<Load>({ status: "loading" })
  // Keep showing the last package while the sheet slides out.
  const [shown, setShown] = React.useState<DetailsTarget | null>(null)
  const key = target ? `${target.name}\u0000${target.source ?? ""}` : null

  React.useEffect(() => {
    if (!target) return
    let cancelled = false
    setShown(target)
    setState({ status: "loading" })
    void api
      .GET("/api/packages/{manager}/info", {
        params: {
          path: { manager: manager.id },
          query: { name: target.name, source: target.source ?? undefined },
        },
      })
      .then(({ data, error }) => {
        if (cancelled) return
        setState(
          data
            ? { status: "ok", data }
            : { status: "error", error: errorMessage(error) }
        )
      })
    return () => {
      cancelled = true
    }
    // `key` stands for the target's name and source.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, manager.id])

  const data = state.status === "ok" ? state.data : null
  const name = data?.name ?? shown?.name ?? ""
  const title = data?.title ?? name
  const homepage = data?.homepage ? safeUrl(data.homepage) : null

  return (
    <Sheet open={target !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="data-[side=right]:sm:max-w-md">
        <SheetHeader className="pr-12">
          <div className="flex items-center gap-3">
            <PackageIcon
              manager={manager.id}
              name={name}
              source={shown?.source}
              label={title}
              hasIcon={data?.has_icon ?? false}
            />
            <div className="flex min-w-0 flex-col">
              <SheetTitle className="truncate">{title}</SheetTitle>
              <SheetDescription className="truncate font-mono text-xs">
                {title !== name ? name : manager.label}
              </SheetDescription>
            </div>
          </div>
        </SheetHeader>

        <ScrollArea className="min-h-0 flex-1 px-4">
          {state.status === "loading" ? (
            <div className="flex flex-col gap-3">
              <Skeleton className="h-5 w-2/3" />
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-5 w-1/2" />
            </div>
          ) : state.status === "error" ? (
            <Alert variant="destructive">
              <CircleAlertIcon />
              <AlertTitle>{t("details.error")}</AlertTitle>
              <AlertDescription className="font-mono text-xs break-all">
                {state.error}
              </AlertDescription>
            </Alert>
          ) : (
            <div className="flex flex-col gap-4 pb-4">
              <div className="flex flex-wrap items-center gap-2">
                {state.data.installed ? (
                  <Badge variant="secondary">{t("tabs.installed")}</Badge>
                ) : null}
                {shown?.upgradable ? (
                  <Badge>{t("details.updateAvailable")}</Badge>
                ) : null}
              </div>
              {state.data.summary ? (
                <p className="font-medium">{state.data.summary}</p>
              ) : null}
              {state.data.description ? (
                <p className="text-sm whitespace-pre-line text-muted-foreground">
                  {state.data.description}
                </p>
              ) : null}
              <dl className="flex flex-col gap-2">
                {state.data.version ? (
                  <Row label={t("table.version")}>
                    <span className="font-mono text-xs">
                      {state.data.version}
                    </span>
                  </Row>
                ) : null}
                {state.data.installed && state.data.installed_version ? (
                  <Row label={t("details.installedVersion")}>
                    <span className="font-mono text-xs">
                      {state.data.installed_version}
                    </span>
                  </Row>
                ) : null}
                {state.data.homepage ? (
                  <Row label={t("details.homepage")}>
                    {homepage ? (
                      <a
                        href={homepage}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-primary underline-offset-4 hover:underline"
                      >
                        {homepage
                          .replace(/^https?:\/\//i, "")
                          .replace(/\/$/, "")}
                        <ExternalLinkIcon className="size-3" />
                      </a>
                    ) : (
                      state.data.homepage
                    )}
                  </Row>
                ) : null}
                {state.data.license ? (
                  <Row label={t("details.license")}>{state.data.license}</Row>
                ) : null}
                {state.data.maintainer ? (
                  <Row label={t("details.maintainer")}>
                    {state.data.maintainer}
                  </Row>
                ) : null}
                {state.data.source ? (
                  <Row label={t("details.source")}>{state.data.source}</Row>
                ) : null}
                {state.data.size ? (
                  <Row label={t("details.size")}>{state.data.size}</Row>
                ) : null}
                {(state.data.extra ?? []).map((f) => (
                  <Row key={f.label} label={f.label}>
                    <span className="whitespace-pre-line">{f.value}</span>
                  </Row>
                ))}
              </dl>
              {(state.data.dependencies ?? []).length ? (
                <div className="flex flex-col gap-2">
                  <h3 className="text-sm text-muted-foreground">
                    {t("details.dependencies")}
                  </h3>
                  <div className="flex flex-wrap gap-1">
                    {(state.data.dependencies ?? []).map((d) => (
                      <Badge key={d} variant="outline" className="font-mono">
                        {d}
                      </Badge>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          )}
        </ScrollArea>

        <SheetFooter className="flex-row flex-wrap justify-end">
          {data && data.installed ? (
            <>
              {shown?.upgradable && manager.can_upgrade_one ? (
                <Button
                  onClick={() => {
                    onUpgrade(data.name)
                    onClose()
                  }}
                >
                  <ArrowUpCircleIcon data-icon="inline-start" />
                  {t("installed.upgrade")}
                </Button>
              ) : null}
              <Button
                variant="outline"
                onClick={() => {
                  onUninstall(data.name)
                  onClose()
                }}
              >
                <Trash2Icon data-icon="inline-start" />
                {t("installed.uninstall")}
              </Button>
            </>
          ) : data ? (
            <Button
              onClick={() => {
                onInstall(data.name, shown?.source ?? null)
                onClose()
              }}
            >
              <DownloadIcon data-icon="inline-start" />
              {t("search.install")}
            </Button>
          ) : null}
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
