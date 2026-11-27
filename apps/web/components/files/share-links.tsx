"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"
import {
  CopyIcon,
  DownloadIcon,
  LockIcon,
  Trash2Icon,
  UploadIcon,
} from "lucide-react"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@workspace/ui/components/alert-dialog"
import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import { toast } from "@workspace/ui/components/toast"

import { copyText } from "@/lib/clipboard"
import i18n, { currentLocale } from "@/lib/i18n"

export type ShareLink = Schemas["ShareOut"]

/** The full link, using the address this page was opened with. */
export function shareUrl(link: ShareLink): string {
  return `${window.location.origin}${link.url_path}`
}

export async function copyLink(link: ShareLink) {
  const ok = await copyText(shareUrl(link))
  toast.add(
    ok
      ? { type: "success", title: i18n.t("files:links.copied") }
      : { type: "error", title: i18n.t("files:links.copyFailed") }
  )
}

export function expiryText(link: ShareLink): string {
  if (link.expired) return i18n.t("files:links.expired")
  if (!link.expires_at) return i18n.t("files:links.neverExpires")
  const date = new Date(link.expires_at).toLocaleString(currentLocale(), {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
  return i18n.t("files:links.expires", { date })
}

/** Mode, password and expiry badges for a link. */
export function LinkBadges({ link }: { link: ShareLink }) {
  const { t } = useTranslation("files")
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Badge variant="secondary">
        {link.mode === "upload" ? <UploadIcon /> : <DownloadIcon />}
        {link.mode === "upload"
          ? t("links.uploadOnly")
          : t("links.viewAndDownload")}
      </Badge>
      {link.has_password ? (
        <Badge variant="outline">
          <LockIcon />
          {t("links.password")}
        </Badge>
      ) : null}
      <Badge variant={link.expired ? "destructive" : "outline"}>
        {expiryText(link)}
      </Badge>
      {link.kind === null ? (
        <Badge variant="destructive">{t("links.missing")}</Badge>
      ) : null}
    </div>
  )
}

/** Copy and Remove buttons; Remove asks first. */
export function LinkActions({
  link,
  onRemoved,
}: {
  link: ShareLink
  onRemoved: () => void
}) {
  const { t } = useTranslation("files")
  const [confirming, setConfirming] = React.useState(false)

  async function remove() {
    const { error, response } = await api.DELETE("/api/shares/{share_id}", {
      params: { path: { share_id: link.id } },
    })
    setConfirming(false)
    if (response.ok) {
      toast.add({ type: "success", title: t("links.removed") })
      onRemoved()
    } else {
      toast.add({
        type: "error",
        title: t("links.removeFailed"),
        description: errorMessage(error),
      })
    }
  }

  return (
    <div className="flex shrink-0 items-center gap-1">
      <Button
        variant="outline"
        size="sm"
        onClick={() => void copyLink(link)}
        aria-label={t("links.copyLinkTo", { name: link.name })}
      >
        <CopyIcon />
        <span className="hidden sm:inline">{t("links.copyLink")}</span>
      </Button>
      <Button
        variant="ghost"
        size="icon-sm"
        onClick={() => setConfirming(true)}
        aria-label={t("links.removeLinkTo", { name: link.name })}
      >
        <Trash2Icon />
      </Button>
      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("links.removeTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("links.removeDescription", { name: link.name })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("links.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => void remove()}
            >
              {t("links.removeLink")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
