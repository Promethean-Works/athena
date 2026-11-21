"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import {
  CpuIcon,
  LockIcon,
  PaletteIcon,
  ServerCogIcon,
  UserIcon,
  type LucideIcon,
} from "lucide-react"

import { Button } from "@workspace/ui/components/button"

const SECTIONS: { title: string; url: string; icon: LucideIcon }[] = [
  { title: "Appearance", url: "/settings/appearance/", icon: PaletteIcon },
  { title: "Account", url: "/settings/account/", icon: UserIcon },
  { title: "System", url: "/settings/system/", icon: ServerCogIcon },
  { title: "HTTPS", url: "/settings/https/", icon: LockIcon },
  { title: "AI", url: "/settings/ai/", icon: CpuIcon },
]

export default function SettingsLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const pathname = usePathname()
  return (
    // A row of tabs on small screens, a side menu from lg up.
    <div className="flex flex-col gap-4 md:gap-6 lg:flex-row lg:gap-10">
      <nav
        aria-label="Settings"
        className="flex flex-wrap gap-1 lg:sticky lg:top-20 lg:w-48 lg:shrink-0 lg:flex-col lg:self-start"
      >
        {SECTIONS.map((s) => {
          const active = pathname.startsWith(s.url.replace(/\/$/, ""))
          return (
            <Button
              key={s.url}
              variant={active ? "secondary" : "ghost"}
              size="sm"
              className="lg:justify-start"
              aria-current={active ? "page" : undefined}
              render={<Link href={s.url} />}
              nativeButton={false}
            >
              <s.icon data-icon="inline-start" />
              {s.title}
            </Button>
          )
        })}
      </nav>
      <div className="max-w-3xl min-w-0 flex-1">{children}</div>
    </div>
  )
}
