"use client"

import * as React from "react"
import {
  BugIcon,
  ExternalLinkIcon,
  LightbulbIcon,
  MessageSquareIcon,
  SlidersHorizontalIcon,
  type LucideIcon,
} from "lucide-react"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemMedia,
  ItemTitle,
} from "@workspace/ui/components/item"
import {
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@workspace/ui/components/sidebar"
import { Skeleton } from "@workspace/ui/components/skeleton"

type Kind = Exclude<Schemas["IssueIn"]["kind"], "app">

const CHOICES: {
  kind: Kind
  title: string
  description: string
  icon: LucideIcon
}[] = [
  {
    kind: "bug",
    title: "Report a bug",
    description: "Something doesn't work the way it should.",
    icon: BugIcon,
  },
  {
    kind: "change",
    title: "Suggest a change",
    description: "Something works, but it should work differently.",
    icon: SlidersHorizontalIcon,
  },
  {
    kind: "feature",
    title: "Request a feature",
    description: "Something Athena can't do yet.",
    icon: LightbulbIcon,
  },
]

/** The "Send feedback" sidebar entry and its dialog. */
export function FeedbackMenuItem() {
  const [open, setOpen] = React.useState(false)
  const { setOpenMobile } = useSidebar()
  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        onClick={() => {
          setOpenMobile(false)
          setOpen(true)
        }}
      >
        <MessageSquareIcon />
        <span>Send feedback</span>
      </SidebarMenuButton>
      <FeedbackDialog open={open} onOpenChange={setOpen} />
    </SidebarMenuItem>
  )
}

export function FeedbackDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [info, setInfo] = React.useState<Schemas["FeedbackInfo"] | null>(null)
  const [urls, setUrls] = React.useState<Partial<Record<Kind, string>>>({})
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (!open) return
    let cancelled = false
    setError(null)
    api.GET("/api/feedback").then(({ data, error: err }) => {
      if (cancelled) return
      if (data) setInfo(data)
      else setError(errorMessage(err, "Couldn't load this server's details"))
    })
    // Links are built up front so each choice is a real link: a tab opened after an
    // await would be caught by popup blockers.
    for (const { kind } of CHOICES) {
      api
        .POST("/api/feedback/issue-url", {
          body: { kind, title: "", logs: "" },
        })
        .then(({ data }) => {
          if (!cancelled && data) setUrls((u) => ({ ...u, [kind]: data.url }))
        })
    }
    return () => {
      cancelled = true
    }
  }, [open])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Send feedback</DialogTitle>
          <DialogDescription>
            Opens a new issue on {repoName(info?.repo_url)} in a new tab. You
            can review and edit it there before it&apos;s posted; issues are
            public.
          </DialogDescription>
        </DialogHeader>

        <ItemGroup className="gap-2">
          {CHOICES.map(({ kind, title, description, icon: Icon }) => {
            const url = urls[kind]
            return (
              <Item
                key={kind}
                variant="outline"
                aria-disabled={!url}
                className={url ? undefined : "pointer-events-none opacity-60"}
                render={
                  url ? (
                    <a
                      href={url}
                      target="_blank"
                      rel="noreferrer"
                      onClick={() => onOpenChange(false)}
                    />
                  ) : (
                    <div />
                  )
                }
              >
                <ItemMedia variant="icon">
                  <Icon />
                </ItemMedia>
                <ItemContent>
                  <ItemTitle>{title}</ItemTitle>
                  <ItemDescription>{description}</ItemDescription>
                </ItemContent>
                <ItemActions>
                  <ExternalLinkIcon className="size-4 text-muted-foreground" />
                </ItemActions>
              </Item>
            )
          })}
        </ItemGroup>

        <p className="text-sm text-muted-foreground">
          A store app that doesn&apos;t work? Use{" "}
          <span className="font-medium text-foreground">Report a problem</span>{" "}
          on its store page, so the report reaches whoever maintains it.
        </p>

        <Diagnostics info={info} error={error} />
      </DialogContent>
    </Dialog>
  )
}

/** The server details a report includes, shown before anything is opened. */
export function Diagnostics({
  info,
  error,
}: {
  info: Schemas["FeedbackInfo"] | null
  error?: string | null
}) {
  if (error) return <p className="text-sm text-destructive">{error}</p>
  return (
    <section className="flex flex-col gap-2 rounded-lg bg-muted/50 p-3">
      <h3 className="text-xs font-medium text-muted-foreground">
        Filled in for you
      </h3>
      {info ? (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
          <dt className="text-muted-foreground">Athena</dt>
          <dd className="font-mono">{info.version}</dd>
          <dt className="text-muted-foreground">System</dt>
          <dd className="min-w-0 font-mono [overflow-wrap:anywhere]">
            {info.os_version}
          </dd>
          <dt className="text-muted-foreground">CPU</dt>
          <dd className="font-mono">{info.arch}</dd>
          <dt className="text-muted-foreground">Containers</dt>
          <dd className="min-w-0 font-mono [overflow-wrap:anywhere]">
            {info.runtime}
          </dd>
        </dl>
      ) : (
        <Skeleton className="h-16 w-full" />
      )}
    </section>
  )
}

export function repoName(url: string | undefined): string {
  if (!url) return "GitHub"
  try {
    const { hostname, pathname } = new URL(url)
    const path = pathname.split("/").filter(Boolean).slice(0, 2).join("/")
    return path ? `${path} (${hostname})` : hostname
  } catch {
    return url
  }
}
