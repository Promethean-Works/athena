"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import { Trans, useTranslation } from "react-i18next"

import { api, errorMessage, setCsrfToken } from "@workspace/api-client"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"

import { CredentialsForm } from "@/components/credentials-form"

export default function LoginPage() {
  const router = useRouter()
  const { t } = useTranslation("auth")

  React.useEffect(() => {
    api.GET("/api/auth/status").then(({ data }) => {
      if (data?.setup_required) router.replace("/setup/")
      else if (data?.user) router.replace("/")
    })
  }, [router])

  return (
    <>
      <Card>
        <CardHeader className="text-center">
          <CardTitle className="text-xl">{t("login.title")}</CardTitle>
          <CardDescription>{t("login.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <CredentialsForm
            mode="login"
            submitLabel={t("login.submit")}
            onSubmit={async (credentials) => {
              const { data, error } = await api.POST("/api/auth/login", {
                body: credentials,
              })
              if (!data) return errorMessage(error, t("login.failed"))
              setCsrfToken(data.csrf_token ?? null)
              router.replace("/")
              return null
            }}
          />
        </CardContent>
      </Card>
      <p className="px-6 text-center text-sm text-balance text-muted-foreground">
        <Trans
          i18nKey="login.forgot"
          ns="auth"
          components={{ code: <code className="font-mono text-foreground" /> }}
        />
      </p>
    </>
  )
}
