"use client"

import * as React from "react"
import { ArrowDownIcon, TriangleAlertIcon } from "lucide-react"
import { useTranslation } from "react-i18next"

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
import { FieldError } from "@workspace/ui/components/field"
import { Spinner } from "@workspace/ui/components/spinner"

import {
  isRemote,
  type Location,
  type Remote,
} from "@/components/files/file-utils"
import {
  type Folder,
  folderLabel,
  FolderPicker,
} from "@/components/files/folder-picker"

type Job = Schemas["JobOut"]
type Preview = Schemas["SyncPreview"]

function place(folder: Folder): Schemas["Place"] {
  return isRemote(folder.source)
    ? { remote: folder.source.remote, path: folder.path }
    : { location: folder.source.location, path: folder.path }
}

/**
 * Make one folder match another: pick both, preview what changes (and what gets
 * deleted), then run the sync as a job.
 */
export function SyncDialog({
  open,
  locations,
  remotes,
  onClose,
  onStarted,
}: {
  open: boolean
  locations: Location[]
  remotes: Remote[]
  onClose: () => void
  onStarted: (job: Job) => void
}) {
  const { t } = useTranslation("cloud")
  const [source, setSource] = React.useState<Folder>({
    source: { location: 0 },
    path: "",
  })
  const [dest, setDest] = React.useState<Folder>(source)
  const [preview, setPreview] = React.useState<Preview | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [pending, setPending] = React.useState(false)

  // Each time it opens: from the first location to the first remote. Done on open,
  // not on mount, because the lists load after the page does.
  const firstLocation = locations[0]?.id ?? 0
  const firstRemote = remotes[0]?.name
  React.useEffect(() => {
    if (!open) return
    setSource({ source: { location: firstLocation }, path: "" })
    setDest(
      firstRemote
        ? { source: { remote: firstRemote }, path: "" }
        : { source: { location: firstLocation }, path: "" }
    )
  }, [open, firstLocation, firstRemote])

  // A preview is only good for the folders it was made for.
  React.useEffect(() => {
    setPreview(null)
    setError(null)
  }, [open, source, dest])

  const body = { source: place(source), dest: place(dest) }

  async function check() {
    setPending(true)
    setError(null)
    const { data, error } = await api.POST("/api/cloud/sync/preview", {
      body,
    })
    setPending(false)
    if (data) setPreview(data)
    else setError(errorMessage(error))
  }

  async function run() {
    setPending(true)
    const { data, error } = await api.POST("/api/cloud/sync", { body })
    setPending(false)
    if (data) {
      onStarted(data)
      onClose()
    } else setError(errorMessage(error))
  }

  const destLabel = folderLabel(dest, locations, remotes)

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t("sync.title")}</DialogTitle>
          <DialogDescription>
            {t("sync.description")}
          </DialogDescription>
        </DialogHeader>
        <FolderPicker
          id="sync-source"
          label={t("sync.from")}
          value={source}
          onChange={setSource}
          locations={locations}
          remotes={remotes}
        />
        <ArrowDownIcon className="mx-auto text-muted-foreground" />
        <FolderPicker
          id="sync-dest"
          label={t("sync.to")}
          value={dest}
          onChange={setDest}
          locations={locations}
          remotes={remotes}
        />
        {preview ? (
          preview.delete_count ? (
            <Alert variant="destructive">
              <TriangleAlertIcon />
              <AlertTitle>
                {t("sync.willDelete", {
                  count: preview.delete_count,
                  dest: destLabel,
                })}
              </AlertTitle>
              <AlertDescription>
                <ul className="max-h-32 overflow-y-auto font-mono text-xs">
                  {preview.deletes.map((p) => (
                    <li key={p} className="truncate">
                      {p}
                    </li>
                  ))}
                  {preview.delete_count > preview.deletes.length ? (
                    <li>
                      {t("sync.andMore", {
                        count: preview.delete_count - preview.deletes.length,
                      })}
                    </li>
                  ) : null}
                </ul>
                {t("sync.willCopy", { count: preview.copy_count })}
              </AlertDescription>
            </Alert>
          ) : (
            <Alert>
              <AlertTitle>{t("sync.nothingDeleted")}</AlertTitle>
              <AlertDescription>
                {preview.copy_count
                  ? t("sync.willCopyTo", {
                      count: preview.copy_count,
                      dest: destLabel,
                    })
                  : t("sync.alreadyMatch")}
              </AlertDescription>
            </Alert>
          )
        ) : null}
        {error ? <FieldError>{error}</FieldError> : null}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          {preview ? (
            <Button
              variant={preview.delete_count ? "destructive" : "default"}
              disabled={pending}
              onClick={() => void run()}
            >
              {pending ? <Spinner data-icon="inline-start" /> : null}
              {preview.delete_count
                ? t("sync.syncAndDelete", { count: preview.delete_count })
                : t("sync.sync")}
            </Button>
          ) : (
            <Button disabled={pending} onClick={() => void check()}>
              {pending ? <Spinner data-icon="inline-start" /> : null}
              {t("sync.check")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
