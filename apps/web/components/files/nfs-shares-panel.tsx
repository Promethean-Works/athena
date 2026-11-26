"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"
import { PlusIcon, Share2Icon, Trash2Icon } from "lucide-react"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import { Button } from "@workspace/ui/components/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@workspace/ui/components/empty"
import { Separator } from "@workspace/ui/components/separator"
import { Skeleton } from "@workspace/ui/components/skeleton"
import { Spinner } from "@workspace/ui/components/spinner"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@workspace/ui/components/table"
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
import { NfsShareForm } from "@/components/files/nfs-share-form"
import { RemoveShareDialog } from "@/components/files/remove-share-dialog"
import { ShareCapabilityNotice } from "@/components/files/share-capability-notice"

type NfsShare = Schemas["NfsShareOut"]
type Location = Schemas["LocationOut"]

/** The NFS tab of /files/network: list the exports Athena made and create new ones. */
export function NfsSharesPanel() {
  const { t } = useTranslation("files")
  const capability = useCapability("shares.nfs")
  const [shares, setShares] = React.useState<NfsShare[] | null>(null)
  const [locations, setLocations] = React.useState<Location[] | null>(null)
  const [dialogOpen, setDialogOpen] = React.useState(false)
  const [removing, setRemoving] = React.useState<NfsShare | null>(null)

  const load = React.useCallback(async () => {
    const { data } = await api.GET("/api/shares/nfs")
    setShares(data ?? [])
    const { data: locs } = await api.GET("/api/files/locations")
    setLocations(locs ?? [])
  }, [])
  React.useEffect(() => {
    void load()
  }, [load])

  async function removeShare(password: string): Promise<string | null> {
    if (!removing) return null
    const { error: err } = await api.DELETE("/api/shares/nfs/{share_id}", {
      params: {
        path: { share_id: removing.id },
        header: hostPasswordHeader(capability, password),
      },
    })
    if (err) return errorMessage(err)
    setRemoving(null)
    await load()
    toast.add({ type: "success", title: t("network.nfs.removed") })
    return null
  }

  const ready = canCreateShare(capability)

  if (shares === null) {
    return <Skeleton className="h-40 w-full" />
  }

  return (
    <div className="flex flex-col gap-4">
      <ShareCapabilityNotice capability={capability} kind="NFS" />

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
            <EmptyTitle>{t("network.nfs.emptyTitle")}</EmptyTitle>
            <EmptyDescription>
              {t("network.nfs.emptyDescription")}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("network.nfs.columnMountFrom")}</TableHead>
                <TableHead className="hidden md:table-cell">
                  {t("smb.columnLocation")}
                </TableHead>
                <TableHead className="hidden lg:table-cell">
                  {t("network.nfs.columnClients")}
                </TableHead>
                <TableHead className="hidden sm:table-cell">
                  {t("smb.columnReadOnly")}
                </TableHead>
                <TableHead className="w-0">
                  <span className="sr-only">{t("smb.columnActions")}</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {shares.map((share) => (
                <TableRow key={share.id}>
                  <TableCell className="max-w-0 min-w-40">
                    <ConnectionString
                      value={`${serverHost()}:${share.path}`}
                      label={t("network.nfs.address")}
                    />
                  </TableCell>
                  <TableCell className="hidden md:table-cell">
                    <div className="truncate">{share.location_name}</div>
                  </TableCell>
                  <TableCell className="hidden lg:table-cell">
                    <div className="truncate font-mono text-xs text-muted-foreground">
                      {share.clients.join(", ")}
                    </div>
                  </TableCell>
                  <TableCell className="hidden sm:table-cell">
                    {share.read_only ? t("smb.yes") : t("smb.no")}
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="outline"
                      size="icon"
                      aria-label={t("network.nfs.removeShare", {
                        name: share.location_name,
                      })}
                      onClick={() => setRemoving(share)}
                    >
                      <Trash2Icon className="size-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="truncate">
              {t("network.nfs.dialogTitle")}
            </DialogTitle>
            <DialogDescription>
              {t("network.nfs.dialogDescription")}
            </DialogDescription>
          </DialogHeader>

          <Separator />

          <NfsShareForm
            id="new-nfs-share"
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
                <Button type="submit" form="new-nfs-share" disabled={pending}>
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
        description={t("network.nfs.confirmRemove")}
        capability={capability}
        onClose={() => setRemoving(null)}
        onConfirm={removeShare}
      />
    </div>
  )
}
