"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { Maximize2Icon, SparklesIcon } from "lucide-react"

import { Button } from "@workspace/ui/components/button"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@workspace/ui/components/sheet"

import { AssistantChat } from "@/components/assistant/assistant-view"
import { useAuth } from "@/components/auth-provider"

/**
 * The assistant in a side sheet from any page (docs/mvp-design.md §4.5, part C).
 * Admins only, like the API, and hidden on /assistant itself. The open chat lives
 * here, in the layout, so it survives closing the sheet and moving between pages; a
 * reply keeps running on the server while the sheet is closed.
 */
export function AssistantSheet() {
  const { user } = useAuth()
  const pathname = usePathname()
  const [open, setOpen] = React.useState(false)
  const [current, setCurrent] = React.useState<string | null>(null)

  // A link inside the sheet (Settings → AI, the full page) moves to another page.
  React.useEffect(() => setOpen(false), [pathname])

  if (!user.is_admin || pathname.startsWith("/assistant")) return null

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger
        render={<Button variant="ghost" size="sm" aria-label="Assistant" />}
      >
        <SparklesIcon />
        <span className="hidden sm:inline">Assistant</span>
      </SheetTrigger>
      <SheetContent
        side="right"
        className="gap-0 data-[side=right]:w-full data-[side=right]:sm:max-w-xl"
      >
        <SheetHeader className="flex-row items-center gap-2 pr-12">
          <div className="min-w-0 flex-1">
            <SheetTitle>Assistant</SheetTitle>
            <SheetDescription className="sr-only">
              Chat with the AI assistant about this server.
            </SheetDescription>
          </div>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Open the full page"
            title="Open the full page"
            nativeButton={false}
            render={
              <Link
                href={
                  current ? `/assistant/?c=${current}` : "/assistant/"
                }
              />
            }
          >
            <Maximize2Icon />
          </Button>
        </SheetHeader>
        <div className="flex min-h-0 flex-1 flex-col px-4 pb-4">
          <AssistantChat current={current} onOpen={setCurrent} compact />
        </div>
      </SheetContent>
    </Sheet>
  )
}
