"use client"

import * as React from "react"
import Link from "next/link"

import Autoplay from "embla-carousel-autoplay"

import { Badge } from "@workspace/ui/components/badge"
import { Button, buttonVariants } from "@workspace/ui/components/button"
import { Card } from "@workspace/ui/components/card"
import {
  type CarouselApi,
  Carousel,
  CarouselContent,
  CarouselItem,
  CarouselNext,
  CarouselPrevious,
} from "@workspace/ui/components/carousel"
import { Skeleton } from "@workspace/ui/components/skeleton"
import { cn } from "@workspace/ui/lib/utils"
import { CheckIcon } from "lucide-react"

import { AppIcon } from "@/components/store/app-icon"
import { StoreCover } from "@/components/store/store-cover"
import { storeAppHref } from "@/components/store/store-browser"
import { type Schemas } from "@workspace/api-client"

type StoreApp = Schemas["StoreApp"]

type PopularCarouselProps = {
  /** The popular apps, or null while the store is loading. */
  popular: StoreApp[] | null
}

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)"

function subscribeReducedMotion(onChange: () => void) {
  const media = window.matchMedia(REDUCED_MOTION)
  media.addEventListener("change", onChange)
  return () => media.removeEventListener("change", onChange)
}

/** True when the visitor asked for less motion. Assumed true until hydrated. */
function useReducedMotion() {
  return React.useSyncExternalStore(
    subscribeReducedMotion,
    () => window.matchMedia(REDUCED_MOTION).matches,
    () => true
  )
}

export function PopularCarousel({ popular }: PopularCarouselProps) {
  const headingId = React.useId()

  if (!popular) {
    return (
      <section aria-labelledby={headingId} className="flex flex-col gap-4">
        <CarouselHeader headingId={headingId} />
        <div
          className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
          aria-hidden="true"
        >
          {[0, 1, 2].map((i) => (
            <Card
              key={i}
              className={cn(
                "gap-0 pt-0",
                i === 1 && "hidden sm:flex",
                i === 2 && "hidden lg:flex"
              )}
            >
              <Skeleton className="aspect-video w-full rounded-none" />
              <div className="flex flex-col gap-4 px-4 pt-4">
                <div className="flex items-start gap-3">
                  <Skeleton className="size-10 rounded-lg" />
                  <div className="flex flex-1 flex-col gap-1">
                    <Skeleton className="h-5 w-1/2" />
                    <Skeleton className="h-10 w-full" />
                  </div>
                </div>
                <div className="flex items-center justify-between">
                  <Skeleton className="h-5 w-20 rounded-4xl" />
                  <Skeleton className="h-7 w-16" />
                </div>
              </div>
            </Card>
          ))}
        </div>
      </section>
    )
  }

  return <PopularCarouselLoaded popular={popular} headingId={headingId} />
}

function CarouselHeader({
  headingId,
  children,
}: {
  headingId: string
  children?: React.ReactNode
}) {
  return (
    <div className="flex items-end justify-between gap-4">
      <div className="flex min-w-0 flex-col gap-0.5">
        <h2 id={headingId} className="font-heading text-base font-medium">
          Popular right now
        </h2>
        <p className="text-sm text-muted-foreground">
          The apps most home servers start with.
        </p>
      </div>
      {children}
    </div>
  )
}

function PopularCarouselLoaded({
  popular,
  headingId,
}: {
  popular: StoreApp[]
  headingId: string
}) {
  const [api, setApi] = React.useState<CarouselApi | null>(null)
  const [snapCount, setSnapCount] = React.useState(0)
  const [selected, setSelected] = React.useState(0)
  // Hover and focus pause autoplay; any scroll the visitor makes (drag,
  // arrows, dots, arrow keys) stops it for good.
  const [hovered, setHovered] = React.useState(false)
  const [focused, setFocused] = React.useState(false)
  const [stopped, setStopped] = React.useState(false)
  const reducedMotion = useReducedMotion()

  // embla-carousel-autoplay's stopOnMouseEnter/stopOnFocusIn only resume when
  // stopOnInteraction is false, and then a drag doesn't stop it for good. So
  // pausing is done here with stop()/play(), and stopping drops the plugin.
  const plugins = React.useMemo(
    () =>
      reducedMotion || stopped
        ? []
        : [
            Autoplay({
              delay: 5000,
              stopOnInteraction: true,
              stopOnMouseEnter: false,
              stopOnFocusIn: false,
            }),
          ],
    [reducedMotion, stopped]
  )

  // "auto" scrolls by as many slides as fit, so the dots match the pages at
  // every width (1, 2 or 3 slides). Embla re-measures and re-inits on resize.
  const opts = React.useMemo(
    () => ({ align: "start" as const, slidesToScroll: "auto" as const }),
    []
  )

  React.useEffect(() => {
    if (!api) return
    const sync = () => {
      setSnapCount(api.scrollSnapList().length)
      setSelected(api.selectedScrollSnap())
    }
    const stop = () => setStopped(true)
    sync()
    api.on("select", sync)
    api.on("reInit", sync)
    api.on("pointerDown", stop)
    return () => {
      api.off("select", sync)
      api.off("reInit", sync)
      api.off("pointerDown", stop)
    }
  }, [api])

  const paused = hovered || focused
  React.useEffect(() => {
    const autoplay = api?.plugins().autoplay
    if (!autoplay) return
    if (paused) autoplay.stop()
    else autoplay.play()
  }, [api, plugins, paused])

  const multiPage = snapCount > 1

  return (
    <Carousel
      setApi={setApi}
      opts={opts}
      plugins={plugins}
      aria-labelledby={headingId}
      className="flex flex-col gap-4"
      onPointerEnter={() => setHovered(true)}
      onPointerLeave={() => setHovered(false)}
      onFocus={() => setFocused(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) {
          setFocused(false)
        }
      }}
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
          setStopped(true)
        }
      }}
      onClickCapture={(event) => {
        const target = event.target as HTMLElement
        if (
          target.closest(
            "[data-slot=carousel-previous],[data-slot=carousel-next]"
          )
        ) {
          setStopped(true)
        }
      }}
    >
      <CarouselHeader headingId={headingId}>
        {multiPage ? (
          <div className="flex shrink-0 items-center gap-2">
            <CarouselPrevious className="static inset-auto my-0" />
            <CarouselNext className="static inset-auto my-0" />
          </div>
        ) : null}
      </CarouselHeader>

      <CarouselContent>
        {popular.map((app) => (
          <CarouselItem
            key={`${app.catalog}/${app.id}`}
            className="sm:basis-1/2 lg:basis-1/3"
          >
            <PopularSlide app={app} />
          </CarouselItem>
        ))}
      </CarouselContent>

      {multiPage ? (
        <div className="flex justify-center gap-1">
          {Array.from({ length: snapCount }, (_, i) => (
            <Button
              key={i}
              variant="ghost"
              size="icon-xs"
              aria-label={`Show page ${i + 1} of ${snapCount}`}
              aria-current={i === selected ? "true" : undefined}
              onClick={() => {
                setStopped(true)
                api?.scrollTo(i)
              }}
            >
              <span
                className={cn(
                  "h-1.5 rounded-full transition-[width,background-color] motion-reduce:transition-none",
                  i === selected
                    ? "w-4 bg-primary"
                    : "w-1.5 bg-muted-foreground/40"
                )}
              />
            </Button>
          ))}
        </div>
      ) : null}
    </Carousel>
  )
}

/**
 * One app as a card. The whole card is a single link to the app's store page;
 * "Install" is styled like a button but is text inside that link, so no
 * interactive element is nested inside another.
 */
function PopularSlide({ app }: { app: StoreApp }) {
  const installed = app.installed.length > 0
  const label = app.category_label || app.category || app.tags[0]

  return (
    <Link
      href={storeAppHref(app)}
      className="group/slide block h-full rounded-xl outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
    >
      <Card className="h-full gap-0 pt-0 transition-shadow group-hover/slide:ring-primary/40">
        <StoreCover
          title={app.title}
          icon={app.icon}
          screenshot={app.cover}
          className="rounded-none"
        />
        <div className="flex flex-1 flex-col gap-4 px-4 pt-4">
          <div className="flex items-start gap-3">
            <AppIcon title={app.title} icon={app.icon} className="size-10" />
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <h3 className="truncate font-heading text-base leading-5 font-medium">
                {app.title}
              </h3>
              <p className="line-clamp-2 h-10 text-sm leading-5 text-muted-foreground">
                {app.tagline ?? app.description}
              </p>
            </div>
          </div>
          <div className="mt-auto flex items-center justify-between gap-2">
            {label ? (
              <Badge variant="outline" className="min-w-0 truncate">
                {label}
              </Badge>
            ) : (
              <span />
            )}
            {installed ? (
              <Badge variant="secondary">
                <CheckIcon data-icon="inline-start" />
                Installed
              </Badge>
            ) : (
              <span className={buttonVariants({ size: "sm" })}>Install</span>
            )}
          </div>
        </div>
      </Card>
    </Link>
  )
}
