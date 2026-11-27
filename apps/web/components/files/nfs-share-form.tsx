"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@workspace/ui/components/alert"
import {
  Field,
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

/** Split what the admin typed ("10.0.0.0/24, nas.local") into a client list. */
function parseClients(text: string): string[] {
  return text.split(/[\s,]+/).filter(Boolean)
}

/** The form that exports a file location over NFS. Used by the Network shares page and by
 * the file explorer's Share dialog (`fixedLocation` skips the folder picker). */
export function NfsShareForm({
  id,
  locations,
  fixedLocation,
  folder = "",
  onCreated,
  actions,
}: {
  id: string
  locations: Location[] | null
  fixedLocation?: number
  /** A folder inside `fixedLocation` to share, instead of the whole location. */
  folder?: string
  onCreated: () => void
  actions: (state: { pending: boolean }) => React.ReactNode
}) {
  const { t } = useTranslation("files")
  const capability = useCapability("shares.nfs")
  const [pending, setPending] = React.useState(false)
  const [picked, setPicked] = React.useState<number | null>(null)
  const [clients, setClients] = React.useState("")
  const [readOnly, setReadOnly] = React.useState(false)
  const [password, setPassword] = React.useState("")
  const [formError, setFormError] = React.useState<string | null>(null)
  const locationId = fixedLocation ?? picked

  const locationItems = React.useMemo(
    () => (locations ?? []).map((loc) => ({ value: loc.id, label: loc.name })),
    [locations]
  )

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setFormError(null)
    if (locationId === null) {
      setFormError(t("network.pickFolder"))
      return
    }
    const list = parseClients(clients)
    if (list.length === 0) {
      setFormError(t("network.nfs.clientsRequired"))
      return
    }
    if (needsHostPassword(capability) && password === "") {
      setFormError(t("network.password.required"))
      return
    }
    if (
      list.some((c) => /\/0$/.test(c)) &&
      !window.confirm(t("network.nfs.confirmEverywhere"))
    )
      return
    setPending(true)
    const { data, error: err } = await api.POST("/api/shares/nfs", {
      body: {
        location: locationId,
        folder,
        clients: list,
        read_only: readOnly,
      },
      params: { header: hostPasswordHeader(capability, password) },
    })
    setPending(false)
    setPassword("")
    if (!data) {
      setFormError(errorMessage(err))
      return
    }
    setClients("")
    setReadOnly(false)
    toast.add({
      type: "success",
      title: t("network.nfs.created"),
      description: `${serverHost()}:${data.path}`,
    })
    onCreated()
  }

  return (
    <form id={id} onSubmit={submit} className="flex flex-col gap-4">
      <FieldGroup>
        <Alert>
          <AlertTitle>{t("network.nfs.noPasswordsTitle")}</AlertTitle>
          <AlertDescription>
            {t("network.nfs.noPasswordsDescription")}
          </AlertDescription>
        </Alert>
        {fixedLocation === undefined ? (
          <Field>
            <FieldLabel htmlFor={`${id}-location`}>
              {t("smb.folderToShare")}
            </FieldLabel>
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
          <FieldLabel htmlFor={`${id}-clients`}>
            {t("network.nfs.whoMayMount")}
          </FieldLabel>
          <FieldDescription>{t("network.nfs.clientsHint")}</FieldDescription>
          <Input
            id={`${id}-clients`}
            value={clients}
            onChange={(e) => setClients(e.target.value)}
            placeholder="192.168.1.0/24"
            disabled={pending}
          />
        </Field>
        <Field orientation="horizontal">
          <Switch
            id={`${id}-read-only`}
            checked={readOnly}
            onCheckedChange={setReadOnly}
            disabled={pending}
          />
          <FieldLabel htmlFor={`${id}-read-only`}>
            {t("smb.readOnly")}
          </FieldLabel>
        </Field>
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
