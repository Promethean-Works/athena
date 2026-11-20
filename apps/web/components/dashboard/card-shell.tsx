"use client"

import * as React from "react"
import Link from "next/link"
import { type LucideIcon } from "lucide-react"

import { Button } from "@workspace/ui/components/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
import { Skeleton } from "@workspace/ui/components/skeleton"

/** The common frame of the smaller dashboard cards: icon, title, a link, and the body. */
export function DashboardCard({
  icon: Icon,
  title,
  description,
  href,
  linkLabel,
  children,
}: {
  icon: LucideIcon
  title: string
  description: string
  href?: string
  linkLabel?: string
  children: React.ReactNode
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Icon className="size-4 text-muted-foreground" />
          {title}
        </CardTitle>
        <CardDescription>{description}</CardDescription>
        {href ? (
          <CardAction>
            <Button
              variant="ghost"
              size="sm"
              nativeButton={false}
              render={<Link href={href} />}
            >
              {linkLabel ?? "Open"}
            </Button>
          </CardAction>
        ) : null}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}

export function RowsSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-2">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-9 w-full" />
      ))}
    </div>
  )
}

/** A short muted line for "nothing here yet" inside a small card. */
export function Quiet({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
      {children}
    </p>
  )
}
