"use client"

import Link from "next/link"
import { useTranslation } from "react-i18next"

import { Button } from "@workspace/ui/components/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"

import { useAuth } from "@/components/auth-provider"

/** Settings → Appearance: open the first-run setup again (admins only). */
export function RunSetupAgainCard() {
  const { t } = useTranslation("onboarding")
  const { user } = useAuth()
  if (!user.is_admin) return null
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("again.title")}</CardTitle>
        <CardDescription>{t("again.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <Button variant="outline" nativeButton={false} render={<Link href="/onboarding/" />}>
          {t("again.button")}
        </Button>
      </CardContent>
    </Card>
  )
}
