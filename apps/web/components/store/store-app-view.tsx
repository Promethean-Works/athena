"use client"

/* eslint-disable @next/next/no-img-element */

import * as React from "react"
import Link from "next/link"
import {
  CheckIcon,
  ChevronDownIcon,
  ExternalLinkIcon,
  ImageOffIcon,
  InfoIcon,
  MaximizeIcon,
  XIcon,
} from "lucide-react"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import { CodeEditor } from "@workspace/ui/components/athena/code-editor"
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@workspace/ui/components/alert"
import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@workspace/ui/components/collapsible"
import {
  Field,
  FieldLabel,
} from "@workspace/ui/components/field"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@workspace/ui/components/empty"
import { Skeleton } from "@workspace/ui/components/skeleton"
import { cn } from "@workspace/ui/lib/utils"
import { AppIcon } from "@/components/store/app-icon"
import { InstallForm } from "@/components/store/install-form"
import { StoreCover } from "@/components/store/store-cover"
import { storeAppHref } from "@/components/store/store-browser"

type Detail = Schemas["StoreAppDetail"]
type StoreApp = Schemas["StoreApp"]
type Variant = Schemas["VariantDetail"]

export function StoreAppView({ catalog, id }: { catalog: string; id: string }) {
  const [app, setApp] = React.useState<Detail | null>(null)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    api
      .GET("/api/store/apps/{catalog}/{app_id}", {
        params: { path: { catalog, app_id: id } },
      })
      .then(({ data, error: err }) => {
        if (data) setApp(data)
        else setError(errorMessage(err, "Couldn't load this app"))
      })
  }, [catalog, id])

  if (error) {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyTitle>App not found</EmptyTitle>
          <EmptyDescription>{error}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }
  if (!app) return <Skeleton className="h-96 w-full" />

  const [selectedVariantSlug, setSelectedVariantSlug] = React.useState(
    app.variants[0]?.slug ?? ""
  )
  const selectedVariant =
    app.variants.find((v) => v.slug === selectedVariantSlug) ?? app.variants[0]!

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
      <div className="flex min-w-0 flex-col gap-6">
        <div className="flex items-start gap-4">
          <AppIcon title={app.title} icon={app.icon} className="size-16" />
          <div className="flex min-w-0 flex-col gap-1">
            <h2 className="text-2xl font-semibold">{app.title}</h2>
            {app.tagline ? (
              <p className="text-muted-foreground">{app.tagline}</p>
            ) : (
              <p className="text-muted-foreground">{app.description}</p>
            )}
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <Badge variant="outline">
                {app.category_label || app.category}
              </Badge>
              {app.tags.map((tag) => (
                <Badge key={tag} variant="secondary">
                  {tag}
                </Badge>
              ))}
              {app.homepage ? (
                <Button
                  variant="link"
                  size="sm"
                  className="h-auto px-0"
                  nativeButton={false}
                  render={
                    <a href={app.homepage} target="_blank" rel="noreferrer" />
                  }
                >
                  Website
                  <ExternalLinkIcon data-icon="inline-end" />
                </Button>
              ) : null}
            </div>
          </div>
        </div>

        <Screenshots title={app.title} images={app.screenshots} />

        {app.installed.length ? (
          <Alert>
            <InfoIcon />
            <AlertTitle>Already installed</AlertTitle>
            <AlertDescription>
              <span>
                As{" "}
                {app.installed.map((n, i) => (
                  <React.Fragment key={n}>
                    {i > 0 ? ", " : ""}
                    <Link
                      href={`/apps/view/?name=${encodeURIComponent(n)}`}
                      className="underline underline-offset-4"
                    >
                      {n}
                    </Link>
                  </React.Fragment>
                ))}
                . You can install another copy under a different name.
              </span>
            </AlertDescription>
          </Alert>
        ) : null}

        {app.notes ? (
          <Alert>
            <InfoIcon />
            <AlertTitle>Before you start</AlertTitle>
            <AlertDescription>{app.notes}</AlertDescription>
          </Alert>
        ) : null}

        {app.features.length ? (
          <section className="flex flex-col gap-2">
            <h3 className="font-heading text-sm font-medium">What you get</h3>
            <ul className="grid gap-2 sm:grid-cols-2">
              {app.features.map((feature) => (
                <li key={feature} className="flex gap-2 text-sm">
                  <CheckIcon className="mt-0.5 size-4 shrink-0 text-primary" />
                  <span>{feature}</span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {app.description && app.tagline ? (
          <p className="text-sm text-muted-foreground">{app.description}</p>
        ) : null}

        <section className="flex flex-col gap-2">
          <h3 className="font-heading text-sm font-medium">Details</h3>
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Category</dt>
            <dd>{app.category_label || app.category}</dd>
            {app.license ? (
              <>
                <dt className="text-muted-foreground">License</dt>
                <dd>{app.license}</dd>
              </>
            ) : null}
            {app.homepage ? (
              <>
                <dt className="text-muted-foreground">Website</dt>
                <dd className="truncate">
                  <a
                    href={app.homepage}
                    target="_blank"
                    rel="noreferrer"
                    className="underline underline-offset-4"
                  >
                    {app.homepage}
                  </a>
                </dd>
              </>
            ) : null}
            <dt className="text-muted-foreground">Images</dt>
            <dd className="font-mono text-xs break-all">
              {app.images.join(", ")}
            </dd>
            <dt className="text-muted-foreground">Platforms</dt>
            <dd className="font-mono text-xs">{app.platforms.join(", ")}</dd>
          </dl>
        </section>

        <Collapsible>
          <CollapsibleTrigger
            render={
              <Button variant="outline" size="sm" className="group/compose" />
            }
          >
            View compose.yaml
            <ChevronDownIcon
              data-icon="inline-end"
              className="transition-transform group-data-panel-open/compose:rotate-180"
            />
          </CollapsibleTrigger>
          <CollapsibleContent className="pt-3">
            <CodeEditor
              value={selectedVariant.compose}
              readOnly
              aria-label={`${app.title} compose.yaml`}
              minHeight="10rem"
            />
          </CollapsibleContent>
        </Collapsible>

        <RelatedApps app={app} />
      </div>

      <Card className="h-fit xl:sticky xl:top-6">
        <CardHeader>
          <CardTitle>Install</CardTitle>
          <CardDescription>
            Your answers are saved in the app&apos;s .env file on the server,
            next to its compose.yaml.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {app.variants.length > 1 && (
            <Field className="pb-2">
              <FieldLabel>Variant</FieldLabel>
              <Select
                value={selectedVariantSlug}
                onValueChange={(value) =>
                  setSelectedVariantSlug(String(value ?? ""))
                }
              >
                <SelectTrigger />
                <SelectValue />
                <SelectContent>
                  <SelectGroup>
                    {app.variants.map((variant) => (
                      <SelectItem key={variant.slug} value={variant.slug}>
                        {variant.label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
          )}
          <InstallForm app={app} variant={selectedVariant} />
        </CardContent>
      </Card>
    </div>
  )
}

function ScreenshotImage({
  src,
  alt,
  className,
}: {
  src?: string
  alt: string
  className?: string
}) {
  const [failed, setFailed] = React.useState(false)

  React.useEffect(() => setFailed(false), [src])

  if (failed || !src) {
    return (
      <div
        role="img"
        aria-label={alt}
        className={cn(
          "flex items-center justify-center bg-muted text-muted-foreground",
          className
        )}
      >
        <ImageOffIcon className="size-6" />
      </div>
    )
  }

  return (
    <img
      src={src}
      alt={alt}
      loading="lazy"
      decoding="async"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
      className={className}
    />
  )
}

function Screenshots({ title, images }: { title: string; images: string[] }) {
  const [active, setActive] = React.useState(0)
  const [open, setOpen] = React.useState(false)

  if (images.length === 0) return null
  const current = images[Math.min(active, images.length - 1)]
  const alt = `${title} screenshot`

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="group relative overflow-hidden rounded-xl border focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
        aria-label={`Open a larger ${title} screenshot`}
      >
        <ScreenshotImage
          src={current}
          alt={alt}
          className="aspect-video w-full bg-muted object-cover object-top"
        />
        <span className="absolute right-2 bottom-2 flex items-center gap-1 rounded-md bg-background/80 px-2 py-1 text-xs text-foreground opacity-0 transition-opacity group-hover:opacity-100">
          <MaximizeIcon className="size-3" />
          Enlarge
        </span>
      </button>

      {images.length > 1 ? (
        <div className="flex gap-2">
          {images.map((image, index) => (
            <button
              key={image}
              type="button"
              onClick={() => setActive(index)}
              aria-label={`Show screenshot ${index + 1}`}
              aria-current={index === active}
              className={cn(
                "overflow-hidden rounded-lg border transition-opacity",
                index === active
                  ? "ring-1 ring-ring"
                  : "opacity-70 hover:opacity-100"
              )}
            >
              <ScreenshotImage
                src={image}
                alt=""
                className="aspect-video w-24 object-cover object-top"
              />
            </button>
          ))}
        </div>
      ) : null}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent showCloseButton={false} className="max-w-5xl sm:max-w-5xl">
          <DialogTitle className="sr-only">{title} screenshot</DialogTitle>
          <DialogDescription className="sr-only">
            A screenshot of {title}.
          </DialogDescription>
          <ScreenshotImage
            src={current}
            alt={alt}
            className="max-h-[80vh] w-full rounded-lg bg-muted object-contain"
          />
          <DialogClose
            render={
              <Button
                variant="secondary"
                size="icon-sm"
                className="absolute top-2 right-2 z-10 shadow-sm"
              />
            }
          >
            <XIcon />
            <span className="sr-only">Close</span>
          </DialogClose>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function RelatedApps({ app }: { app: Detail }) {
  const [apps, setApps] = React.useState<StoreApp[]>([])

  React.useEffect(() => {
    api
      .GET("/api/store/apps", {
        params: { query: { category: app.category } },
      })
      .then(({ data }) => {
        if (data) setApps(data)
      })
  }, [app.category])

  const related = apps
    .filter((a) => !(a.catalog === app.catalog && a.id === app.id))
    .slice(0, 4)

  if (related.length === 0) return null

  return (
    <section className="flex flex-col gap-3">
      <h3 className="font-heading text-sm font-medium">
        More in {app.category_label || app.category}
      </h3>
      <div className="grid gap-3 sm:grid-cols-2">
        {related.map((other) => (
          <Link
            key={`${other.catalog}/${other.id}`}
            href={storeAppHref(other)}
            className="group flex items-center gap-3 rounded-xl border p-3 transition-colors hover:border-primary/40 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
          >
            <StoreCover
              title={other.title}
              icon={other.icon}
              screenshot={other.cover}
              className="aspect-square w-14 shrink-0 rounded-lg"
            />
            <span className="flex min-w-0 flex-col">
              <span className="truncate text-sm font-medium">
                {other.title}
              </span>
              <span className="line-clamp-2 text-xs text-muted-foreground">
                {other.tagline ?? other.description}
              </span>
            </span>
          </Link>
        ))}
      </div>
    </section>
  )
}
