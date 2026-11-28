"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import { Button } from "@workspace/ui/components/button"
import { Checkbox } from "@workspace/ui/components/checkbox"
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
  FieldGroup,
  FieldLabel,
} from "@workspace/ui/components/field"
import { Input } from "@workspace/ui/components/input"
import { Separator } from "@workspace/ui/components/separator"
import { Select } from "@workspace/ui/components/select"
import {
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import { toast } from "@workspace/ui/components/toast"

import { useDestinations } from "./use-backup"

/** Add a backup plan: destination, items (Athena + apps), schedule and retention. */
export function AddPlanDialog({
  open,
  onClose,
  onAdded,
}: {
  open: boolean
  onClose: () => void
  /** Called with the created plan. */
  onAdded: (plan: Schemas["PlanOut"]) => void
}) {
  const { t } = useTranslation("backup")
  const { destinations } = useDestinations()
  const [apps, setApps] = React.useState<string[] | null>(null)
  const [submitting, setSubmitting] = React.useState(false)
  const [name, setName] = React.useState("")
  const [destinationId, setDestinationId] = React.useState("")
  const [athena, setAthena] = React.useState(true)
  const [userFiles, setUserFiles] = React.useState(true)
  const [appSelections, setAppSelections] = React.useState<
    Record<string, boolean>
  >({})
  const [schedule, setSchedule] = React.useState("")
  const [keepLast, setKeepLast] = React.useState("7")
  const [keepDaily, setKeepDaily] = React.useState("7")
  const [keepWeekly, setKeepWeekly] = React.useState("4")
  const [keepMonthly, setKeepMonthly] = React.useState("6")

  const selectedApps = React.useMemo(
    () =>
      Object.entries(appSelections)
        .filter(([, checked]) => checked)
        .map(([name]) => name),
    [appSelections]
  )

  React.useEffect(() => {
    void api.GET("/api/apps").then(({ data }) => {
      if (data) setApps(data.map((a) => a.name))
    })
  }, [])

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    try {
      const items: Schemas["PlanItems"] = {
        athena,
        user_files: userFiles,
        apps: selectedApps.map((name) => ({ name, while_running: false })),
      }
      const { data, error: err } = await api.POST("/api/backup/plans", {
        body: {
          name,
          destination_id: destinationId,
          items,
          schedule: schedule || undefined,
          retention: {
            keep_last: Number(keepLast) || 7,
            keep_daily: Number(keepDaily) || 7,
            keep_weekly: Number(keepWeekly) || 4,
            keep_monthly: Number(keepMonthly) || 6,
          },
          enabled: true,
        },
      })
      if (data) {
        toast.add({
          title: t("toast.planCreated", { name: data.name }),
          type: "success",
        })
        onAdded(data)
        onClose()
        return
      }
      toast.add({
        title: errorMessage(err, t("errors.createPlan")),
        type: "error",
      })
      return
    } finally {
      setSubmitting(false)
    }
  }

  if (!apps || !destinations) {
    return null
  }

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("addPlan.title")}</DialogTitle>
          <DialogDescription>
            {t("addPlan.description")}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit}>
          <Field>
            <FieldLabel>{t("addPlan.name")}</FieldLabel>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("addPlan.namePlaceholder")}
              required
            />
          </Field>
          <Field>
            <FieldLabel>{t("addPlan.destination")}</FieldLabel>
            <Select
              value={destinationId}
              onValueChange={(v: string | null) => setDestinationId(v ?? "")}
              required
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {destinations.map((d) => (
                  <SelectItem key={d.id} value={d.id}>
                    {d.name} · {d.location}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field>
            <FieldLabel className="flex items-center gap-2">
              <Checkbox
                checked={athena}
                onCheckedChange={(v) => setAthena(v)}
                required
              />
              {t("addPlan.athena")}
            </FieldLabel>
            <FieldDescription>{t("addPlan.athenaHint")}</FieldDescription>
          </Field>
          <Field>
            <FieldLabel className="flex items-center gap-2">
              <Checkbox
                checked={userFiles}
                onCheckedChange={(v) => setUserFiles(v)}
              />
              {t("addPlan.userFiles")}
            </FieldLabel>
            <FieldDescription>{t("addPlan.userFilesHint")}</FieldDescription>
          </Field>
          {apps.length ? (
            <>
              <Field>
                <FieldLabel>{t("addPlan.apps")}</FieldLabel>
                <FieldDescription>
                  {t("addPlan.appsHint")}
                </FieldDescription>
                <div className="max-h-48 space-y-1 overflow-y-auto rounded-md border p-2">
                  {apps.map((appName) => (
                    <CheckboxItem
                      key={appName}
                      checked={!!appSelections[appName]}
                      onCheckedChange={(v) =>
                        setAppSelections((prev) => ({ ...prev, [appName]: v }))
                      }
                      label={appName}
                    />
                  ))}
                </div>
              </Field>
            </>
          ) : (
            <FieldDescription>
              {t("addPlan.noApps")}
            </FieldDescription>
          )}
          <Separator />
          <Field>
            <FieldLabel>{t("addPlan.schedule")}</FieldLabel>
            <Input
              value={schedule}
              onChange={(e) => setSchedule(e.target.value)}
              placeholder={t("addPlan.schedulePlaceholder")}
            />
            <FieldDescription>
              {t("addPlan.scheduleHint")}
            </FieldDescription>
          </Field>
          <Field>
            <FieldLabel>{t("addPlan.retention")}</FieldLabel>
            <FieldGroup>
              <Field>
                <FieldLabel>{t("addPlan.keepLast")}</FieldLabel>
                <Input
                  type="number"
                  value={keepLast}
                  onChange={(e) => setKeepLast(e.target.value)}
                  min="1"
                />
              </Field>
              <Field>
                <FieldLabel>{t("addPlan.keepDaily")}</FieldLabel>
                <Input
                  type="number"
                  value={keepDaily}
                  onChange={(e) => setKeepDaily(e.target.value)}
                  min="1"
                />
              </Field>
              <Field>
                <FieldLabel>{t("addPlan.keepWeekly")}</FieldLabel>
                <Input
                  type="number"
                  value={keepWeekly}
                  onChange={(e) => setKeepWeekly(e.target.value)}
                  min="1"
                />
              </Field>
              <Field>
                <FieldLabel>{t("addPlan.keepMonthly")}</FieldLabel>
                <Input
                  type="number"
                  value={keepMonthly}
                  onChange={(e) => setKeepMonthly(e.target.value)}
                  min="1"
                />
              </Field>
            </FieldGroup>
            <FieldDescription>
              {t("addPlan.retentionHint")}
            </FieldDescription>
          </Field>
        </form>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button
            type="submit"
            disabled={
              submitting ||
              !name ||
              !destinationId ||
              (!athena && !userFiles && selectedApps.length === 0)
            }
          >
            {t("addPlan.create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function CheckboxItem({
  checked,
  onCheckedChange,
  label,
}: {
  checked: boolean
  onCheckedChange: (v: boolean) => void
  label: string
}) {
  return (
    <Checkbox checked={checked} onCheckedChange={onCheckedChange}>
      {label}
    </Checkbox>
  )
}
