"use client"

import * as React from "react"

import { LogOutIcon } from "lucide-react"
import { useTranslation } from "react-i18next"

import { api, errorMessage } from "@workspace/api-client"
import { Avatar, AvatarFallback } from "@workspace/ui/components/avatar"
import { Badge } from "@workspace/ui/components/badge"
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
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@workspace/ui/components/field"
import { Input } from "@workspace/ui/components/input"
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemMedia,
  ItemTitle,
} from "@workspace/ui/components/item"
import { Spinner } from "@workspace/ui/components/spinner"
import { toast } from "@workspace/ui/components/toast"

import { useAuth } from "@/components/auth-provider"

const MIN_LENGTH = 8

/** Settings → Account: who you are, and changing your password. */
export function AccountForm() {
  const { t } = useTranslation("settings")
  const { user, logout } = useAuth()
  const formRef = React.useRef<HTMLFormElement>(null)
  const [pending, setPending] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [mismatch, setMismatch] = React.useState(false)

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const current = String(form.get("current") ?? "")
    const next = String(form.get("new") ?? "")
    if (next !== String(form.get("confirm") ?? "")) {
      setMismatch(true)
      return
    }
    setMismatch(false)
    setError(null)
    setPending(true)
    const { error: err, response } = await api.POST("/api/auth/password", {
      body: { current_password: current, new_password: next },
    })
    setPending(false)
    if (response.ok) {
      formRef.current?.reset()
      toast.add({
        type: "success",
        title: t("account.toast.changed"),
        description: t("account.toast.changedDescription"),
      })
      return
    }
    setError(errorMessage(err, t("account.changeFailed")))
  }

  return (
    <div className="flex flex-col gap-4 md:gap-6">
      <Card>
        <CardContent>
          <Item className="p-0">
            <ItemMedia>
              <Avatar className="size-10">
                <AvatarFallback>
                  {user.username.slice(0, 2).toUpperCase()}
                </AvatarFallback>
              </Avatar>
            </ItemMedia>
            <ItemContent>
              <ItemTitle>
                {user.username}
                <Badge variant="secondary">
                  {user.is_admin ? t("account.admin") : t("account.user")}
                </Badge>
              </ItemTitle>
              <ItemDescription>{t("account.signedIn")}</ItemDescription>
            </ItemContent>
            <ItemActions>
              <Button variant="outline" onClick={() => void logout()}>
                <LogOutIcon data-icon="inline-start" />
                {t("account.signOut")}
              </Button>
            </ItemActions>
          </Item>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("account.password.title")}</CardTitle>
          <CardDescription>{t("account.password.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <form ref={formRef} onSubmit={submit} className="max-w-sm">
            {/* Lets password managers attach the new password to the right account. */}
            <input
              type="text"
              name="username"
              autoComplete="username"
              value={user.username}
              readOnly
              hidden
            />
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="current">
                  {t("account.password.current")}
                </FieldLabel>
                <Input
                  id="current"
                  name="current"
                  type="password"
                  autoComplete="current-password"
                  required
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="new">
                  {t("account.password.new")}
                </FieldLabel>
                <Input
                  id="new"
                  name="new"
                  type="password"
                  autoComplete="new-password"
                  minLength={MIN_LENGTH}
                  required
                />
                <FieldDescription>
                  {t("account.password.minLength", { count: MIN_LENGTH })}
                </FieldDescription>
              </Field>
              <Field data-invalid={mismatch || undefined}>
                <FieldLabel htmlFor="confirm">
                  {t("account.password.confirm")}
                </FieldLabel>
                <Input
                  id="confirm"
                  name="confirm"
                  type="password"
                  autoComplete="new-password"
                  aria-invalid={mismatch || undefined}
                  required
                />
                {mismatch ? (
                  <FieldError>{t("account.password.mismatch")}</FieldError>
                ) : null}
              </Field>
              {error ? (
                <Field data-invalid>
                  <FieldError>{error}</FieldError>
                </Field>
              ) : null}
              <Field orientation="horizontal">
                <Button type="submit" disabled={pending}>
                  {pending ? <Spinner data-icon="inline-start" /> : null}
                  {t("account.password.submit")}
                </Button>
              </Field>
            </FieldGroup>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
