"use client"

import * as React from "react"
import { PlusIcon, Share2Icon, Trash2Icon } from "lucide-react"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@workspace/ui/components/alert"
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
import { Separator } from "@workspace/ui/components/separator"
import { Skeleton } from "@workspace/ui/components/skeleton"
import { Spinner } from "@workspace/ui/components/spinner"
import { Switch } from "@workspace/ui/components/switch"
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
import { ShareCapabilityNotice } from "@/components/files/share-capability-notice"

type NfsShare = Schemas["NfsShareOut"]
type Location = Schemas["LocationOut"]

/** Split what the admin typed ("10.0.0.0/24, nas.local") into a client list. */
function parseClients(text: string): string[] {
  return text.split(/[\s,]+/).filter(Boolean)
}

/** The NFS tab of /files/network: list the exports Athena made and create new ones. */
export function NfsSharesPanel() {
  const capability = useCapability("shares.nfs")
  const [shares, setShares] = React.useState<NfsShare[] | null>(null)
  const [locations, setLocations] = React.useState<Location[] | null>(null)
  const [dialogOpen, setDialogOpen] = React.useState(false)
  const [pending, setPending] = React.useState(false)

  const [locationId, setLocationId] = React.useState<number | null>(null)
  const [clients, setClients] = React.useState("")
  const [readOnly, setReadOnly] = React.useState(false)
  const [formError, setFormError] = React.useState<string | null>(null)

  const locationItems = React.useMemo(
    () => (locations ?? []).map((loc) => ({ value: loc.id, label: loc.name })),
    [locations]
  )

  const load = React.useCallback(async () => {
    const { data } = await api.GET("/api/shares/nfs")
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
      setFormError("Pick a folder to share")
      return
    }
    const list = parseClients(clients)
    if (list.length === 0) {
      setFormError("List at least one client that may mount it")
      return
    }
    if (
      list.some((c) => /\/0$/.test(c)) &&
      !window.confirm(
        "That network includes every address. Anyone who can reach this computer could mount the folder. Continue?"
      )
    )
      return
    setPending(true)
    const { data, error: err } = await api.POST("/api/shares/nfs", {
      body: { location: locationId, clients: list, read_only: readOnly },
    })
    setPending(false)
    if (!data) {
      setFormError(errorMessage(err))
      return
    }
    setDialogOpen(false)
    setClients("")
    setReadOnly(false)
    await load()
    toast.add({
      type: "success",
      title: "NFS share created",
      description: `${serverHost()}:${data.path}`,
    })
  }

  async function removeShare(id: number) {
    if (!window.confirm("Stop sharing this folder over NFS? The folder stays."))
      return
    const { error: err } = await api.DELETE("/api/shares/nfs/{share_id}", {
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
    toast.add({ type: "success", title: "NFS share removed" })
  }

  const ready = capability?.status === "ready"

  if (shares === null) {
    return <Skeleton className="h-40 w-full" />
  }

  return (
    <div className="flex flex-col gap-4">
      <ShareCapabilityNotice capability={capability} kind="NFS" />

      <div className="flex items-center justify-between">
        <Button
          onClick={() => setDialogOpen(true)}
          disabled={pending || !ready}
        >
          <PlusIcon className="mr-2 size-4 shrink-0" />
          Create share
        </Button>
      </div>

      {shares.length === 0 ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Share2Icon />
            </EmptyMedia>
            <EmptyTitle>No NFS shares</EmptyTitle>
            <EmptyDescription>
              Export a file location to Linux and macOS computers on your
              network.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Mount from</TableHead>
                <TableHead className="hidden md:table-cell">Location</TableHead>
                <TableHead className="hidden lg:table-cell">Clients</TableHead>
                <TableHead className="hidden sm:table-cell">
                  Read only
                </TableHead>
                <TableHead className="w-0">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {shares.map((share) => (
                <TableRow key={share.id}>
                  <TableCell className="max-w-0 min-w-40">
                    <ConnectionString
                      value={`${serverHost()}:${share.path}`}
                      label="NFS address"
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
                    {share.read_only ? "Yes" : "No"}
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="outline"
                      size="icon"
                      aria-label={`Remove NFS share ${share.location_name}`}
                      onClick={() => void removeShare(share.id)}
                      disabled={pending}
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
            <DialogTitle className="truncate">Create NFS share</DialogTitle>
            <DialogDescription>
              Let Linux and macOS computers mount a file location over the
              network.
            </DialogDescription>
          </DialogHeader>

          <Separator />

          <form id="new-nfs-share" onSubmit={createShare}>
            <FieldGroup>
              <Alert>
                <AlertTitle>NFS has no passwords</AlertTitle>
                <AlertDescription>
                  Access is decided by the computer's address, so list only
                  machines and networks you trust.
                </AlertDescription>
              </Alert>
              <Field>
                <FieldLabel htmlFor="nfs-share-location">
                  Folder to share
                </FieldLabel>
                <Select
                  items={locationItems}
                  value={locationId}
                  onValueChange={(v) => v !== null && setLocationId(v)}
                  disabled={pending || locations === null}
                >
                  <SelectTrigger id="nfs-share-location" className="w-full">
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
              </Field>
              <Field>
                <FieldLabel htmlFor="nfs-share-clients">
                  Who may mount
                </FieldLabel>
                <FieldDescription>
                  IP addresses, networks like 192.168.1.0/24, or host names,
                  separated by commas.
                </FieldDescription>
                <Input
                  id="nfs-share-clients"
                  value={clients}
                  onChange={(e) => setClients(e.target.value)}
                  placeholder="192.168.1.0/24"
                  disabled={pending}
                />
                {formError ? <FieldError>{formError}</FieldError> : null}
              </Field>
              <Field orientation="horizontal">
                <Switch
                  id="nfs-share-read-only"
                  checked={readOnly}
                  onCheckedChange={setReadOnly}
                  disabled={pending}
                />
                <FieldLabel htmlFor="nfs-share-read-only">Read only</FieldLabel>
              </Field>
            </FieldGroup>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setDialogOpen(false)}
                disabled={pending}
              >
                Cancel
              </Button>
              <Button type="submit" form="new-nfs-share" disabled={pending}>
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
