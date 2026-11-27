"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useTranslation } from "react-i18next"
import {
  CpuIcon,
  LockIcon,
  PaletteIcon,
  ServerCogIcon,
  UserIcon,
  UsersIcon,
  type LucideIcon,
} from "lucide-react"

import { Button } from "@workspace/ui/components/button"

import { useAuth } from "@/components/auth-provider"

const SECTIONS: {
  key: "appearance" | "account" | "users" | "system" | "https" | "ai"
  url: string
  icon: LucideIcon
  adminOnly?: boolean
}[] = [
  { key: "appearance", url: "/settings/appearance/", icon: PaletteIcon },
  { key: "account", url: "/settings/account/", icon: UserIcon },
  { key: "users", url: "/settings/users/", icon: UsersIcon, adminOnly: true },
  {
    key: "system",
    url: "/settings/system/",
    icon: ServerCogIcon,
    adminOnly: true,
  },
  { key: "https", url: "/settings/https/", icon: LockIcon, adminOnly: true },
  { key: "ai", url: "/settings/ai/", icon: CpuIcon, adminOnly: true },
]

export default function SettingsLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const pathname = usePathname()
  const { t } = useTranslation("settings")
  const { user } = useAuth()
  return (
    // A row of tabs on small screens, a side menu from lg up.
    <div className="flex flex-col gap-4 md:gap-6 lg:flex-row lg:gap-10">
      <nav
        aria-label={t("sections.label")}
        className="flex flex-wrap gap-1 lg:sticky lg:top-20 lg:w-48 lg:shrink-0 lg:flex-col lg:self-start"
      >
        {SECTIONS.filter((s) => !s.adminOnly || user.is_admin).map((s) => {
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
              {t(`sections.${s.key}`)}
            </Button>
          )
        })}
      </nav>
      <div className="max-w-3xl min-w-0 flex-1">{children}</div>
    </div>
  )
}
