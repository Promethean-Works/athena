"use client"

import * as React from "react"

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
  const { destinations } = useDestinations()
  const [apps, setApps] = React.useState<string[] | null>(null)
  const [submitting, setSubmitting] = React.useState(false)
  const [name, setName] = React.useState("")
  const [destinationId, setDestinationId] = React.useState("")
  const [athena, setAthena] = React.useState(true)
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
        toast.add({ title: `Plan "${data.name}" created`, type: "success" })
        onAdded(data)
        onClose()
        return
      }
      toast.add({
        title: errorMessage(err, "Couldn't create plan"),
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
          <DialogTitle>Add backup plan</DialogTitle>
          <DialogDescription>
            Pick what to back up, where, and how often. Apps are stopped during
            their backup unless "Back up while running" is on.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit}>
          <Field>
            <FieldLabel>Name</FieldLabel>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Daily apps"
              required
            />
          </Field>
          <Field>
            <FieldLabel>Destination</FieldLabel>
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
              Back up Athena (settings, DB, secrets, TLS)
            </FieldLabel>
            <FieldDescription>Recommended: on by default.</FieldDescription>
          </Field>
          {apps.length ? (
            <>
              <Field>
                <FieldLabel>Apps</FieldLabel>
                <FieldDescription>
                  Which apps to include in the plan.
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
              No apps found. Start apps from Store → Apps first.
            </FieldDescription>
          )}
          <Separator />
          <Field>
            <FieldLabel>Schedule (cron)</FieldLabel>
            <Input
              value={schedule}
              onChange={(e) => setSchedule(e.target.value)}
              placeholder="0 3 * * *  (daily at 03:00)"
            />
            <FieldDescription>
              Leave empty for manual runs only. Scheduled runs come with part 4.
            </FieldDescription>
          </Field>
          <Field>
            <FieldLabel>Retention</FieldLabel>
            <FieldGroup>
              <Field>
                <FieldLabel>Keep last</FieldLabel>
                <Input
                  type="number"
                  value={keepLast}
                  onChange={(e) => setKeepLast(e.target.value)}
                  min="1"
                />
              </Field>
              <Field>
                <FieldLabel>Keep daily</FieldLabel>
                <Input
                  type="number"
                  value={keepDaily}
                  onChange={(e) => setKeepDaily(e.target.value)}
                  min="1"
                />
              </Field>
              <Field>
                <FieldLabel>Keep weekly</FieldLabel>
                <Input
                  type="number"
                  value={keepWeekly}
                  onChange={(e) => setKeepWeekly(e.target.value)}
                  min="1"
                />
              </Field>
              <Field>
                <FieldLabel>Keep monthly</FieldLabel>
                <Input
                  type="number"
                  value={keepMonthly}
                  onChange={(e) => setKeepMonthly(e.target.value)}
                  min="1"
                />
              </Field>
            </FieldGroup>
            <FieldDescription>
              `restic forget --keep-…` per item. Defaults: 7 daily / 4 weekly /
              6 monthly.
            </FieldDescription>
          </Field>
        </form>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            disabled={
              submitting ||
              !name ||
              !destinationId ||
              (!athena && selectedApps.length === 0)
            }
          >
            Create plan
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
