"use client"

import * as React from "react"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import { useApi } from "@/hooks/use-api"
import { Button } from "@workspace/ui/components/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@workspace/ui/components/dialog"
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@workspace/ui/components/empty"
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldError,
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
import { Separator } from "@workspace/ui/components/separator"
import { Switch } from "@workspace/ui/components/switch"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@workspace/ui/components/table"
import { Badge } from "@workspace/ui/components/badge"
import { Spinner } from "@workspace/ui/components/spinner"
import { toast } from "@workspace/ui/components/toast"
import {
  ClockIcon,
  PlusIcon,
  Trash2Icon,
  WebhookIcon,
} from "lucide-react"

import { useCapability } from "@/components/capabilities-provider"

type Trigger = Schemas["TriggerOut"]
type JobRun = Schemas["JobRunOut"]
type TriggerAction = Schemas["AppAction"] | Schemas["PackageAction"]

function actionSummary(action: TriggerAction): string {
  if (action.kind === "app") {
    return `${action.verb} app "${action.name}"`
  }
  const extra = action.manager ? ` via ${action.manager}` : ""
  const target = action.name
  return `${action.verb} package "${target}"${extra}`
}

/** Automation page: triggers (cron + webhook) and their job runs. */
export function AutomationView() {
  const capability = useCapability("automation")
  if (!capability) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Automation</CardTitle>
          <CardDescription>
            Automation isn't available on this host.
          </CardDescription>
        </CardHeader>
      </Card>
    )
  }
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
      <div className="lg:col-span-7">
        <TriggersCard />
      </div>
      <div className="lg:col-span-5">
        <JobRunsCard />
        <McpCard />
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- triggers */

function TriggersCard() {
  const triggers = useApi<Trigger[]>(() => api.GET("/api/automation/triggers"))
  if (triggers.status === "loading") {
    return (
      <Card>
        <CardContent className="h-48 flex items-center justify-center">
          <Spinner />
        </CardContent>
      </Card>
    )
  }
  if (triggers.status === "error") {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Triggers</CardTitle>
          <CardDescription>{triggers.error}</CardDescription>
        </CardHeader>
      </Card>
    )
  }
  return <TriggersList triggers={triggers.data} />
}

function TriggersList({ triggers }: { triggers: Trigger[] }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="flex items-center gap-2">
          <ClockIcon className="size-4" /> Triggers
        </CardTitle>
        <NewTriggerDialog />
      </CardHeader>
      <CardContent>
        {triggers.length === 0 ? (
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <ClockIcon className="size-4" />
              </EmptyMedia>
              <EmptyTitle>No triggers yet</EmptyTitle>
              <EmptyDescription>
                <div className="text-sm text-muted-foreground">
                  Create a trigger to run an action on a schedule (cron) or when
                  its webhook is called (for n8n and other automation).
                </div>
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <Table>
            <TableHead>
              <TableRow>
                <TableHead className="text-left w-32">Name</TableHead>
                <TableHead className="text-left">Kind</TableHead>
                <TableHead className="text-left">Schedule</TableHead>
                <TableHead className="text-left">Action</TableHead>
                <TableHead className="text-right w-24">Enabled</TableHead>
                <TableHead className="w-20" />
              </TableRow>
            </TableHead>
            <TableBody>
              {triggers.map((t) => (
                <TriggerRow key={t.id} trigger={t} />
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

function TriggerRow({ trigger }: { trigger: Trigger }) {
  return (
    <TableRow className="hover:bg-muted/50">
      <TableCell className="font-medium truncate">{trigger.name}</TableCell>
      <TableCell className="text-sm">{trigger.kind}</TableCell>
      <TableCell className="text-sm text-muted-foreground">
        {trigger.kind === "cron" ? (
          trigger.cron_expression ?? "—"
        ) : (
          <span className="inline-flex items-center gap-1 text-xs">
            <WebhookIcon className="size-3" /> webhook
          </span>
        )}
      </TableCell>
      <TableCell className="text-sm truncate max-w-[200px]">
        {actionSummary(trigger.action)}
      </TableCell>
      <TableCell className="text-center">
        <TriggerEnabledRow trigger={trigger} />
      </TableCell>
      <TableCell className="text-right">
        {trigger.kind === "http" ? (
          <CopyWebhookButton trigger={trigger} />
        ) : (
          <DeleteTriggerButton trigger={trigger} />
        )}
      </TableCell>
    </TableRow>
  )
}

function TriggerEnabledRow({ trigger }: { trigger: Trigger }) {
  const [on, setOn] = React.useState(trigger.enabled)
  const [saving, setSaving] = React.useState(false)

  React.useEffect(() => {
    setOn(trigger.enabled)
  }, [trigger.enabled])

  async function toggle() {
    const next = !on
    setSaving(true)
    const { error, response } = await api.PATCH(
      "/api/automation/triggers/{trigger_id}",
      {
        params: { path: { trigger_id: trigger.id } },
        body: {
          kind: trigger.kind as "cron" | "http",
          name: trigger.name,
          cron_expression: trigger.cron_expression,
          action: trigger.action,
          enabled: next,
        },
      }
    )
    setSaving(false)
    if (response.ok) {
      setOn(next)
      toast.add({
        type: "success",
        title: `Trigger ${next ? "enabled" : "disabled"}`,
      })
    } else {
      toast.add({
        type: "error",
        title: "Couldn't change trigger",
        description: errorMessage(error),
      })
    }
  }

  return (
    <Switch
      checked={on}
      onCheckedChange={toggle}
      disabled={saving}
      aria-label={`Trigger ${trigger.name} enabled`}
    />
  )
}

function CopyWebhookButton({ trigger }: { trigger: Trigger }) {
  return (
    <Button
      size="sm"
      variant="outline"
      onClick={() =>
        navigator.clipboard.writeText(
          `${window.location.origin}/api/automation/webhook/${trigger.webhook_token}`
        )
      }
    >
      Copy webhook URL
    </Button>
  )
}

function DeleteTriggerButton({ trigger }: { trigger: Trigger }) {
  const [open, setOpen] = React.useState(false)
  const [deleting, setDeleting] = React.useState(false)

  async function remove() {
    setDeleting(true)
    const { error } = await api.DELETE(
      "/api/automation/triggers/{trigger_id}",
      { params: { path: { trigger_id: trigger.id } } }
    )
    setDeleting(false)
    setOpen(false)
    if (!error) {
      toast.add({ type: "success", title: "Trigger removed" })
    } else {
      toast.add({
        type: "error",
        title: "Couldn't remove trigger",
        description: errorMessage(error),
      })
    }
  }

  return (
    <>
      <Button
        size="sm"
        variant="destructive"
        onClick={() => setOpen(true)}
      >
        <Trash2Icon className="size-3" />
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete trigger</DialogTitle>
            <DialogDescription>
              Remove "{trigger.name}"? Its past job runs will stay in the log.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setOpen(false)}
            >
              Cancel
            </Button>
            <Button type="submit" onClick={remove} disabled={deleting}>
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

/* ---------------------------------------------------------------- create trigger */

type FormValues = {
  name: string
  kind: "cron" | "http"
  cron_expression: string
  action_kind: "app" | "package"
  app_name: string
  app_verb: "start" | "stop" | "restart" | "update"
  package_manager: string
  package_name: string
  package_verb: "install" | "uninstall" | "upgrade" | "refresh"
  package_source: string
}

const APP_VERBS: { value: "start" | "stop" | "restart" | "update"; label: string }[] = [
  { value: "start", label: "Start" },
  { value: "stop", label: "Stop" },
  { value: "restart", label: "Restart" },
  { value: "update", label: "Update" },
]

const PACKAGE_VERBS: { value: "install" | "uninstall" | "upgrade" | "refresh"; label: string }[] = [
  { value: "install", label: "Install" },
  { value: "uninstall", label: "Uninstall" },
  { value: "upgrade", label: "Upgrade" },
  { value: "refresh", label: "Refresh lists" },
]

function NewTriggerDialog() {
  const [open, setOpen] = React.useState(false)
  const [values, setValues] = React.useState<FormValues>({
    name: "",
    kind: "cron",
    cron_expression: "",
    action_kind: "app",
    app_name: "",
    app_verb: "start",
    package_manager: "",
    package_name: "",
    package_verb: "install",
    package_source: "",
  })
  const [submitting, setSubmitting] = React.useState(false)

  async function submit() {
    setSubmitting(true)
    const action: TriggerAction =
      values.action_kind === "app"
        ? { kind: "app", name: values.app_name, verb: values.app_verb }
        : {
            kind: "package",
            manager: values.package_manager,
            name: values.package_name,
            verb: values.package_verb,
            source: values.package_source || undefined,
          }
    const { data, error } = await api.POST("/api/automation/triggers", {
      body: {
        kind: values.kind,
        name: values.name,
        cron_expression:
          values.kind === "cron" ? values.cron_expression || undefined : undefined,
        action,
        enabled: true,
      },
    })
    setSubmitting(false)
    setOpen(false)
    if (data) {
      toast.add({ type: "success", title: "Trigger created" })
    } else {
      toast.add({
        type: "error",
        title: "Couldn't create trigger",
        description: errorMessage(error),
      })
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button variant="outline" size="sm" />}>
        <PlusIcon className="size-3" /> New trigger
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New trigger</DialogTitle>
          <DialogDescription>
            Runs an action on a schedule (cron) or when its webhook is called.
          </DialogDescription>
        </DialogHeader>
        <form className="grid w-full gap-4" onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}>
          <Field>
            <FieldLabel>Name</FieldLabel>
            <FieldContent>
              <Input
                placeholder="e.g. nightly backup"
                value={values.name}
                onChange={(e) => setValues({ ...values, name: e.target.value })}
              />
            </FieldContent>
          </Field>
          <Field>
            <FieldLabel>Trigger kind</FieldLabel>
            <div className="flex items-center gap-4">
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="radio"
                  checked={values.kind === "cron"}
                  onChange={() => setValues({ ...values, kind: "cron" })}
                  className="accent-primary h-4 w-4 shrink-0"
                />
                Cron (time)
              </label>
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="radio"
                  checked={values.kind === "http"}
                  onChange={() => setValues({ ...values, kind: "http" })}
                  className="accent-primary h-4 w-4 shrink-0"
                />
                Webhook (HTTP)
              </label>
            </div>
          </Field>
          {values.kind === "cron" ? (
            <Field>
              <FieldLabel>Cron expression</FieldLabel>
              <FieldContent>
                <Input
                  placeholder="e.g. 0 2 * * *"
                  value={values.cron_expression}
                  onChange={(e) =>
                    setValues({ ...values, cron_expression: e.target.value })
                  }
                />
              </FieldContent>
              <FieldDescription>
                Minute Hour Day Month Weekday, e.g. "0 2 * * *" runs at 02:00
                every day.
              </FieldDescription>
            </Field>
          ) : null}
          <Separator />
          <p className="text-xs font-medium text-muted-foreground mb-2">
            Action to run
          </p>
          <div className="grid grid-cols-1 gap-4">
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="radio"
                checked={values.action_kind === "app"}
                onChange={() => setValues({ ...values, action_kind: "app" })}
                className="accent-primary h-4 w-4 shrink-0"
              />
              App (start / stop / restart / update)
            </label>
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="radio"
                checked={values.action_kind === "package"}
                onChange={() => setValues({ ...values, action_kind: "package" })}
                className="accent-primary h-4 w-4 shrink-0"
              />
              Package (install / uninstall / upgrade / refresh)
            </label>
          </div>
          {values.action_kind === "app" ? (
            <div className="grid grid-cols-1 gap-4">
              <Field>
                <FieldLabel>App name</FieldLabel>
                <FieldContent>
                  <Input
                    placeholder="e.g. home-assistant"
                    value={values.app_name}
                    onChange={(e) => setValues({ ...values, app_name: e.target.value })}
                  />
                </FieldContent>
              </Field>
              <Field>
                <FieldLabel>Action</FieldLabel>
                <FieldContent>
                  <Select
                    items={APP_VERBS}
                    value={values.app_verb}
                    onValueChange={(v) =>
                      setValues({ ...values, app_verb: v as FormValues["app_verb"] })
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {APP_VERBS.map((v) => (
                        <SelectItem key={v.value} value={v.value}>
                          {v.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </FieldContent>
              </Field>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4">
              <Field>
                <FieldLabel>Manager</FieldLabel>
                <FieldContent>
                  <Input
                    placeholder="e.g. apt"
                    value={values.package_manager}
                    onChange={(e) =>
                      setValues({ ...values, package_manager: e.target.value })
                    }
                  />
                </FieldContent>
              </Field>
              <Field>
                <FieldLabel>Package name</FieldLabel>
                <FieldContent>
                  <Input
                    placeholder="e.g. jq"
                    value={values.package_name}
                    onChange={(e) => setValues({ ...values, package_name: e.target.value })}
                  />
                </FieldContent>
              </Field>
              <Field>
                <FieldLabel>Action</FieldLabel>
                <FieldContent>
                  <Select
                    items={PACKAGE_VERBS}
                    value={values.package_verb}
                    onValueChange={(v) =>
                      setValues({
                        ...values,
                        package_verb: v as FormValues["package_verb"],
                      })
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PACKAGE_VERBS.map((v) => (
                        <SelectItem key={v.value} value={v.value}>
                          {v.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </FieldContent>
              </Field>
              <Field>
                <FieldLabel>Source</FieldLabel>
                <FieldContent>
                  <Input
                    placeholder="optional source"
                    value={values.package_source}
                    onChange={(e) =>
                      setValues({ ...values, package_source: e.target.value })
                    }
                  />
                </FieldContent>
                <FieldDescription>
                  Flatpak remote, Scoop bucket, or "cask" for Homebrew casks.
                </FieldDescription>
              </Field>
            </div>
          )}
        </form>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => setOpen(false)}
            disabled={submitting}
          >
            Cancel
          </Button>
          <Button type="submit" disabled={submitting}>
            Create trigger
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/* ---------------------------------------------------------------- job runs */

function JobRunsCard() {
  const runs = useApi<JobRun[]>(() => api.GET("/api/automation/jobs"), 5000)
  if (runs.status === "loading") {
    return (
      <Card>
        <CardContent className="h-64 flex items-center justify-center">
          <Spinner />
        </CardContent>
      </Card>
    )
  }
  if (runs.status === "error") {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Job runs</CardTitle>
          <CardDescription>{runs.error}</CardDescription>
        </CardHeader>
      </Card>
    )
  }
  return <JobRunsList runs={runs.data} />
}

function JobRunsList({ runs }: { runs: JobRun[] }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="flex items-center gap-2">
          <ClockIcon className="size-4" /> Job runs
        </CardTitle>
      </CardHeader>
      <CardContent>
        {runs.length === 0 ? (
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <ClockIcon className="size-4" />
              </EmptyMedia>
              <EmptyTitle>No job runs yet</EmptyTitle>
              <EmptyDescription>Job runs appear here when a trigger fires.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <Table>
            <TableHead>
              <TableRow>
                <TableHead className="text-left w-40">Trigger</TableHead>
                <TableHead className="text-left">Status</TableHead>
                <TableHead className="text-left">Started</TableHead>
                <TableHead className="text-left">Finished</TableHead>
                <TableHead className="text-left w-32">Error</TableHead>
              </TableRow>
            </TableHead>
            <TableBody>
              {runs.map((r) => (
                <TableRow key={r.id} className="hover:bg-muted/50">
                  <TableCell className="text-sm truncate">
                    {r.trigger_id ?? "—"}
                  </TableCell>
                  <TableCell className="text-sm">
                    <Badge variant={badgeVariant(r.status)}>{r.status}</Badge>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {new Date(r.started_at).toLocaleString()}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {r.finished_at ? new Date(r.finished_at).toLocaleString() : "—"}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground truncate max-w-[200px]">
                    {r.error ?? "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

function badgeVariant(status: string): "default" | "destructive" | "secondary" {
  if (status === "succeeded") return "default"
  if (status === "failed") return "destructive"
  return "secondary"
}

/* ---------------------------------------------------------------- MCP server */

function McpCard() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>External automation</CardTitle>
        <CardDescription>
          Connect n8n or other agents to Athena via MCP or webhooks.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center gap-2 text-sm">
          <WebhookIcon className="size-3" />
          <span>Webhook endpoint:</span>
          <span className="ml-auto truncate font-mono text-xs text-muted-foreground">
            {window.location.origin}/api/automation/webhook/&lt;token&gt;
          </span>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <ClockIcon className="size-3" />
          <span>MCP server:</span>
          <span className="ml-auto truncate font-mono text-xs text-muted-foreground">
            {window.location.origin}/api/mcp
          </span>
        </div>
        <p className="text-xs text-muted-foreground">
          The webhook fires an HTTP trigger when called. The MCP server needs a
          session cookie or the "ATHENA_MCP_TOKEN" bearer token.
        </p>
      </CardContent>
    </Card>
  )
}
