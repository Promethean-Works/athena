"use client"

import * as React from "react"

import { Skeleton } from "@workspace/ui/components/skeleton"

import { RequireContainers } from "@/components/containers/require-containers"
import { StoreBrowser } from "@/components/store/store-browser"

export default function StorePage() {
  return (
    <RequireContainers>
      {/* StoreBrowser reads ?q= with useSearchParams, which needs a Suspense
          boundary in the static export. */}
      <React.Suspense fallback={<Skeleton className="h-64 w-full" />}>
        <StoreBrowser />
      </React.Suspense>
    </RequireContainers>
  )
}
