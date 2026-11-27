"use client"

/* eslint-disable @next/next/no-img-element */

import * as React from "react"
import Link from "next/link"
import { useTranslation } from "react-i18next"
import {
  CheckIcon,
  ChevronDownIcon,
  CpuIcon,
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
import { Field, FieldLabel } from "@workspace/ui/components/field"
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
import { AppReportButton } from "@/components/feedback/app-report-dialog"
import { AppIcon } from "@/components/store/app-icon"
import { InstallForm } from "@/components/store/install-form"
import { StoreCover } from "@/components/store/store-cover"
import { storeAppHref, SupportBadge } from "@/components/store/store-browser"
import i18n from "@/lib/i18n"

type Detail = Schemas["StoreAppDetail"]
type StoreApp = Schemas["StoreApp"]

export function StoreAppView({ catalog, id }: { catalog: string; id: string }) {
  const { t } = useTranslation("store")
  const [app, setApp] = React.useState<Detail | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [selectedVariantSlug, setSelectedVariantSlug] = React.useState("")

  React.useEffect(() => {
    api
      .GET("/api/store/apps/{catalog}/{app_id}", {
        params: { path: { catalog, app_id: id } },
      })
      .then(({ data, error: err }) => {
        if (data) setApp(data)
        else setError(errorMessage(err, i18n.t("store:view.loadError")))
      })
  }, [catalog, id])

  React.useEffect(() => {
    if (app) {
      setSelectedVariantSlug(app.variants[0]?.slug ?? "")
    }
  }, [app])

  if (error) {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyTitle>{t("view.notFound")}</EmptyTitle>
          <EmptyDescription>{error}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }
  if (!app) return <Skeleton className="h-96 w-full" />

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
              <SupportBadge support={app.support} />
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
                  {t("view.website")}
                  <ExternalLinkIcon data-icon="inline-end" />
                </Button>
              ) : null}
            </div>
          </div>
        </div>

        <Screenshots title={app.title} images={app.screenshots} />

        <CpuAlert app={app} />

        {app.installed.length ? (
          <Alert>
            <InfoIcon />
            <AlertTitle>{t("view.alreadyInstalled")}</AlertTitle>
            <AlertDescription>
              <span>
                {t("view.installedAs")}{" "}
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
                . {t("view.installAnother")}
              </span>
            </AlertDescription>
          </Alert>
        ) : null}

        {app.notes ? (
          <Alert>
            <InfoIcon />
            <AlertTitle>{t("view.beforeYouStart")}</AlertTitle>
            <AlertDescription>{app.notes}</AlertDescription>
          </Alert>
        ) : null}

        {app.features.length ? (
          <section className="flex flex-col gap-2">
            <h3 className="font-heading text-sm font-medium">
              {t("view.whatYouGet")}
            </h3>
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
          <h3 className="font-heading text-sm font-medium">
            {t("view.details")}
          </h3>
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
            <dt className="text-muted-foreground">{t("view.category")}</dt>
            <dd>{app.category_label || app.category}</dd>
            {app.license ? (
              <>
                <dt className="text-muted-foreground">{t("view.license")}</dt>
                <dd>{app.license}</dd>
              </>
            ) : null}
            {app.homepage ? (
              <>
                <dt className="text-muted-foreground">{t("view.website")}</dt>
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
            <dt className="text-muted-foreground">{t("view.images")}</dt>
            <dd className="font-mono text-xs break-all">
              {app.images.join(", ")}
            </dd>
            <dt className="text-muted-foreground">{t("view.platforms")}</dt>
            <dd className="font-mono text-xs">{app.platforms.join(", ")}</dd>
          </dl>
        </section>

        <Collapsible>
          <CollapsibleTrigger
            render={
              <Button variant="outline" size="sm" className="group/compose" />
            }
          >
            {t("view.viewCompose")}
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

        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <span>{t("view.reportPrompt")}</span>
          <AppReportButton app={app} />
        </div>

        <RelatedApps app={app} />
      </div>

      <Card className="h-fit xl:sticky xl:top-6">
        <CardHeader>
          <CardTitle>{t("view.install")}</CardTitle>
          {app.support !== "unsupported" ? (
            <CardDescription>{t("view.installHint")}</CardDescription>
          ) : null}
        </CardHeader>
        <CardContent>
          {app.variants.length > 1 && (
            <Field className="pb-2">
              <FieldLabel>{t("view.variant")}</FieldLabel>
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
          {app.support === "unsupported" ? (
            <p className="text-sm text-muted-foreground">
              {t("view.cannotInstall", {
                title: app.title,
                platform: app.host_platform ?? t("view.thisCpu"),
              })}
            </p>
          ) : (
            <InstallForm app={app} variant={selectedVariant} />
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function CpuAlert({ app }: { app: Detail }) {
  const { t } = useTranslation("store")
  const published = app.platforms.join(", ")
  const host = app.host_platform ?? t("view.thisServerCpu")
  if (app.support === "unsupported") {
    return (
      <Alert variant="destructive">
        <CpuIcon />
        <AlertTitle>{t("view.cpu.unsupportedTitle")}</AlertTitle>
        <AlertDescription>
          {t("view.cpu.unsupportedBody", { published, host })}
        </AlertDescription>
      </Alert>
    )
  }
  if (app.support === "emulated") {
    return (
      <Alert>
        <CpuIcon />
        <AlertTitle>{t("view.cpu.emulatedTitle")}</AlertTitle>
        <AlertDescription>
          {t("view.cpu.emulatedBody", { host, published })}
        </AlertDescription>
      </Alert>
    )
  }
  return null
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
  const { t } = useTranslation("store")
  const [active, setActive] = React.useState(0)
  const [open, setOpen] = React.useState(false)

  if (images.length === 0) return null
  const current = images[Math.min(active, images.length - 1)]
  const alt = t("view.screenshot.alt", { title })

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="group relative overflow-hidden rounded-xl border focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
        aria-label={t("view.screenshot.open", { title })}
      >
        <ScreenshotImage
          src={current}
          alt={alt}
          className="aspect-video w-full bg-muted object-cover object-top"
        />
        <span className="absolute right-2 bottom-2 flex items-center gap-1 rounded-md bg-background/80 px-2 py-1 text-xs text-foreground opacity-0 transition-opacity group-hover:opacity-100">
          <MaximizeIcon className="size-3" />
          {t("view.screenshot.enlarge")}
        </span>
      </button>

      {images.length > 1 ? (
        <div className="flex gap-2">
          {images.map((image, index) => (
            <button
              key={image}
              type="button"
              onClick={() => setActive(index)}
              aria-label={t("view.screenshot.show", { number: index + 1 })}
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
        <DialogContent
          showCloseButton={false}
          className="max-w-5xl sm:max-w-5xl"
        >
          <DialogTitle className="sr-only">{alt}</DialogTitle>
          <DialogDescription className="sr-only">
            {t("view.screenshot.description", { title })}
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
            <span className="sr-only">{t("view.screenshot.close")}</span>
          </DialogClose>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function RelatedApps({ app }: { app: Detail }) {
  const { t } = useTranslation("store")
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
    .filter(
      (a) =>
        !(a.catalog === app.catalog && a.id === app.id) &&
        a.support !== "unsupported"
    )
    .slice(0, 4)

  if (related.length === 0) return null

  return (
    <section className="flex flex-col gap-3">
      <h3 className="font-heading text-sm font-medium">
        {t("view.moreIn", { category: app.category_label || app.category })}
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
