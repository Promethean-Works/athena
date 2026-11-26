"use client"

import * as React from "react"
import { FolderIcon, KeyIcon } from "lucide-react"
import { useTranslation } from "react-i18next"

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
  Field,
  FieldDescription,
  FieldLabel,
} from "@workspace/ui/components/field"
import { Input } from "@workspace/ui/components/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import { toast } from "@workspace/ui/components/toast"

type Kind = Schemas["DestinationIn"]["kind"]

/** Add a backup destination, with the recovery-kit step before anything is created. */
export function AddDestinationDialog({
  open,
  onClose,
  onAdded,
}: {
  open: boolean
  onClose: () => void
  /** Called with the created destination. */
  onAdded: (destination: Schemas["DestinationOut"]) => void
}) {
  const { t } = useTranslation("backup")
  const [submitting, setSubmitting] = React.useState(false)
  const [step, setStep] = React.useState<"form" | "kit">("form")
  const [name, setName] = React.useState("")
  const [kind, setKind] = React.useState<Kind>("local")
  const [path, setPath] = React.useState("")
  const [remote, setRemote] = React.useState("")
  const [password, setPassword] = React.useState("")
  const [kitSaved, setKitSaved] = React.useState(false)
  const [kit, setKit] = React.useState<Schemas["RecoveryKit"] | null>(null)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    try {
      if (step === "form") {
        const { data, error: err } = await api.POST(
          "/api/backup/destinations/recovery-kit",
          {
            body: {
              name,
              kind,
              path: kind === "local" ? path : "",
              remote: kind === "rclone" ? remote : "",
              password: password || undefined,
            },
          }
        )
        if (data) {
          setKit(data)
          setStep("kit")
          return
        }
        toast.add({
          title: errorMessage(err, t("addDestination.prepareFailed")),
          type: "error",
        })
        return
      }

      // "kit" step: confirm the kit was saved, then create.
      if (!kitSaved) {
        toast.add({
          title: t("addDestination.saveKitFirst"),
          type: "error",
        })
        return
      }
      const { data, error: err } = await api.POST("/api/backup/destinations", {
        body: {
          name,
          kind,
          path: kind === "local" ? path : "",
          remote: kind === "rclone" ? remote : "",
          password,
          recovery_kit_saved: true,
        },
      })
      if (data) {
        toast.add({
          title: t("toast.destinationCreated", { name: data.name }),
          type: "success",
        })
        onAdded(data)
        onClose()
        return
      }
      toast.add({
        title: errorMessage(err, t("errors.createDestination")),
        type: "error",
      })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {step === "form"
              ? t("addDestination.title")
              : t("addDestination.kitTitle")}
          </DialogTitle>
          <DialogDescription>
            {step === "form"
              ? t("addDestination.description")
              : t("addDestination.kitDescription")}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit}>
          {step === "form" ? (
            <>
              <Field>
                <FieldLabel>{t("addDestination.name")}</FieldLabel>
                <Input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={t("addDestination.namePlaceholder")}
                  required
                />
              </Field>
              <Field>
                <FieldLabel>{t("addDestination.kind")}</FieldLabel>
                <Select value={kind} onValueChange={(v) => setKind(v as Kind)}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="local">
                      <FolderIcon data-icon="inline-start" />
                      {t("addDestination.local")}
                    </SelectItem>
                    <SelectItem value="rclone">
                      {t("addDestination.rclone")}
                    </SelectItem>
                  </SelectContent>
                </Select>
              </Field>
              {kind === "local" ? (
                <Field>
                  <FieldLabel>{t("addDestination.folder")}</FieldLabel>
                  <Input
                    value={path}
                    onChange={(e) => setPath(e.target.value)}
                    placeholder="/mnt/backups/athena"
                    required
                  />
                  <FieldDescription>
                    {t("addDestination.folderHint")}
                  </FieldDescription>
                </Field>
              ) : (
                <Field>
                  <FieldLabel>{t("addDestination.remote")}</FieldLabel>
                  <Input
                    value={remote}
                    onChange={(e) => setRemote(e.target.value)}
                    placeholder="myremote:path/to/backups"
                    required
                  />
                  <FieldDescription>
                    {t("addDestination.remoteHint")}
                  </FieldDescription>
                </Field>
              )}
              <Field>
                <FieldLabel>{t("addDestination.password")}</FieldLabel>
                <Input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={t("addDestination.passwordPlaceholder")}
                />
                <FieldDescription>
                  {t("addDestination.passwordHint")}
                </FieldDescription>
              </Field>
            </>
          ) : (
            <>
              <div className="mb-4">
                <KeyIcon className="mr-2 h-5 w-5" />
                <p className="font-mono text-sm break-all">{kit?.password}</p>
              </div>
              <div className="mb-4 rounded-lg border bg-muted p-3 text-sm">
                {kit?.kit}
              </div>
              <Field>
                <FieldLabel className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={kitSaved}
                    onChange={(e) => setKitSaved(e.target.checked)}
                    required
                  />
                  {t("addDestination.kitSaved")}
                </FieldLabel>
              </Field>
            </>
          )}
        </form>
        <DialogFooter>
          {step === "form" ? (
            <Button type="button" variant="outline" onClick={onClose}>
              {t("cancel")}
            </Button>
          ) : (
            <Button
              type="button"
              variant="outline"
              onClick={() => setStep("form")}
            >
              {t("back")}
            </Button>
          )}
          <Button
            type="submit"
            disabled={submitting || (step === "kit" && !kitSaved)}
          >
            {step === "form"
              ? t("addDestination.next")
              : t("addDestination.create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
