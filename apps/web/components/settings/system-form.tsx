"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@workspace/ui/components/field"
import { Skeleton } from "@workspace/ui/components/skeleton"
import { Switch } from "@workspace/ui/components/switch"
import { toast } from "@workspace/ui/components/toast"

import { useAuth } from "@/components/auth-provider"
import { patchSystemSettings } from "@/components/settings/system-settings"

type SystemSettings = Schemas["SystemSettings"]

/** Settings → System: host-wide switches that only admins change. */
export function SystemForm() {
  const { t } = useTranslation("settings")
  const { user } = useAuth()
  const [settings, setSettings] = React.useState<SystemSettings | null>(null)
  const [saving, setSaving] = React.useState(false)

  React.useEffect(() => {
    api
      .GET("/api/settings/system")
      .then(({ data }) => data && setSettings(data))
  }, [])

  // The remote access switch lives in its own card (TunnelCard); this card
  // holds the terminal and update check switches.
  async function update(next: SystemSettings, title: string) {
    const previous = settings
    setSettings(next)
    setSaving(true)
    const { data, error } = await patchSystemSettings({
      terminal_enabled: next.terminal_enabled,
      update_check: next.update_check,
    })
    setSaving(false)
    if (data) {
      setSettings(data)
      toast.add({
        type: "success",
        title,
      })
    } else {
      setSettings(previous)
      toast.add({
        type: "error",
        title: t("system.saveFailed"),
        description: errorMessage(error),
      })
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("system.title")}</CardTitle>
        <CardDescription>{t("system.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {settings === null ? (
          <Skeleton className="h-12 w-full" />
        ) : (
          <FieldGroup>
            <Field orientation="horizontal">
              <FieldContent>
                <FieldLabel htmlFor="terminal-enabled">
                  {t("system.terminal.label")}
                </FieldLabel>
                <FieldDescription>
                  {t("system.terminal.description")}
                  {!user.is_admin && ` ${t("system.adminOnly")}`}
                </FieldDescription>
              </FieldContent>
              <Switch
                id="terminal-enabled"
                checked={settings.terminal_enabled}
                disabled={saving || !user.is_admin}
                onCheckedChange={(checked) =>
                  update(
                    { ...settings, terminal_enabled: checked },
                    checked ? t("system.terminal.on") : t("system.terminal.off")
                  )
                }
              />
            </Field>
            <Field orientation="horizontal">
              <FieldContent>
                <FieldLabel htmlFor="update-check">
                  {t("system.updateCheck.label")}
                </FieldLabel>
                <FieldDescription>
                  {t("system.updateCheck.description")}
                  {!user.is_admin && ` ${t("system.adminOnly")}`}
                </FieldDescription>
              </FieldContent>
              <Switch
                id="update-check"
                checked={settings.update_check}
                disabled={saving || !user.is_admin}
                onCheckedChange={(checked) =>
                  update(
                    { ...settings, update_check: checked },
                    checked
                      ? t("system.updateCheck.on")
                      : t("system.updateCheck.off")
                  )
                }
              />
            </Field>
          </FieldGroup>
        )}
      </CardContent>
    </Card>
  )
}
