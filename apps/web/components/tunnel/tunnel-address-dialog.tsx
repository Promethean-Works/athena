"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"

import { api, type Schemas } from "@workspace/api-client"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import { Skeleton } from "@workspace/ui/components/skeleton"

import { CopyField } from "@/components/settings/copy-field"
import { TunnelQr } from "@/components/tunnel/tunnel-qr"

type TunnelStatus = Schemas["TunnelStatusResponse"]

/** The tunnel's public address as a link with a copy button and a QR code. */
export function TunnelAddressDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useTranslation("tunnel")
  const [status, setStatus] = React.useState<TunnelStatus | null>(null)

  React.useEffect(() => {
    if (!open) return
    setStatus(null)
    void api.GET("/api/tunnel/status").then(({ data }) => {
      if (data) setStatus(data)
    })
  }, [open])

  const url = status?.running ? status.public_url : null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{t("dialog.title")}</DialogTitle>
          <DialogDescription>{t("dialog.description")}</DialogDescription>
        </DialogHeader>
        {!status ? (
          <Skeleton className="h-48 w-full" />
        ) : url ? (
          <div className="flex flex-col items-center gap-4">
            <TunnelQr value={url} />
            <div className="w-full">
              <CopyField
                id="tunnel-dialog-url"
                label={t("dialog.publicAddress")}
                value={url}
              />
            </div>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            {status.detail ?? t("dialog.notRunning")} {t("dialog.startInSettings")}
          </p>
        )}
      </DialogContent>
    </Dialog>
  )
}
