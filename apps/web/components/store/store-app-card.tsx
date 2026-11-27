"use client"

import Link from "next/link"
import { useTranslation } from "react-i18next"
import { CheckIcon } from "lucide-react"

import { type Schemas } from "@workspace/api-client"
import { Badge } from "@workspace/ui/components/badge"
import { Card } from "@workspace/ui/components/card"
import { cn } from "@workspace/ui/lib/utils"

import { AppIcon } from "@/components/store/app-icon"
import { StoreCover } from "@/components/store/store-cover"
import { storeAppHref, SupportBadge } from "@/components/store/store-browser"

type StoreApp = Schemas["StoreApp"]

/**
 * One store app as a card, used by the "Popular right now" carousel and the
 * app grid. The whole card is a single link to the app's store page.
 */
export function StoreAppCard({ app }: { app: StoreApp }) {
  const { t } = useTranslation("store")
  const installed = app.installed.length > 0
  const label = app.category_label || app.category || app.tags[0]

  return (
    <Link
      href={storeAppHref(app)}
      className="group/card block h-full rounded-xl outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
    >
      <Card
        className={cn(
          "h-full gap-0 pt-0 transition-shadow group-hover/card:ring-primary/40",
          app.support === "unsupported" && "opacity-60"
        )}
      >
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
            <div className="flex min-w-0 items-center gap-1">
              {label ? (
                <Badge variant="outline" className="min-w-0 truncate">
                  {label}
                </Badge>
              ) : null}
              <SupportBadge support={app.support} />
            </div>
            {installed ? (
              <Badge variant="secondary">
                <CheckIcon data-icon="inline-start" />
                {t("card.installed")}
              </Badge>
            ) : null}
          </div>
        </div>
      </Card>
    </Link>
  )
}
