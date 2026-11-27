"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"

import type { Schemas } from "@workspace/api-client"
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
import { ElevationHint } from "@/components/files/elevation"

/** Confirms removing a share. `onConfirm` asks for the computer's password itself when the
 * host needs it, and returns an error message to show here, or null when it worked. */
export function RemoveShareDialog({
  open,
  description,
  capability,
  onClose,
  onConfirm,
}: {
  open: boolean
  description: string
  capability: Schemas["Capability"] | undefined
  onClose: () => void
  onConfirm: () => Promise<string | null>
}) {
  const { t } = useTranslation("files")
  const [pending, setPending] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (open) {
      setError(null)
    }
  }, [open])

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setPending(true)
    setError(null)
    const failed = await onConfirm()
    setPending(false)
    if (failed) setError(failed)
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("network.remove.title")}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <form
          id="remove-share"
          onSubmit={submit}
          className="flex flex-col gap-3"
        >
          <ElevationHint capability={capability} />
          {error ? <FieldError>{error}</FieldError> : null}
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={pending}>
            {t("smb.cancel")}
          </Button>
          <Button
            type="submit"
            form="remove-share"
            variant="destructive"
            disabled={pending}
          >
            {pending ? <Spinner /> : null}
            {t("network.remove.action")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
