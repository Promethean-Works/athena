"use client"

import { type ParseKeys } from "i18next"
import { useTranslation } from "react-i18next"
import {
  BoxIcon,
  ChevronDownIcon,
  CpuIcon,
  GlobeIcon,
  CloudIcon,
  FolderIcon,
  PackageIcon,
  RefreshCwIcon,
  Share2Icon,
  SquareTerminalIcon,
  ZapIcon,
  type LucideIcon,
} from "lucide-react"

import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@workspace/ui/components/collapsible"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemMedia,
  ItemTitle,
} from "@workspace/ui/components/item"
import { Skeleton } from "@workspace/ui/components/skeleton"
import { Spinner } from "@workspace/ui/components/spinner"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@workspace/ui/components/tooltip"

import {
  type Capability,
  useCapabilities,
} from "@/components/capabilities-provider"

const STATUS: Record<
  Capability["status"],
  { label: ParseKeys<"common">; variant: "secondary" | "outline" | "destructive" }
> = {
  ready: { label: "capabilities.status.ready", variant: "secondary" },
  stopped: { label: "capabilities.status.stopped", variant: "outline" },
  missing: { label: "capabilities.status.missing", variant: "outline" },
  unsupported: { label: "capabilities.status.unsupported", variant: "outline" },
  needs_privilege: { label: "capabilities.status.needs_privilege", variant: "destructive" },
}

function iconFor(id: string): LucideIcon {
  if (id === "containers") return BoxIcon
  if (id === "automation") return ZapIcon
  if (id === "files") return FolderIcon
  if (id.startsWith("packages.")) return PackageIcon
  if (id.startsWith("terminal.")) return SquareTerminalIcon
  if (id.startsWith("assistant.")) return SquareTerminalIcon
  if (id.startsWith("ai.")) return CpuIcon
  if (id.startsWith("cloud.")) return CloudIcon
  if (id.startsWith("shares.")) return Share2Icon
  if (id.startsWith("tunnel.")) return GlobeIcon
  return FolderIcon
}

/**
 * Package managers that aren't installed are left out entirely. The host only ever
 * shows what it has. Other capabilities stay visible when missing, because they can
 * be set up.
 */
function visible(c: Capability): boolean {
  return !(c.id.startsWith("packages.") && c.status === "missing")
}

const DOT: Record<Capability["status"], string> = {
  ready: "bg-primary",
  stopped: "bg-muted-foreground/50",
  missing: "border border-muted-foreground/60",
  unsupported: "border border-muted-foreground/30",
  needs_privilege: "bg-destructive",
}

function CapabilityList({ capabilities }: { capabilities: Capability[] }) {
  const { t } = useTranslation()
  return (
    <ItemGroup>
      {capabilities.map((c) => {
        const Icon = iconFor(c.id)
        const status = STATUS[c.status]
        return (
          <Item key={c.id} size="sm">
            <ItemMedia variant="icon">
              <Icon />
            </ItemMedia>
            <ItemContent>
              <ItemTitle>
                {c.label}
                {c.provider && c.provider !== "builtin" ? (
                  <span className="font-normal text-muted-foreground">
                    · {c.provider}
                  </span>
                ) : null}
              </ItemTitle>
              {c.detail ? <ItemDescription>{c.detail}</ItemDescription> : null}
            </ItemContent>
            <Badge variant={status.variant}>{t(status.label)}</Badge>
          </Item>
        )
      })}
    </ItemGroup>
  )
}

/**
 * What Athena found on the host: a compact grid of status chips (details in a
 * tooltip), with the full list one click away. The full list used to fill half
 * the dashboard.
 */
export function HostCapabilities() {
  const { t } = useTranslation()
  const { manifest, error, refreshing, refresh } = useCapabilities()
  const capabilities = manifest?.capabilities.filter(visible) ?? []
  const ready = capabilities.filter((c) => c.status === "ready").length

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("capabilities.title")}</CardTitle>
        <CardDescription>
          {manifest
            ? t("capabilities.summary", { ready, total: capabilities.length })
            : t("capabilities.loadingSummary")}
        </CardDescription>
        <CardAction>
          <Button
            variant="outline"
            size="sm"
            onClick={refresh}
            disabled={refreshing}
          >
            {refreshing ? (
              <Spinner data-icon="inline-start" />
            ) : (
              <RefreshCwIcon data-icon="inline-start" />
            )}
            {t("capabilities.redetect")}
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        {error && !manifest ? (
          <p className="text-sm text-muted-foreground">
            {t("capabilities.loadFailed", { error })}
          </p>
        ) : !manifest ? (
          <div className="grid grid-cols-2 gap-2">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : (
          <Collapsible className="flex flex-col gap-3">
            <ul className="grid grid-cols-1 gap-2 @sm/main:grid-cols-2 @3xl/main:grid-cols-3">
              {capabilities.map((c) => {
                const Icon = iconFor(c.id)
                const status = STATUS[c.status]
                return (
                  <li key={c.id}>
                    <Tooltip>
                      <TooltipTrigger
                        render={
                          <span
                            tabIndex={0}
                            className="flex h-9 items-center gap-2 rounded-lg border px-2.5 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                          />
                        }
                      >
                        <Icon className="size-4 shrink-0 text-muted-foreground" />
                        <span className="min-w-0 flex-1 truncate">{c.label}</span>
                        <span
                          className={`size-2 shrink-0 rounded-full ${DOT[c.status]}`}
                        />
                        <span className="sr-only">{t(status.label)}</span>
                      </TooltipTrigger>
                      <TooltipContent className="max-w-72">
                        {t(status.label)}
                        {c.provider && c.provider !== "builtin"
                          ? ` · ${c.provider}`
                          : ""}
                        {c.detail ? `. ${c.detail}` : ""}
                      </TooltipContent>
                    </Tooltip>
                  </li>
                )
              })}
            </ul>
            <CollapsibleTrigger
              render={
                <Button variant="ghost" size="sm" className="self-start" />
              }
            >
              <ChevronDownIcon
                data-icon="inline-start"
                className="transition-transform in-data-[panel-open]:rotate-180"
              />
              {t("capabilities.details")}
            </CollapsibleTrigger>
            <CollapsibleContent>
              <CapabilityList capabilities={capabilities} />
            </CollapsibleContent>
          </Collapsible>
        )}
      </CardContent>
    </Card>
  )
}
