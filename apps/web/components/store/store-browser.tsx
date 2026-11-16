"use client"

import * as React from "react"
import Link from "next/link"
import { useSearchParams } from "next/navigation"
import { FlameIcon, LibraryIcon, SearchIcon } from "lucide-react"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
import {
  Empty,
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

import { AppIcon } from "@/components/store/app-icon"
import { StoreCover } from "@/components/store/store-cover"

type StoreApp = Schemas["StoreApp"]
type Category = Schemas["Category"]

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

  const popular = React.useMemo(
    () => (apps ?? []).filter((a) => a.popular),
    [apps]
  )

  const shown = React.useMemo(() => {
    const needle = query.trim().toLowerCase()
    return (apps ?? []).filter(
      (a) =>
        (category === "all" || a.category === category) &&
        (!needle ||
          a.title.toLowerCase().includes(needle) ||
          a.description.toLowerCase().includes(needle) ||
          (a.tagline ?? "").toLowerCase().includes(needle) ||
          a.tags.some((t) => t.toLowerCase().includes(needle)))
    )
  }, [apps, query, category])

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
                ? `${shown.length} of ${apps.length} apps`
                : `${apps.length} apps, each a compose project Athena sets up for you.`
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
      </div>

      {!apps ? (
        <Skeleton className="h-52 w-full rounded-2xl" />
      ) : popular.length && !browsing ? (
        <section className="overflow-hidden rounded-2xl border bg-linear-to-br from-primary/10 via-card to-card">
          <div className="flex flex-col gap-1 px-5 pt-5">
            <h2 className="flex items-center gap-2 font-heading text-base font-medium">
              <FlameIcon className="size-4 text-primary" />
              Popular right now
            </h2>
            <p className="text-sm text-muted-foreground">
              The apps most home servers start with.
            </p>
          </div>
          <div className="flex snap-x snap-mandatory gap-3 overflow-x-auto px-5 py-5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {popular.map((app) => (
              <Link
                key={`${app.catalog}/${app.id}`}
                href={storeAppHref(app)}
                className="group w-64 shrink-0 snap-start overflow-hidden rounded-xl border bg-card transition-colors hover:border-primary/40"
              >
                <StoreCover
                  title={app.title}
                  icon={app.icon}
                  screenshot={app.cover}
                />
                <div className="flex flex-col gap-1 p-3">
                  <span className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium">
                      {app.title}
                    </span>
                    {app.installed.length ? (
                      <Badge variant="secondary">Installed</Badge>
                    ) : null}
                  </span>
                  <span className="line-clamp-2 text-xs text-muted-foreground">
                    {app.tagline ?? app.description}
                  </span>
                </div>
              </Link>
            ))}
          </div>
        </section>
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
            <EmptyDescription>Try another search or category.</EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {shown.map((app) => (
            <Link
              key={`${app.catalog}/${app.id}`}
              href={storeAppHref(app)}
              className="group rounded-xl focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
            >
              <Card className="h-full gap-0 pt-0 transition-colors group-hover:border-primary/40 group-hover:shadow-sm">
                <StoreCover
                  title={app.title}
                  icon={app.icon}
                  screenshot={app.cover}
                />
                <CardHeader className="grid-cols-[auto_1fr] items-start gap-x-3 pt-4">
                  <AppIcon
                    title={app.title}
                    icon={app.icon}
                    className="row-span-2 size-9"
                  />
                  <CardTitle className="flex flex-wrap items-center gap-2">
                    {app.title}
                    {app.installed.length ? (
                      <Badge variant="secondary">Installed</Badge>
                    ) : null}
                  </CardTitle>
                  <CardDescription className="line-clamp-2">
                    {app.tagline ?? app.description}
                  </CardDescription>
                  <div className="col-start-2 flex flex-wrap gap-1 pt-1">
                    <Badge variant="outline">
                      {app.category_label || app.category}
                    </Badge>
                    {app.tags.slice(0, 2).map((tag) => (
                      <Badge key={tag} variant="secondary">
                        {tag}
                      </Badge>
                    ))}
                    {app.catalog !== "builtin" ? (
                      <Badge variant="outline">{app.catalog_name}</Badge>
                    ) : null}
                  </div>
                </CardHeader>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
