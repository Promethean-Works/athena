"use client"

import * as React from "react"
import { Trans, useTranslation } from "react-i18next"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
import { FieldDescription, FieldGroup } from "@workspace/ui/components/field"
import { Skeleton } from "@workspace/ui/components/skeleton"

import { useAuth } from "@/components/auth-provider"
import { CopyField } from "@/components/settings/copy-field"

type SettingsFile = Schemas["SettingsFileOut"]

/** Settings → System: where the host-wide settings are saved, so an admin knows
 * which file to fix if a change keeps Athena from starting. Admins only. */
export function SettingsFileCard() {
  const { t } = useTranslation("settings")
  const { user } = useAuth()
  const [file, setFile] = React.useState<SettingsFile | null>(null)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (!user.is_admin) return
    api.GET("/api/settings/file").then(({ data, error }) => {
      if (data) setFile(data)
      else setError(errorMessage(error))
    })
  }, [user.is_admin])

  if (!user.is_admin) return null

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("settingsFile.title")}</CardTitle>
        <CardDescription>{t("settingsFile.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {error !== null ? (
          <FieldDescription className="text-destructive">
            {t("settingsFile.loadFailed", { error })}
          </FieldDescription>
        ) : file === null ? (
          <Skeleton className="h-16 w-full" />
        ) : (
          <FieldGroup>
            <CopyField
              id="settings-file-path"
              label={t("settingsFile.file")}
              value={file.path}
            />
            <FieldDescription>
              <Trans
                i18nKey="settingsFile.help"
                ns="settings"
                components={{ code: <code /> }}
              />
            </FieldDescription>
          </FieldGroup>
        )}
      </CardContent>
    </Card>
  )
}
