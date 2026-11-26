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
import { Separator } from "@workspace/ui/components/separator"
import { Spinner } from "@workspace/ui/components/spinner"
import { toast } from "@workspace/ui/components/toast"
import { useCapability } from "@/components/capabilities-provider"
import {
  ConnectionString,
  serverHost,
} from "@/components/files/connection-string"
import {
  canCreateShare,
  hostPasswordHeader,
} from "@/components/files/elevation"
import { RemoveShareDialog } from "@/components/files/remove-share-dialog"
import { SmbShareForm } from "@/components/files/smb-share-form"
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
  const [removing, setRemoving] = React.useState<SmbShare | null>(null)

  const load = React.useCallback(async () => {
    const { data } = await api.GET("/api/shares/smb")
    setShares(data ?? [])
    const { data: locs } = await api.GET("/api/files/locations")
    setLocations(locs ?? [])
  }, [])
  React.useEffect(() => {
    void load()
  }, [load])

  async function removeShare(password: string): Promise<string | null> {
    if (!removing) return null
    const { error: err } = await api.DELETE("/api/shares/smb/{share_id}", {
      params: {
        path: { share_id: removing.id },
        header: hostPasswordHeader(capability, password),
      },
    })
    if (err) return errorMessage(err)
    setRemoving(null)
    await load()
    toast.add({ type: "success", title: t("smb.removed") })
    return null
  }

  const ready = canCreateShare(capability)

  if (shares === null) {
    return <Skeleton className="h-40 w-full" />
  }

  return (
    <div className="flex flex-col gap-4">
      <ShareCapabilityNotice capability={capability} kind="SMB" />

      <div className="flex items-center justify-between">
        <Button onClick={() => setDialogOpen(true)} disabled={!ready}>
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
              {shares.map((share) => renderShareRow(share, setRemoving, t))}
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

          <SmbShareForm
            id="new-smb-share"
            locations={locations}
            onCreated={() => {
              setDialogOpen(false)
              void load()
            }}
            actions={({ pending }) => (
              <DialogFooter>
                <Button
                  type="button"
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
            )}
          />
        </DialogContent>
      </Dialog>

      <RemoveShareDialog
        open={removing !== null}
        description={t("smb.confirmRemove")}
        capability={capability}
        onClose={() => setRemoving(null)}
        onConfirm={removeShare}
      />
    </div>
  )
}

function renderShareRow(
  share: SmbShare,
  onRemove: (share: SmbShare) => void,
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
          onClick={() => onRemove(share)}
        >
          <Trash2Icon className="size-4" />
        </Button>
      </TableCell>
    </TableRow>
  )
}
