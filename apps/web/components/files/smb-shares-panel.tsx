"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"
import type { TFunction } from "i18next"
import { PlusIcon, Share2Icon, Trash2Icon } from "lucide-react"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import { Button } from "@workspace/ui/components/button"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@workspace/ui/components/empty"
import { Skeleton } from "@workspace/ui/components/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@workspace/ui/components/table"
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
import { Separator } from "@workspace/ui/components/separator"
import { Switch } from "@workspace/ui/components/switch"
import { Spinner } from "@workspace/ui/components/spinner"
import { toast } from "@workspace/ui/components/toast"
import { useCapability } from "@/components/capabilities-provider"
import {
  ConnectionString,
  serverHost,
} from "@/components/files/connection-string"
import { useHostPassword } from "@/components/host-password-provider"
import {
  canCreateShare,
  ElevationHint,
  passwordFor,
  hostPasswordHeader,
} from "@/components/files/elevation"
import { RemoveShareDialog } from "@/components/files/remove-share-dialog"
import { ShareCapabilityNotice } from "@/components/files/share-capability-notice"

type SmbShare = Schemas["SmbShareOut"]
type Location = Schemas["LocationOut"]

/** The SMB tab of /files/network: list the shares Athena published and create new ones. */
export function SmbSharesPanel() {
  const { t } = useTranslation("files")
  const capability = useCapability("shares.smb")
  const [shares, setShares] = React.useState<SmbShare[] | null>(null)
  const [locations, setLocations] = React.useState<Location[] | null>(null)
  const [dialogOpen, setDialogOpen] = React.useState(false)
  const [pending, setPending] = React.useState(false)

  // create form
  const [locationId, setLocationId] = React.useState<number | null>(null)
  const [name, setName] = React.useState("")
  const [readOnly, setReadOnly] = React.useState(false)
  const [guestOk, setGuestOk] = React.useState(false)
  const { ask, remember, forget } = useHostPassword()
  const [removeId, setRemoveId] = React.useState<number | null>(null)
  const [formError, setFormError] = React.useState<string | null>(null)

  const locationItems = React.useMemo(
    () => (locations ?? []).map((loc) => ({ value: loc.id, label: loc.name })),
    [locations]
  )

  const load = React.useCallback(async () => {
    const { data } = await api.GET("/api/shares/smb")
    setShares(data ?? [])
    const { data: locs } = await api.GET("/api/files/locations")
    setLocations(locs ?? [])
  }, [])
  React.useEffect(() => {
    void load()
  }, [load])

  async function createShare(event: React.FormEvent) {
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
    const password = await passwordFor(capability, ask, t("smb.createShare"))
    if (password === undefined) return
    setPending(true)
    const { data, error: err } = await api.POST("/api/shares/smb", {
      body: {
        location: locationId,
        folder: "",
        name,
        read_only: readOnly,
        guest_ok: guestOk,
      },
      params: { header: hostPasswordHeader(capability, password) },
    })
    setPending(false)
    if (!data) {
      forget()
      setFormError(errorMessage(err))
      return
    }
    if (password) remember(password)
    setDialogOpen(false)
    setName("")
    setReadOnly(false)
    setGuestOk(false)
    await load()
    toast.add({
      type: "success",
      title: t("smb.created"),
      description: `\\\\${serverHost()}\\${data.name}`,
    })
  }

  async function removeShare(): Promise<string | null> {
    if (removeId === null) return null
    const pw = await passwordFor(capability, ask, t("network.remove.title"))
    if (pw === undefined) return null
    const { error: err } = await api.DELETE("/api/shares/smb/{share_id}", {
      params: {
        path: { share_id: removeId },
        header: hostPasswordHeader(capability, pw),
      },
    })
    if (err) {
      forget()
      return errorMessage(err)
    }
    if (pw) remember(pw)
    setRemoveId(null)
    await load()
    toast.add({ type: "success", title: t("smb.removed") })
    return null
  }

  const ready = canCreateShare(capability)
  // Windows can't share to guests from here (the server refuses it).
  const canGuest = capability?.provider !== "smbshare"

  if (shares === null) {
    return <Skeleton className="h-40 w-full" />
  }

  return (
    <div className="flex flex-col gap-4">
      <ShareCapabilityNotice capability={capability} kind="SMB" />

      <div className="flex items-center justify-between">
        <Button
          onClick={() => setDialogOpen(true)}
          disabled={pending || !ready}
        >
          <PlusIcon className="mr-2 size-4 shrink-0" />
          {t("smb.createShare")}
        </Button>
      </div>

      {shares.length === 0 ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Share2Icon />
            </EmptyMedia>
            <EmptyTitle>{t("smb.emptyTitle")}</EmptyTitle>
            <EmptyDescription>{t("smb.emptyDescription")}</EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("smb.columnName")}</TableHead>
                <TableHead className="hidden md:table-cell">
                  {t("smb.columnLocation")}
                </TableHead>
                <TableHead className="hidden lg:table-cell">
                  {t("smb.columnPath")}
                </TableHead>
                <TableHead className="hidden sm:table-cell">
                  {t("smb.columnReadOnly")}
                </TableHead>
                <TableHead className="hidden sm:table-cell">
                  {t("smb.columnGuest")}
                </TableHead>
                <TableHead className="w-0">
                  <span className="sr-only">{t("smb.columnActions")}</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {shares.map((share) =>
                renderShareRow(share, pending, setRemoveId, t)
              )}
            </TableBody>
          </Table>
        </div>
      )}

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="truncate">
              {t("smb.dialogTitle")}
            </DialogTitle>
            <DialogDescription>{t("smb.dialogDescription")}</DialogDescription>
          </DialogHeader>

          <Separator />

          <form id="new-smb-share" onSubmit={createShare}>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="smb-share-location">
                  {t("smb.folderToShare")}
                </FieldLabel>
                <FieldDescription>{t("smb.folderHint")}</FieldDescription>
                <Select
                  items={locationItems}
                  value={locationId}
                  onValueChange={(v) => v !== null && setLocationId(v)}
                  disabled={pending || locations === null}
                >
                  <SelectTrigger id="smb-share-location" className="w-full">
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
                {formError ? <FieldError>{formError}</FieldError> : null}
              </Field>
              <Field>
                <FieldLabel htmlFor="smb-share-name">
                  {t("smb.shareName")}
                </FieldLabel>
                <FieldDescription>{t("smb.shareNameHint")}</FieldDescription>
                <Input
                  id="smb-share-name"
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
                    <FieldLabel htmlFor="smb-share-read-only">
                      {t("smb.readOnly")}
                    </FieldLabel>
                    <FieldDescription>{t("smb.readOnlyHint")}</FieldDescription>
                    <Switch
                      id="smb-share-read-only"
                      checked={readOnly}
                      onCheckedChange={setReadOnly}
                      disabled={pending}
                    />
                  </FieldContent>
                </Field>
                {canGuest ? (
                  <Field orientation="horizontal">
                    <FieldContent>
                      <FieldLabel htmlFor="smb-share-guest-ok">
                        {t("smb.guestOk")}
                      </FieldLabel>
                      <FieldDescription>
                        {t("smb.guestOkHint")}
                      </FieldDescription>
                      <Switch
                        id="smb-share-guest-ok"
                        checked={guestOk}
                        onCheckedChange={setGuestOk}
                        disabled={pending}
                      />
                    </FieldContent>
                  </Field>
                ) : null}
              </div>
              <ElevationHint capability={capability} />
            </FieldGroup>

            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setDialogOpen(false)}
                disabled={pending}
              >
                {t("smb.cancel")}
              </Button>
              <Button type="submit" form="new-smb-share" disabled={pending}>
                {pending ? <Spinner /> : null}
                {t("smb.createShare")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <RemoveShareDialog
        open={removeId !== null}
        description={t("smb.confirmRemove")}
        capability={capability}
        onClose={() => setRemoveId(null)}
        onConfirm={removeShare}
      />
    </div>
  )
}

function renderShareRow(
  share: SmbShare,
  pending: boolean,
  onRemove: (id: number) => void,
  t: TFunction<"files">
) {
  return (
    <TableRow key={share.id}>
      <TableCell className="max-w-0 min-w-40">
        <div className="truncate font-medium">{share.name}</div>
        <ConnectionString
          value={`\\\\${serverHost()}\\${share.name}`}
          label={t("network.smbAddress")}
        />
      </TableCell>
      <TableCell className="hidden md:table-cell">
        <div className="truncate">{share.location_name}</div>
      </TableCell>
      <TableCell className="hidden lg:table-cell">
        <div className="truncate font-mono text-xs text-muted-foreground">
          {share.path}
        </div>
      </TableCell>
      <TableCell className="hidden sm:table-cell">
        {share.read_only ? t("smb.yes") : t("smb.no")}
      </TableCell>
      <TableCell className="hidden sm:table-cell">
        {share.guest_ok ? t("smb.yes") : t("smb.no")}
      </TableCell>
      <TableCell>
        <Button
          variant="outline"
          size="icon"
          aria-label={t("smb.removeShare", { name: share.name })}
          onClick={() => void onRemove(share.id)}
          disabled={pending}
        >
          <Trash2Icon className="size-4" />
        </Button>
      </TableCell>
    </TableRow>
  )
}
