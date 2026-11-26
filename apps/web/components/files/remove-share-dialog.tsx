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
import {
  HostPasswordField,
  needsHostPassword,
} from "@/components/files/elevation"

/** Confirms removing a share, and asks for the computer's password when the host needs it.
 * `onConfirm` returns an error message to show here, or null when it worked. */
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
  onConfirm: (password: string) => Promise<string | null>
}) {
  const { t } = useTranslation("files")
  const [password, setPassword] = React.useState("")
  const [pending, setPending] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (open) {
      setPassword("")
      setError(null)
    }
  }, [open])

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (needsHostPassword(capability) && password === "") {
      setError(t("network.password.required"))
      return
    }
    setPending(true)
    setError(null)
    const failed = await onConfirm(password)
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
          <HostPasswordField
            id="remove-share-password"
            capability={capability}
            value={password}
            onChange={setPassword}
            disabled={pending}
          />
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
