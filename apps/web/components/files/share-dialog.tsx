"use client"

import * as React from "react"
import Link from "next/link"
import { useTranslation } from "react-i18next"

import { api, errorMessage } from "@workspace/api-client"
import { Button } from "@workspace/ui/components/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
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
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@workspace/ui/components/tabs"
import { toast } from "@workspace/ui/components/toast"

import {
  LinkActions,
  LinkBadges,
  type ShareLink,
  shareUrl,
} from "@/components/files/share-links"
import { useAuth } from "@/components/auth-provider"
import { ShareNetworkTab } from "@/components/files/share-network-tab"
import { copyText } from "@/lib/clipboard"

export type ShareTarget = {
  /** The file location (0 for a cloud remote, which has no public links). */
  location: number
  /** Set for a folder on a cloud remote: only the Network tab applies. */
  remote?: string
  path: string
  name: string
  kind: "dir" | "file" | "other"
}

const EXPIRY_DAYS = [1, 7, 30]

/** Links to one file or folder: the existing ones, and a form for a new one. */
export function ShareDialog({
  target,
  onClose,
}: {
  target: ShareTarget | null
  onClose: () => void
}) {
  const { t } = useTranslation("files")
  const { user } = useAuth()
  const MODES = [
    { value: "read", label: t("shareDialog.modeRead") },
    { value: "upload", label: t("shareDialog.modeUpload") },
  ]
  const EXPIRY = [
    { value: "0", label: t("shareDialog.expiryNever") },
    ...EXPIRY_DAYS.map((d) => ({
      value: String(d),
      label: t("shareDialog.expiryDays", { count: d }),
    })),
  ]
  const [links, setLinks] = React.useState<ShareLink[] | null>(null)
  const [mode, setMode] = React.useState("read")
  const [password, setPassword] = React.useState("")
  const [days, setDays] = React.useState("0")
  const [pending, setPending] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const load = React.useCallback(async () => {
    // A cloud folder has no public links (they need a file location).
    if (!target || target.remote) return
    const { data } = await api.GET("/api/shares", {
      params: { query: { location: target.location, path: target.path } },
    })
    setLinks(data ?? [])
  }, [target])

  React.useEffect(() => {
    setLinks(null)
    setMode("read")
    setPassword("")
    setDays("0")
    setError(null)
    void load()
  }, [load])

  async function create(event: React.FormEvent) {
    event.preventDefault()
    if (!target) return
    setPending(true)
    setError(null)
    const expires = Number(days)
      ? new Date(Date.now() + Number(days) * 86_400_000).toISOString()
      : null
    const { data, error } = await api.POST("/api/shares", {
      body: {
        location: target.location,
        path: target.path,
        mode: mode as ShareLink["mode"],
        password: password || null,
        expires_at: expires,
      },
    })
    setPending(false)
    if (!data) {
      setError(errorMessage(error))
      return
    }
    setPassword("")
    await load()
    const copied = await copyText(shareUrl(data))
    toast.add({
      type: "success",
      title: t("shareDialog.created"),
      description: copied ? t("shareDialog.copiedToClipboard") : undefined,
    })
  }

  const isFolder = target?.kind === "dir"

  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="truncate">
            {t("shareDialog.title", { name: target?.name })}
          </DialogTitle>
        </DialogHeader>

        <Tabs
          defaultValue={target?.remote && user.is_admin ? "network" : "link"}
        >
          <TabsList>
            <TabsTrigger value="link" disabled={!!target?.remote}>
              {t("shareDialog.tabLink")}
            </TabsTrigger>
            {user.is_admin ? (
              <TabsTrigger value="network">
                {t("shareDialog.tabNetwork")}
              </TabsTrigger>
            ) : null}
          </TabsList>
          <TabsContent value="link" className="flex flex-col gap-4 pt-2">
            <p className="text-sm text-muted-foreground">
              {t("shareDialog.description")}
            </p>
            {links === null ? (
              <Skeleton className="h-12 w-full" />
            ) : links.length ? (
              <ul
                className="flex flex-col gap-2"
                aria-label={t("shareDialog.links")}
              >
                {links.map((link) => (
                  <li
                    key={link.id}
                    className="flex items-center gap-2 rounded-lg border p-2"
                  >
                    <div className="min-w-0 flex-1">
                      <LinkBadges link={link} />
                    </div>
                    <LinkActions link={link} onRemoved={() => void load()} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">
                {t("shareDialog.noLinks")}
              </p>
            )}

            <Separator />

            <form id="new-share" onSubmit={create}>
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="share-mode">
                    {t("shareDialog.visitorsCan")}
                  </FieldLabel>
                  <Select
                    items={MODES}
                    value={mode}
                    onValueChange={(v) => v && setMode(v)}
                    disabled={!isFolder}
                  >
                    <SelectTrigger id="share-mode" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectGroup>
                        {MODES.map((m) => (
                          <SelectItem key={m.value} value={m.value}>
                            {m.label}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                  <FieldDescription>
                    {!isFolder
                      ? t("shareDialog.needsFolder")
                      : mode === "upload"
                        ? t("shareDialog.uploadHint")
                        : t("shareDialog.readHint")}
                  </FieldDescription>
                </Field>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field>
                    <FieldLabel htmlFor="share-password">
                      {t("shareDialog.passwordOptional")}
                    </FieldLabel>
                    <Input
                      id="share-password"
                      type="password"
                      autoComplete="new-password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                    />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="share-expiry">
                      {t("shareDialog.expires")}
                    </FieldLabel>
                    <Select
                      items={EXPIRY}
                      value={days}
                      onValueChange={(v) => v && setDays(v)}
                    >
                      <SelectTrigger id="share-expiry" className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectGroup>
                          {EXPIRY.map((e) => (
                            <SelectItem key={e.value} value={e.value}>
                              {e.label}
                            </SelectItem>
                          ))}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                  </Field>
                </div>
                {error ? <FieldError>{error}</FieldError> : null}
              </FieldGroup>
            </form>

            <DialogFooter>
              <Button
                variant="outline"
                render={<Link href="/files/shares/" />}
                nativeButton={false}
              >
                {t("shareDialog.allLinks")}
              </Button>
              <Button type="submit" form="new-share" disabled={pending}>
                {pending ? <Spinner /> : null}
                {t("shareDialog.create")}
              </Button>
            </DialogFooter>
          </TabsContent>
          {user.is_admin ? (
            <TabsContent value="network" className="pt-2">
              {target ? <ShareNetworkTab target={target} /> : null}
            </TabsContent>
          ) : null}
        </Tabs>
      </DialogContent>
    </Dialog>
  )
}
