"use client"

import { useTranslation } from "react-i18next"

import Link from "next/link"
import { PlusIcon } from "lucide-react"

import { Button } from "@workspace/ui/components/button"

import { useAuth } from "@/components/auth-provider"
import { AppsGrid } from "@/components/apps/apps-grid"
import { RequireContainers } from "@/components/containers/require-containers"

export default function AppsPage() {
  const { t } = useTranslation("apps")
  const { user } = useAuth()
  return (
    <RequireContainers>
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm text-muted-foreground">
            {t("page.description")}
          </p>
          {user.is_admin ? (
            <Button render={<Link href="/apps/new/" />} nativeButton={false}>
              <PlusIcon data-icon="inline-start" />
              {t("newApp")}
            </Button>
          ) : null}
        </div>
        <AppsGrid />
      </div>
    </RequireContainers>
  )
}
