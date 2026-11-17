"use client"

import * as React from "react"
import Link from "next/link"

import Autoplay from "embla-carousel-autoplay"

import { Badge } from "@workspace/ui/components/badge"
import {
  CarouselApi,
  Carousel,
  CarouselContent,
  CarouselItem,
  CarouselNext,
  CarouselPrevious,
} from "@workspace/ui/components/carousel"
import { Skeleton } from "@workspace/ui/components/skeleton"
import { FlameIcon } from "lucide-react"

import { AppIcon } from "@/components/store/app-icon"
import { StoreCover } from "@/components/store/store-cover"
import { storeAppHref } from "@/components/store/store-browser"
import { type Schemas } from "@workspace/api-client"

type StoreApp = Schemas["StoreApp"]

type PopularCarouselProps = {
  popular: StoreApp[] | null
}

export function PopularCarousel({ popular }: PopularCarouselProps) {
  const [api, setApi] = React.useState<CarouselApi | null>(null)

  const plugins = React.useMemo(
    () => [
      Autoplay({
        delay: 3500,
        stopOnInteraction: false,
        stopOnMouseEnter: false,
      }),
    ],
    []
  )

  const opts = React.useMemo(() => ({ slidesToScroll: 3 }), [])

  // Re-init the carousel when the responsive breakpoint changes so the
  // responsive slide widths (1 on mobile, 2 on small, 3 on large) take effect.
  React.useEffect(() => {
    if (!api) return
    const media = window.matchMedia("(min-width: 1024px)")
    const onChange = () => void api.reInit()
    media.addEventListener("change", onChange)
    return () => media.removeEventListener("change", onChange)
  }, [api])

  if (!popular) {
    return (
      <section className="overflow-hidden rounded-2xl border bg-linear-to-br from-primary/10 via-card to-card px-4">
        <div className="flex flex-col gap-1 px-4 pt-4">
          <h2 className="flex items-center gap-2 font-heading text-base font-medium">
            <FlameIcon className="size-4 text-primary" />
            Popular right now
          </h2>
        </div>
        <div className="flex gap-3 overflow-x-auto px-5 py-5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="w-64 shrink-0 overflow-hidden rounded-xl border bg-card"
            >
              <Skeleton className="h-48 w-full" />
              <div className="flex flex-col gap-1 p-3">
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-3 w-full" />
              </div>
            </div>
          ))}
        </div>
      </section>
    )
  }

  return (
    <section className="overflow-hidden rounded-2xl border bg-linear-to-br from-primary/10 via-card to-card px-4">
      <div className="flex flex-col gap-1 px-4 pt-4 pb-4">
        <h2 className="flex items-center gap-2 font-heading text-base font-medium">
          <FlameIcon className="size-4 text-primary" />
          Popular right now
        </h2>
      </div>
      <Carousel
        setApi={setApi}
        opts={opts}
        plugins={plugins}
        className="px-4 pb-4"
      >
        <CarouselContent>
          {popular.map((app) => (
            <CarouselItem
              key={`${app.catalog}/${app.id}`}
              className="h-full sm:basis-[50%] lg:basis-[calc(100%/3)]"
            >
              <Link
                href={storeAppHref(app)}
                className="group block flex h-full flex-col"
              >
                <StoreCover
                  title={app.title}
                  icon={app.icon}
                  screenshot={app.cover}
                />
                <div className="flex flex-1 flex-col gap-1 p-4">
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
            </CarouselItem>
          ))}
        </CarouselContent>
        <CarouselPrevious className="-left-3" />
        <CarouselNext className="-right-3" />
      </Carousel>
    </section>
  )
}
