"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@workspace/ui/components/field"
import { Input } from "@workspace/ui/components/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import { Switch } from "@workspace/ui/components/switch"
import { toast } from "@workspace/ui/components/toast"
import { useCapability } from "@/components/capabilities-provider"
import { serverHost } from "@/components/files/connection-string"
import {
  HostPasswordField,
  hostPasswordHeader,
  needsHostPassword,
} from "@/components/files/elevation"

type Location = Schemas["LocationOut"]

/** The form that publishes a file location over SMB. Used by the Network shares page and
 * by the file explorer's Share dialog (`fixedLocation` skips the folder picker).
 * `actions` renders the buttons inside the form. */
export function SmbShareForm({
  id,
  locations,
  fixedLocation,
  folder = "",
  defaultName,
  onCreated,
  actions,
}: {
  id: string
  locations: Location[] | null
  fixedLocation?: number
  /** A folder inside `fixedLocation` to share, instead of the whole location. */
  folder?: string
  defaultName?: string
  onCreated: () => void
  actions: (state: { pending: boolean }) => React.ReactNode
}) {
  const { t } = useTranslation("files")
  const capability = useCapability("shares.smb")
  const [pending, setPending] = React.useState(false)
  const [picked, setPicked] = React.useState<number | null>(null)
  const [name, setName] = React.useState(defaultName ?? "")
  const [readOnly, setReadOnly] = React.useState(false)
  const [guestOk, setGuestOk] = React.useState(false)
  const [password, setPassword] = React.useState("")
  const [formError, setFormError] = React.useState<string | null>(null)
  const locationId = fixedLocation ?? picked

  const locationItems = React.useMemo(
    () => (locations ?? []).map((loc) => ({ value: loc.id, label: loc.name })),
    [locations]
  )
  // Windows can't share to guests from here (the server refuses it).
  const canGuest = capability?.provider !== "smbshare"

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setFormError(null)
    if (locationId === null) {
      setFormError(t("network.pickFolder"))
      return
    }
    if (name.trim() === "") {
      setFormError(t("network.nameRequired"))
      return
    }
    if (needsHostPassword(capability) && password === "") {
      setFormError(t("network.password.required"))
      return
    }
    setPending(true)
    const { data, error: err } = await api.POST("/api/shares/smb", {
      body: {
        location: locationId,
        folder,
        name,
        read_only: readOnly,
        guest_ok: guestOk,
      },
      params: { header: hostPasswordHeader(capability, password) },
    })
    setPending(false)
    setPassword("")
    if (!data) {
      setFormError(errorMessage(err))
      return
    }
    setName(defaultName ?? "")
    setReadOnly(false)
    setGuestOk(false)
    toast.add({
      type: "success",
      title: t("smb.created"),
      description: `\\\\${serverHost()}\\${data.name}`,
    })
    onCreated()
  }

  return (
    <form id={id} onSubmit={submit} className="flex flex-col gap-4">
      <FieldGroup>
        {fixedLocation === undefined ? (
          <Field>
            <FieldLabel htmlFor={`${id}-location`}>
              {t("smb.folderToShare")}
            </FieldLabel>
            <FieldDescription>{t("smb.folderHint")}</FieldDescription>
            <Select
              items={locationItems}
              value={locationId}
              onValueChange={(v) => v !== null && setPicked(v)}
              disabled={pending || locations === null}
            >
              <SelectTrigger id={`${id}-location`} className="w-full">
                <SelectValue placeholder={t("smb.selectLocation")} />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {locationItems.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                      {item.label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </Field>
        ) : null}
        <Field>
          <FieldLabel htmlFor={`${id}-name`}>{t("smb.shareName")}</FieldLabel>
          <FieldDescription>{t("smb.shareNameHint")}</FieldDescription>
          <Input
            id={`${id}-name`}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("smb.shareNamePlaceholder")}
            maxLength={63}
            disabled={pending}
          />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field orientation="horizontal">
            <FieldContent>
              <FieldLabel htmlFor={`${id}-read-only`}>
                {t("smb.readOnly")}
              </FieldLabel>
              <FieldDescription>{t("smb.readOnlyHint")}</FieldDescription>
              <Switch
                id={`${id}-read-only`}
                checked={readOnly}
                onCheckedChange={setReadOnly}
                disabled={pending}
              />
            </FieldContent>
          </Field>
          {canGuest ? (
            <Field orientation="horizontal">
              <FieldContent>
                <FieldLabel htmlFor={`${id}-guest-ok`}>
                  {t("smb.guestOk")}
                </FieldLabel>
                <FieldDescription>{t("smb.guestOkHint")}</FieldDescription>
                <Switch
                  id={`${id}-guest-ok`}
                  checked={guestOk}
                  onCheckedChange={setGuestOk}
                  disabled={pending}
                />
              </FieldContent>
            </Field>
          ) : null}
        </div>
        <HostPasswordField
          id={`${id}-password`}
          capability={capability}
          value={password}
          onChange={setPassword}
          disabled={pending}
        />
        {formError ? <FieldError>{formError}</FieldError> : null}
      </FieldGroup>
      {actions({ pending })}
    </form>
  )
}
