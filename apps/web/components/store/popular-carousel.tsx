"use client"

import * as React from "react"
import Autoplay from "embla-carousel-autoplay"
import { useTranslation } from "react-i18next"

import { Button } from "@workspace/ui/components/button"
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

import { StoreAppCard } from "@/components/store/store-app-card"
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
                <Skeleton className="h-5 w-20 rounded-4xl" />
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
  const { t } = useTranslation("store")
  return (
    <div className="flex items-end justify-between gap-4">
      <div className="flex min-w-0 flex-col gap-0.5">
        <h2 id={headingId} className="font-heading text-base font-medium">
          {t("popular.title")}
        </h2>
        <p className="text-sm text-muted-foreground">
          {t("popular.subtitle")}
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
  const { t } = useTranslation("store")
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

      {/* -ml-2 with pl-3/pr-1 on each slide keeps the 16px gap and leaves 4px
          inside the viewport's overflow-hidden for each card's focus ring
          and hover outline, which draw just outside the card. */}
      <CarouselContent className="-ml-2">
        {popular.map((app) => (
          <CarouselItem
            key={`${app.catalog}/${app.id}`}
            className="py-1 pr-1 pl-3 sm:basis-1/2 lg:basis-1/3"
          >
            <StoreAppCard app={app} />
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
              aria-label={t("popular.showPage", { page: i + 1, total: snapCount })}
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
