"use client"

import { usePathname } from "next/navigation"
import { ShieldIcon } from "lucide-react"
import { useTranslation } from "react-i18next"

import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@workspace/ui/components/empty"

import { useAuth } from "@/components/auth-provider"
import { isAdminPath } from "@/components/nav"

/** Shows a note instead of a page that only admins may open (the API refuses users too). */
export function AdminGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const { user } = useAuth()
  const { t } = useTranslation("nav")
  if (user.is_admin || !isAdminPath(pathname)) return <>{children}</>
  return (
    <Empty className="border">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <ShieldIcon />
        </EmptyMedia>
        <EmptyTitle>{t("adminOnly.title")}</EmptyTitle>
        <EmptyDescription>{t("adminOnly.description")}</EmptyDescription>
      </EmptyHeader>
    </Empty>
  )
}
