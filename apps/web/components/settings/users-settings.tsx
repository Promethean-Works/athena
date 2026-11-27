"use client"

import * as React from "react"

import { KeyRoundIcon, Trash2Icon, UserPlusIcon } from "lucide-react"
import { useTranslation } from "react-i18next"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@workspace/ui/components/alert-dialog"
import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
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
  ItemTitle,
} from "@workspace/ui/components/item"
import { Skeleton } from "@workspace/ui/components/skeleton"
import { Spinner } from "@workspace/ui/components/spinner"
import { Switch } from "@workspace/ui/components/switch"
import { toast } from "@workspace/ui/components/toast"

import { useAuth } from "@/components/auth-provider"
import { currentLocale } from "@/lib/i18n"

type Row = Schemas["UserRow"]

const MIN_LENGTH = 8

/** Settings → Users (admins only): add accounts, change roles, reset passwords, remove. */
export function UsersSettings() {
  const { t } = useTranslation("users")
  const { user: me } = useAuth()
  const [users, setUsers] = React.useState<Row[] | null>(null)
  const [loadError, setLoadError] = React.useState<string | null>(null)
  const [creating, setCreating] = React.useState(false)
  const [resetting, setResetting] = React.useState<Row | null>(null)
  const [removing, setRemoving] = React.useState<Row | null>(null)

  const load = React.useCallback(async () => {
    const { data, error } = await api.GET("/api/users")
    if (data) {
      setUsers(data)
      setLoadError(null)
    } else setLoadError(errorMessage(error, t("loadFailed")))
  }, [t])

  React.useEffect(() => {
    void load()
  }, [load])

  async function setRole(row: Row, isAdmin: boolean) {
    const { error } = await api.PATCH("/api/users/{user_id}", {
      params: { path: { user_id: row.id } },
      body: { is_admin: isAdmin },
    })
    if (error) {
      toast.add({
        type: "error",
        title: t("roleFailed"),
        description: errorMessage(error, ""),
      })
    }
    await load()
  }

  async function remove(row: Row) {
    const { error } = await api.DELETE("/api/users/{user_id}", {
      params: { path: { user_id: row.id } },
    })
    setRemoving(null)
    if (error) {
      toast.add({
        type: "error",
        title: t("removeFailed"),
        description: errorMessage(error, ""),
      })
    } else {
      toast.add({
        type: "success",
        title: t("removed", { name: row.username }),
      })
    }
    await load()
  }

  const admins = users?.filter((u) => u.is_admin).length ?? 0

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
        <CardAction>
          <Button onClick={() => setCreating(true)}>
            <UserPlusIcon data-icon="inline-start" />
            {t("add")}
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {loadError ? (
          <p className="text-sm text-destructive">{loadError}</p>
        ) : !users ? (
          <Skeleton className="h-16 w-full" />
        ) : (
          users.map((row) => {
            const isMe = row.id === me.id
            // The server refuses these too; the buttons just say so up front.
            const lastAdmin = row.is_admin && admins <= 1
            return (
              <Item key={row.id} variant="outline" className="flex-wrap">
                <ItemContent>
                  <ItemTitle>
                    {row.username}
                    <Badge variant="secondary">
                      {row.is_admin ? t("roleAdmin") : t("roleUser")}
                    </Badge>
                    {isMe ? <Badge variant="outline">{t("you")}</Badge> : null}
                  </ItemTitle>
                  <ItemDescription>
                    {t("created", {
                      date: new Date(row.created_at).toLocaleDateString(
                        currentLocale()
                      ),
                    })}
                  </ItemDescription>
                </ItemContent>
                <ItemActions className="flex-wrap">
                  <label className="flex items-center gap-2 text-sm">
                    <Switch
                      checked={row.is_admin}
                      disabled={lastAdmin}
                      onCheckedChange={(checked) => void setRole(row, checked)}
                      aria-label={t("adminSwitch", { name: row.username })}
                    />
                    {t("admin")}
                  </label>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setResetting(row)}
                  >
                    <KeyRoundIcon data-icon="inline-start" />
                    {t("resetPassword")}
                  </Button>
                  <Button
                    variant="outline"
                    size="icon-sm"
                    disabled={isMe || lastAdmin}
                    onClick={() => setRemoving(row)}
                  >
                    <Trash2Icon />
                    <span className="sr-only">
                      {t("remove", { name: row.username })}
                    </span>
                  </Button>
                </ItemActions>
              </Item>
            )
          })
        )}
      </CardContent>

      <CreateUserDialog
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={() => {
          setCreating(false)
          void load()
        }}
      />
      <ResetPasswordDialog
        user={resetting}
        onClose={() => setResetting(null)}
      />
      <AlertDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("removeTitle", { name: removing?.username })}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t("removeDescription")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => removing && void remove(removing)}
            >
              {t("removeConfirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}

function CreateUserDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: () => void
}) {
  const { t } = useTranslation("users")
  const [isAdmin, setIsAdmin] = React.useState(false)
  const [pending, setPending] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (open) {
      setIsAdmin(false)
      setError(null)
    }
  }, [open])

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setPending(true)
    setError(null)
    const { error: err } = await api.POST("/api/users", {
      body: {
        username: String(form.get("username") ?? "").trim(),
        password: String(form.get("password") ?? ""),
        is_admin: isAdmin,
      },
    })
    setPending(false)
    if (err) setError(errorMessage(err, t("createFailed")))
    else onCreated()
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("createTitle")}</DialogTitle>
          <DialogDescription>{t("createDescription")}</DialogDescription>
        </DialogHeader>
        <form id="create-user" onSubmit={submit}>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="new-username">{t("username")}</FieldLabel>
              <Input
                id="new-username"
                name="username"
                required
                minLength={3}
                maxLength={64}
                autoComplete="off"
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="new-user-password">
                {t("password")}
              </FieldLabel>
              <Input
                id="new-user-password"
                name="password"
                type="password"
                required
                minLength={MIN_LENGTH}
                autoComplete="new-password"
              />
              <FieldDescription>
                {t("passwordHint", { count: MIN_LENGTH })}
              </FieldDescription>
            </Field>
            <Field orientation="horizontal">
              <Switch
                id="new-user-admin"
                checked={isAdmin}
                onCheckedChange={setIsAdmin}
              />
              <FieldLabel htmlFor="new-user-admin">{t("makeAdmin")}</FieldLabel>
            </Field>
            {error ? <FieldError>{error}</FieldError> : null}
          </FieldGroup>
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={pending}>
            {t("cancel")}
          </Button>
          <Button type="submit" form="create-user" disabled={pending}>
            {pending ? <Spinner data-icon="inline-start" /> : null}
            {t("create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ResetPasswordDialog({
  user,
  onClose,
}: {
  user: Row | null
  onClose: () => void
}) {
  const { t } = useTranslation("users")
  const [pending, setPending] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (user) setError(null)
  }, [user])

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!user) return
    const form = new FormData(event.currentTarget)
    setPending(true)
    setError(null)
    const { error: err } = await api.PATCH("/api/users/{user_id}", {
      params: { path: { user_id: user.id } },
      body: { password: String(form.get("password") ?? "") },
    })
    setPending(false)
    if (err) {
      setError(errorMessage(err, t("resetFailed")))
      return
    }
    toast.add({
      type: "success",
      title: t("resetDone", { name: user.username }),
    })
    onClose()
  }

  return (
    <Dialog open={user !== null} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("resetTitle", { name: user?.username })}</DialogTitle>
          <DialogDescription>{t("resetDescription")}</DialogDescription>
        </DialogHeader>
        <form id="reset-user-password" onSubmit={submit}>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="reset-password">
                {t("newPassword")}
              </FieldLabel>
              <Input
                id="reset-password"
                name="password"
                type="password"
                required
                minLength={MIN_LENGTH}
                autoComplete="new-password"
              />
              <FieldDescription>
                {t("passwordHint", { count: MIN_LENGTH })}
              </FieldDescription>
            </Field>
            {error ? <FieldError>{error}</FieldError> : null}
          </FieldGroup>
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={pending}>
            {t("cancel")}
          </Button>
          <Button type="submit" form="reset-user-password" disabled={pending}>
            {pending ? <Spinner data-icon="inline-start" /> : null}
            {t("resetConfirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
