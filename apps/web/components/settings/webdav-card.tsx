"use client"

import * as React from "react"
import { KeyRoundIcon } from "lucide-react"
import { Trans, useTranslation } from "react-i18next"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@workspace/ui/components/alert"
import { Button } from "@workspace/ui/components/button"
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
import { useCapability } from "@/components/capabilities-provider"
import { CopyField } from "@/components/settings/copy-field"

type WebDav = Schemas["WebDavOut"]

/** Settings → System: the WebDAV network share at /dav/. */
export function WebDavCard() {
  const { t } = useTranslation("settings")
  const { user } = useAuth()
  const capability = useCapability("shares.webdav")
  const [config, setConfig] = React.useState<WebDav | null>(null)
  const [saving, setSaving] = React.useState(false)
  const [password, setPassword] = React.useState<string | null>(null)

  React.useEffect(() => {
    api.GET("/api/webdav").then(({ data }) => data && setConfig(data))
  }, [])

  if (!capability) return null

  async function toggle(enabled: boolean) {
    setSaving(true)
    const { data, error } = await api.PUT("/api/webdav", { body: { enabled } })
    setSaving(false)
    if (data) {
      setConfig(data)
      toast.add({
        type: "success",
        title: enabled ? t("webdav.on") : t("webdav.off"),
      })
    } else {
      toast.add({
        type: "error",
        title: t("webdav.saveFailed"),
        description: errorMessage(error),
      })
    }
  }

  async function generate() {
    setSaving(true)
    const { data, error } = await api.POST("/api/webdav/password")
    setSaving(false)
    if (data) {
      setPassword(data.password)
      setConfig((c) =>
        c ? { ...c, username: data.username, has_password: true } : c
      )
    } else {
      toast.add({
        type: "error",
        title: t("webdav.passwordFailed"),
        description: errorMessage(error),
      })
    }
  }

  const address =
    typeof window === "undefined"
      ? (config?.path ?? "/dav/")
      : `${window.location.origin}${config?.path ?? "/dav/"}`
  const plainHttp =
    typeof window !== "undefined" && window.location.protocol === "http:"

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("webdav.title")}</CardTitle>
        <CardDescription>{t("webdav.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {config === null ? (
          <Skeleton className="h-12 w-full" />
        ) : (
          <FieldGroup>
            <Field orientation="horizontal">
              <FieldContent>
                <FieldLabel htmlFor="webdav-enabled">
                  {t("webdav.label")}
                </FieldLabel>
                <FieldDescription>
                  {t("webdav.help")}
                  {!user.is_admin && ` ${t("webdav.adminOnly")}`}
                </FieldDescription>
              </FieldContent>
              <Switch
                id="webdav-enabled"
                checked={config.enabled}
                disabled={saving || !user.is_admin}
                onCheckedChange={(checked) => void toggle(checked)}
              />
            </Field>
            {config.enabled ? (
              <>
                <CopyField
                  id="webdav-address"
                  label={t("webdav.address")}
                  value={address}
                />
                {config.username ? (
                  <CopyField
                    id="webdav-username"
                    label={t("webdav.username")}
                    value={config.username}
                  />
                ) : null}
                {password ? (
                  <CopyField
                    id="webdav-password"
                    label={t("webdav.password")}
                    value={password}
                  />
                ) : null}
                <Field orientation="horizontal">
                  <FieldContent>
                    <FieldDescription>
                      {password
                        ? t("webdav.passwordHint.copyNow")
                        : config.has_password
                          ? t("webdav.passwordHint.set")
                          : t("webdav.passwordHint.none")}
                    </FieldDescription>
                  </FieldContent>
                  <Button
                    variant="outline"
                    disabled={saving || !user.is_admin}
                    onClick={() => void generate()}
                  >
                    <KeyRoundIcon />
                    {config.has_password
                      ? t("webdav.newPassword")
                      : t("webdav.makePassword")}
                  </Button>
                </Field>
                {plainHttp ? (
                  <Alert>
                    <AlertTitle>{t("webdav.plainHttp.title")}</AlertTitle>
                    <AlertDescription>
                      {t("webdav.plainHttp.description")}
                    </AlertDescription>
                  </Alert>
                ) : null}
                <div className="flex flex-col gap-1.5 text-sm text-muted-foreground">
                  <p>
                    <Trans
                      i18nKey="webdav.howto.macos"
                      ns="settings"
                      components={{
                        b: <span className="font-medium text-foreground" />,
                      }}
                    />
                  </p>
                  <p>
                    <Trans
                      i18nKey="webdav.howto.windows"
                      ns="settings"
                      components={{
                        b: <span className="font-medium text-foreground" />,
                        code: <code />,
                      }}
                    />
                  </p>
                  <p>
                    <Trans
                      i18nKey="webdav.howto.linux"
                      ns="settings"
                      values={{ url: address.replace(/^http/, "dav") }}
                      components={{
                        b: <span className="font-medium text-foreground" />,
                        code: <code />,
                      }}
                    />
                  </p>
                </div>
              </>
            ) : null}
          </FieldGroup>
        )}
      </CardContent>
    </Card>
  )
}
