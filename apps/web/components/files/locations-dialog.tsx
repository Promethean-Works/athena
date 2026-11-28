"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"
import { PencilIcon, PlusIcon, Trash2Icon } from "lucide-react"

import { api, errorMessage } from "@workspace/api-client"
import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
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
  ItemGroup,
  ItemTitle,
} from "@workspace/ui/components/item"
import { Spinner } from "@workspace/ui/components/spinner"
import { Switch } from "@workspace/ui/components/switch"
import { toast } from "@workspace/ui/components/toast"

import type { Location } from "@/components/files/file-utils"

type Editing = {
  id: number | null
  name: string
  path: string
  usersCanOpen: boolean
}

function LocationForm({
  editing,
  onCancel,
  onSaved,
}: {
  editing: Editing
  onCancel: () => void
  onSaved: () => void
}) {
  const { t } = useTranslation("files")
  const [name, setName] = React.useState(editing.name)
  const [path, setPath] = React.useState(editing.path)
  const [usersCanOpen, setUsersCanOpen] = React.useState(editing.usersCanOpen)
  const [error, setError] = React.useState<string | null>(null)
  const [pending, setPending] = React.useState(false)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setPending(true)
    setError(null)
    const body = { name, path, users_can_open: usersCanOpen }
    const result =
      editing.id === null
        ? await api.POST("/api/files/locations", { body })
        : await api.PUT("/api/files/locations/{location_id}", {
            params: { path: { location_id: editing.id } },
            body,
          })
    setPending(false)
    if (result.data) onSaved()
    else setError(errorMessage(result.error))
  }

  return (
    <form onSubmit={submit} className="rounded-lg border p-4">
      <FieldGroup>
        <Field>
          <FieldLabel htmlFor="location-name">
            {t("locationsDialog.name")}
          </FieldLabel>
          <Input
            id="location-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("locationsDialog.namePlaceholder")}
            maxLength={64}
            required
          />
        </Field>
        <Field data-invalid={error ? true : undefined}>
          <FieldLabel htmlFor="location-path">
            {t("locationsDialog.folder")}
          </FieldLabel>
          <Input
            id="location-path"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder="/srv/media"
            className="font-mono"
            required
            aria-invalid={error ? true : undefined}
          />
          {error ? <FieldError>{error}</FieldError> : null}
        </Field>
        <Field orientation="horizontal">
          <Switch
            id="location-users"
            checked={usersCanOpen}
            onCheckedChange={setUsersCanOpen}
          />
          <FieldLabel htmlFor="location-users">
            {t("locationsDialog.usersCanOpen")}
          </FieldLabel>
        </Field>
        <FieldDescription>
          {t("locationsDialog.usersCanOpenHint")}
        </FieldDescription>
        <Field orientation="horizontal">
          <Button type="submit" disabled={pending}>
            {pending ? <Spinner data-icon="inline-start" /> : null}
            {editing.id === null
              ? t("locationsDialog.add")
              : t("locationsDialog.save")}
          </Button>
          <Button type="button" variant="outline" onClick={onCancel}>
            {t("locationsDialog.cancel")}
          </Button>
        </Field>
      </FieldGroup>
    </form>
  )
}

/** Add, change and remove the folders the file manager can reach. Admins only. */
export function LocationsDialog({
  open,
  locations,
  onOpenChange,
  onChanged,
}: {
  open: boolean
  locations: Location[]
  onOpenChange: (open: boolean) => void
  onChanged: () => void
}) {
  const { t } = useTranslation("files")
  const [editing, setEditing] = React.useState<Editing | null>(null)
  const [removing, setRemoving] = React.useState<number | null>(null)

  async function remove(loc: Location) {
    setRemoving(loc.id)
    const { error, response } = await api.DELETE(
      "/api/files/locations/{location_id}",
      { params: { path: { location_id: loc.id } } }
    )
    setRemoving(null)
    if (response.ok) {
      toast.add({
        type: "success",
        title: t("locationsDialog.removed", { name: loc.name }),
        description: t("locationsDialog.removedDescription"),
      })
      onChanged()
    } else {
      toast.add({
        type: "error",
        title: t("locationsDialog.removeFailed", { name: loc.name }),
        description: errorMessage(error),
      })
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) setEditing(null)
        onOpenChange(o)
      }}
    >
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t("locationsDialog.title")}</DialogTitle>
          <DialogDescription>
            {t("locationsDialog.description")}
          </DialogDescription>
        </DialogHeader>
        <ItemGroup className="max-h-80 gap-2 overflow-y-auto">
          {locations.map((loc) => (
            <Item key={loc.id} variant="outline" size="sm">
              <ItemContent className="min-w-0">
                <ItemTitle>
                  {loc.name}
                  {loc.owner_id !== null ? (
                    <Badge variant="outline">
                      {t("locationsDialog.personal")}
                    </Badge>
                  ) : loc.users_can_open ? (
                    <Badge variant="secondary">
                      {t("locationsDialog.openToUsers")}
                    </Badge>
                  ) : null}
                  {!loc.available ? (
                    <Badge variant="destructive">
                      {t("locationsDialog.missing")}
                    </Badge>
                  ) : !loc.writable ? (
                    <Badge variant="secondary">
                      {t("locationsDialog.readOnly")}
                    </Badge>
                  ) : null}
                </ItemTitle>
                <ItemDescription className="truncate font-mono text-xs">
                  {loc.path}
                </ItemDescription>
              </ItemContent>
              {loc.owner_id !== null ? null : (
                <ItemActions>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t("locationsDialog.edit", { name: loc.name })}
                    onClick={() =>
                      setEditing({
                        id: loc.id,
                        name: loc.name,
                        path: loc.path,
                        usersCanOpen: loc.users_can_open ?? false,
                      })
                    }
                  >
                    <PencilIcon />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t("locationsDialog.remove", { name: loc.name })}
                    disabled={removing === loc.id}
                    onClick={() => remove(loc)}
                  >
                    {removing === loc.id ? <Spinner /> : <Trash2Icon />}
                  </Button>
                </ItemActions>
              )}
            </Item>
          ))}
        </ItemGroup>
        {editing ? (
          <LocationForm
            key={editing.id ?? "new"}
            editing={editing}
            onCancel={() => setEditing(null)}
            onSaved={() => {
              setEditing(null)
              onChanged()
            }}
          />
        ) : (
          <Button
            variant="outline"
            className="self-start"
            onClick={() =>
              setEditing({ id: null, name: "", path: "", usersCanOpen: false })
            }
          >
            <PlusIcon />
            {t("locationsDialog.add")}
          </Button>
        )}
      </DialogContent>
    </Dialog>
  )
}
