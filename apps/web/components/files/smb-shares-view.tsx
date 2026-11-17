"use client"

import * as React from "react"
import Link from "next/link"
import { ArrowLeftIcon, PlusIcon, Trash2Icon } from "lucide-react"

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

type SmbShare = Schemas["SmbShareOut"]
type Location = Schemas["LocationOut"]

/** /files/smb: list the SMB shares Athena published and create new ones. */
export function SmbSharesView() {
  const capability = useCapability("shares.smb")
  const [shares, setShares] = React.useState<SmbShare[] | null>(null)
  const [locations, setLocations] = React.useState<Location[] | null>(null)
  const [dialogOpen, setDialogOpen] = React.useState(false)
  const [pending, setPending] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  // create form
  const [locationId, setLocationId] = React.useState<number | null>(null)
  const [name, setName] = React.useState("")
  const [readOnly, setReadOnly] = React.useState(false)
  const [guestOk, setGuestOk] = React.useState(false)
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
    if (locationId === null) return
    setPending(true)
    const { data, error: err } = await api.POST("/api/shares/smb", {
      body: {
        location: locationId,
        name,
        read_only: readOnly,
        guest_ok: guestOk,
      },
    })
    setPending(false)
    if (!data) {
      setFormError(errorMessage(err))
      return
    }
    setDialogOpen(false)
    setName("")
    setReadOnly(false)
    setGuestOk(false)
    await load()
    toast.add({
      type: "success",
      title: "SMB share created",
      description: `\\\\server\\${data.name}`,
    })
  }

  async function removeShare(id: number) {
    if (
      !window.confirm("Remove this SMB share? The folder stays on the server.")
    )
      return
    const { error: err } = await api.DELETE("/api/shares/smb/{share_id}", {
      params: { path: { share_id: id } },
    })
    if (err) {
      toast.add({
        type: "error",
        title: "Couldn't remove",
        description: errorMessage(err),
      })
      return
    }
    await load()
    toast.add({ type: "success", title: "SMB share removed" })
  }

  const ready = capability?.status === "ready"

  if (shares === null) {
    return <Skeleton className="h-40 w-full" />
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="sm"
          render={<Link href="/files/" />}
          nativeButton={false}
        >
          <ArrowLeftIcon />
          Files
        </Button>
        <h2 className="font-heading text-lg font-medium">SMB shares</h2>
      </div>

      {!ready && (
        <div className="rounded-lg border p-4">
          {capability?.status === "unsupported" ? (
            <>
              <h3 className="font-medium">
                SMB shares aren't available on this computer
              </h3>
              <p className="text-sm text-muted-foreground">
                Creating SMB shares from Athena isn't wired on macOS or Windows
                yet. On Linux, install Samba (
                <code className="font-mono text-xs">apt install samba</code>)
                and Athena will offer it here.
              </p>
            </>
          ) : (
            <>
              <h3 className="font-medium">SMB shares aren't set up yet</h3>
              <p className="text-sm text-muted-foreground">
                Install the Samba server on this host, then shares can be
                published over the network as \\\\server\\share.
              </p>
            </>
          )}
        </div>
      )}

      <div className="flex items-center justify-between">
        <Button onClick={() => setDialogOpen(true)} disabled={pending}>
          <PlusIcon className="mr-2 size-4 shrink-0" />
          Create share
        </Button>
      </div>

      {shares.length === 0 ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Trash2Icon />
            </EmptyMedia>
            <EmptyTitle>No SMB shares</EmptyTitle>
            <EmptyDescription>
              Create a share to publish a file location over the network.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead className="hidden md:table-cell">Location</TableHead>
                <TableHead className="hidden lg:table-cell">
                  Path on server
                </TableHead>
                <TableHead className="hidden sm:table-cell">
                  Read only
                </TableHead>
                <TableHead className="hidden sm:table-cell">Guest ok</TableHead>
                <TableHead className="w-0">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {shares.map((share) =>
                renderShareRow(share, pending, removeShare)
              )}
            </TableBody>
          </Table>
        </div>
      )}

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="truncate">Create SMB share</DialogTitle>
            <DialogDescription>
              Publish a file location over the network so other computers can
              open it as a network drive.
            </DialogDescription>
          </DialogHeader>

          <Separator />

          <form id="new-smb-share" onSubmit={createShare}>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="smb-share-location">
                  Folder to share
                </FieldLabel>
                <FieldDescription>
                  Pick a file location. Its contents become the share.
                </FieldDescription>
                <Select
                  items={locationItems}
                  value={locationId}
                  onValueChange={(v) => v !== null && setLocationId(v)}
                  disabled={pending || locations === null}
                >
                  <SelectTrigger id="smb-share-location" className="w-full">
                    <SelectValue placeholder="Select a location" />
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
                <FieldLabel htmlFor="smb-share-name">Share name</FieldLabel>
                <FieldDescription>
                  The name on the network, e.g. "Media". Letters, digits, _. - ,
                  up to 63 chars and not starting with -.
                </FieldDescription>
                <Input
                  id="smb-share-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Media"
                  maxLength={63}
                  disabled={pending}
                />
              </Field>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field orientation="horizontal">
                  <FieldContent>
                    <FieldLabel htmlFor="smb-share-read-only">
                      Read only
                    </FieldLabel>
                    <FieldDescription>
                      Visitors can read but not add, change or delete files.
                    </FieldDescription>
                    <Switch
                      id="smb-share-read-only"
                      checked={readOnly}
                      onCheckedChange={setReadOnly}
                      disabled={pending}
                    />
                  </FieldContent>
                </Field>
                <Field orientation="horizontal">
                  <FieldContent>
                    <FieldLabel htmlFor="smb-share-guest-ok">
                      Guest ok
                    </FieldLabel>
                    <FieldDescription>
                      Anyone on the network can connect without a username or
                      password.
                    </FieldDescription>
                    <Switch
                      id="smb-share-guest-ok"
                      checked={guestOk}
                      onCheckedChange={setGuestOk}
                      disabled={pending}
                    />
                  </FieldContent>
                </Field>
              </div>
              {error ? <FieldError>{error}</FieldError> : null}
            </FieldGroup>

            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setDialogOpen(false)}
                disabled={pending}
              >
                Cancel
              </Button>
              <Button type="submit" form="new-smb-share" disabled={pending}>
                {pending ? <Spinner /> : null}
                Create share
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function renderShareRow(
  share: SmbShare,
  pending: boolean,
  onRemove: (id: number) => void
) {
  return (
    <TableRow key={share.id}>
      <TableCell className="max-w-0 min-w-40">
        <div className="truncate font-medium">{share.name}</div>
        <p className="truncate text-xs text-muted-foreground">
          \\\\server\\{share.name}
        </p>
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
        {share.read_only ? "Yes" : "No"}
      </TableCell>
      <TableCell className="hidden sm:table-cell">
        {share.guest_ok ? "Yes" : "No"}
      </TableCell>
      <TableCell>
        <Button
          variant="outline"
          size="icon"
          aria-label={`Remove SMB share ${share.name}`}
          onClick={() => void onRemove(share.id)}
          disabled={pending}
        >
          <Trash2Icon className="size-4" />
        </Button>
      </TableCell>
    </TableRow>
  )
}
