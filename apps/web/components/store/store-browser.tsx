"use client"

import * as React from "react"
import Link from "next/link"
import { useSearchParams } from "next/navigation"
import { LibraryIcon, SearchIcon } from "lucide-react"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import { PopularCarousel } from "@/components/store/popular-carousel"
import { StoreAppCard } from "@/components/store/store-app-card"
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@workspace/ui/components/empty"
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from "@workspace/ui/components/input-group"
import { Skeleton } from "@workspace/ui/components/skeleton"
import {
  ToggleGroup,
  ToggleGroupItem,
} from "@workspace/ui/components/toggle-group"

type StoreApp = Schemas["StoreApp"]
type Category = Schemas["Category"]

/** "Emulated" or "Won't run here" next to an app's title; nothing when it runs natively. */
export function SupportBadge({ support }: { support: StoreApp["support"] }) {
  if (support === "emulated") {
    return (
      <Badge
        variant="outline"
        title="No image for this CPU; Docker runs another one under emulation, which is slower"
      >
        Emulated
      </Badge>
    )
  }
  if (support === "unsupported") {
    return (
      <Badge variant="destructive" title="No image for this server's CPU">
        Won&apos;t run here
      </Badge>
    )
  }
  return null
}

export function storeAppHref(app: { catalog: string; id: string }) {
  return `/store/view/?catalog=${encodeURIComponent(app.catalog)}&id=${encodeURIComponent(app.id)}`
}

export function StoreBrowser() {
  // Deep links such as /store/?q=git open with the search already filled in.
  const initialQuery = useSearchParams().get("q") ?? ""
  const [apps, setApps] = React.useState<StoreApp[] | null>(null)
  const [categories, setCategories] = React.useState<Category[]>([])
  const [error, setError] = React.useState<string | null>(null)
  const [query, setQuery] = React.useState(initialQuery)
  const [category, setCategory] = React.useState<string>("all")
  // Apps with no image for this host's CPU are hidden until asked for.
  const [showUnsupported, setShowUnsupported] = React.useState(false)

  React.useEffect(() => {
    void Promise.all([
      api.GET("/api/store/apps"),
      api.GET("/api/store/categories"),
    ]).then(([appsRes, catsRes]) => {
      if (appsRes.data) setApps(appsRes.data)
      else setError(errorMessage(appsRes.error, "Couldn't load the store"))
      if (catsRes.data) setCategories(catsRes.data)
    })
  }, [])

  const runnable = React.useMemo(
    () =>
      (apps ?? []).filter(
        (a) => showUnsupported || a.support !== "unsupported"
      ),
    [apps, showUnsupported]
  )
  const unsupportedCount = React.useMemo(
    () => (apps ?? []).filter((a) => a.support === "unsupported").length,
    [apps]
  )

  const popular = React.useMemo(
    () => runnable.filter((a) => a.popular && a.support !== "unsupported"),
    [runnable]
  )

  const matches = React.useCallback(
    (a: StoreApp) => {
      const needle = query.trim().toLowerCase()
      return (
        (category === "all" || a.category === category) &&
        (!needle ||
          a.title.toLowerCase().includes(needle) ||
          a.description.toLowerCase().includes(needle) ||
          (a.tagline ?? "").toLowerCase().includes(needle) ||
          a.tags.some((t) => t.toLowerCase().includes(needle)))
      )
    },
    [query, category]
  )
  const shown = React.useMemo(
    () => runnable.filter(matches),
    [runnable, matches]
  )
  // Hidden apps that match the search, so "No apps match" can say they exist.
  const hiddenMatches = React.useMemo(
    () =>
      showUnsupported
        ? 0
        : (apps ?? []).filter((a) => a.support === "unsupported" && matches(a))
            .length,
    [apps, showUnsupported, matches]
  )

  if (error && !apps) {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyTitle>Couldn&apos;t load the store</EmptyTitle>
          <EmptyDescription>{error}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  const browsing = category !== "all" || query.trim() !== ""

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm text-muted-foreground">
            {apps
              ? browsing
                ? `${shown.length} of ${runnable.length} apps`
                : `${runnable.length} apps, each a compose project Athena sets up for you.`
              : "Browse apps to install."}
          </p>
          <div className="flex items-center gap-2 sm:ml-auto">
            <InputGroup className="w-full max-w-xs sm:w-64">
              <InputGroupAddon>
                <SearchIcon />
              </InputGroupAddon>
              <InputGroupInput
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search apps"
                aria-label="Search apps"
              />
            </InputGroup>
            <Button
              variant="outline"
              render={<Link href="/store/catalogs/" />}
              nativeButton={false}
            >
              <LibraryIcon data-icon="inline-start" />
              Catalogs
            </Button>
          </div>
        </div>
        {unsupportedCount ? (
          <p className="text-sm text-muted-foreground">
            {showUnsupported
              ? `Showing ${unsupportedCount} ${unsupportedCount === 1 ? "app" : "apps"} that can't run on this server's CPU.`
              : `${unsupportedCount} ${unsupportedCount === 1 ? "app is" : "apps are"} hidden because ${unsupportedCount === 1 ? "it has" : "they have"} no image for this server's CPU.`}{" "}
            <Button
              variant="link"
              size="sm"
              className="h-auto px-0"
              onClick={() => setShowUnsupported((v) => !v)}
            >
              {showUnsupported ? "Hide them" : "Show them"}
            </Button>
          </p>
        ) : null}
      </div>

      {!apps ? (
        <PopularCarousel popular={null} />
      ) : popular.length && !browsing ? (
        <PopularCarousel popular={popular} />
      ) : null}

      <ToggleGroup
        value={[category]}
        onValueChange={(value: string[]) => setCategory(value[0] ?? "all")}
        variant="outline"
        size="sm"
        spacing={2}
        className="flex-wrap"
      >
        <ToggleGroupItem value="all">All</ToggleGroupItem>
        {categories.map((c) => (
          <ToggleGroupItem key={c.id} value={c.id}>
            {c.label}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>

      {!apps ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="h-60 w-full" />
          ))}
        </div>
      ) : shown.length === 0 ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyTitle>No apps match</EmptyTitle>
            <EmptyDescription>
              {hiddenMatches
                ? `${hiddenMatches} matching ${hiddenMatches === 1 ? "app is" : "apps are"} hidden because ${hiddenMatches === 1 ? "it has" : "they have"} no image for this server's CPU.`
                : "Try another search or category."}
            </EmptyDescription>
          </EmptyHeader>
          {hiddenMatches ? (
            <EmptyContent>
              <Button
                variant="outline"
                onClick={() => setShowUnsupported(true)}
              >
                Show {hiddenMatches === 1 ? "it" : "them"}
              </Button>
            </EmptyContent>
          ) : null}
        </Empty>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {shown.map((app) => (
            <StoreAppCard key={`${app.catalog}/${app.id}`} app={app} />
          ))}
        </div>
      )}
    </div>
  )
}
