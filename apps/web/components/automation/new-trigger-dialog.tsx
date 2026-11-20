"use client"

import * as React from "react"
import { CheckIcon, PlusIcon } from "lucide-react"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import { Button } from "@workspace/ui/components/button"
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@workspace/ui/components/combobox"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@workspace/ui/components/dialog"
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSeparator,
  FieldSet,
} from "@workspace/ui/components/field"
import { Input } from "@workspace/ui/components/input"
import {
  RadioGroup,
  RadioGroupItem,
} from "@workspace/ui/components/radio-group"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import { Spinner } from "@workspace/ui/components/spinner"
import { toast } from "@workspace/ui/components/toast"

import { useAppsList } from "@/components/apps/use-apps-list"
import { CopyUrl } from "@/components/automation/copy-url"
import { CRON_PRESETS, checkCron } from "@/components/automation/cron"
import {
  webhookUrl,
  type Trigger,
  type TriggerAction,
} from "@/components/automation/triggers"
import { useApi } from "@/hooks/use-api"

type AppVerb = Schemas["AppAction"]["verb"]
type PackageVerb = Schemas["PackageAction"]["verb"]
type Manager = Schemas["ManagerOut"]

const APP_VERBS: { value: AppVerb; label: string }[] = [
  { value: "start", label: "Start" },
  { value: "stop", label: "Stop" },
  { value: "restart", label: "Restart" },
  { value: "update", label: "Update (pull and recreate)" },
]

const PACKAGE_VERBS: { value: PackageVerb; label: string }[] = [
  { value: "install", label: "Install" },
  { value: "uninstall", label: "Uninstall" },
  { value: "upgrade", label: "Upgrade" },
  { value: "refresh", label: "Refresh package lists" },
]

/** "New trigger" button and dialog. Calls `onCreated` so the list reloads. */
export function NewTriggerDialog({
  onCreated,
}: {
  onCreated: () => Promise<void>
}) {
  const [open, setOpen] = React.useState(false)
  const [created, setCreated] = React.useState<Trigger | null>(null)

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) setCreated(null)
      }}
    >
      <DialogTrigger render={<Button size="sm" />}>
        <PlusIcon /> New trigger
      </DialogTrigger>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg">
        {created ? (
          <CreatedWebhook trigger={created} />
        ) : (
          <NewTriggerForm
            onCreated={async (trigger) => {
              await onCreated()
              if (trigger.kind === "http" && trigger.webhook_token)
                setCreated(trigger)
              else setOpen(false)
            }}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}

function CreatedWebhook({ trigger }: { trigger: Trigger }) {
  return (
    <>
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <CheckIcon className="size-4" /> Webhook trigger created
        </DialogTitle>
        <DialogDescription>
          Send a POST request to this URL to run &quot;{trigger.name}&quot;.
          Anyone with the URL can fire it, so keep it private. You can copy it
          again from the trigger list.
        </DialogDescription>
      </DialogHeader>
      <Field>
        <FieldLabel htmlFor="new-webhook-url">Webhook URL</FieldLabel>
        <CopyUrl
          id="new-webhook-url"
          label="Webhook URL"
          value={webhookUrl(trigger.webhook_token ?? "")}
        />
      </Field>
      <DialogFooter>
        <DialogClose render={<Button />}>Done</DialogClose>
      </DialogFooter>
    </>
  )
}

function NewTriggerForm({
  onCreated,
}: {
  onCreated: (trigger: Trigger) => Promise<void>
}) {
  const [name, setName] = React.useState("")
  const [kind, setKind] = React.useState<"cron" | "http">("cron")
  const [cron, setCron] = React.useState("")
  const [actionKind, setActionKind] = React.useState<"app" | "package">("app")
  const [appName, setAppName] = React.useState<string | null>(null)
  const [appVerb, setAppVerb] = React.useState<AppVerb>("restart")
  const [manager, setManager] = React.useState<string | null>(null)
  const [packageVerb, setPackageVerb] = React.useState<PackageVerb>("upgrade")
  const [packageName, setPackageName] = React.useState("")
  const [source, setSource] = React.useState("")
  const [submitted, setSubmitted] = React.useState(false)
  const [submitting, setSubmitting] = React.useState(false)
  const [serverError, setServerError] = React.useState<string | null>(null)

  const cronCheck = checkCron(cron)
  const needsPackageName = packageVerb !== "refresh"
  const errors = {
    name: name.trim() ? null : "Give the trigger a name.",
    cron: kind === "cron" && !cronCheck.ok ? cronCheck.error : null,
    app: actionKind === "app" && !appName ? "Pick an app." : null,
    manager:
      actionKind === "package" && !manager ? "Pick a package manager." : null,
    packageName:
      actionKind === "package" && needsPackageName && !packageName.trim()
        ? "Enter a package name."
        : null,
  }
  const show = (error: string | null) => (submitted ? error : null)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setSubmitted(true)
    setServerError(null)
    if (Object.values(errors).some(Boolean)) return
    const action: TriggerAction =
      actionKind === "app"
        ? { kind: "app", name: appName!, verb: appVerb }
        : {
            kind: "package",
            manager: manager!,
            // Refresh has no package, but the action needs a name: use the manager's.
            name: needsPackageName ? packageName.trim() : manager!,
            verb: packageVerb,
            source: needsPackageName && source.trim() ? source.trim() : null,
          }
    setSubmitting(true)
    const { data, error } = await api.POST("/api/automation/triggers", {
      body: {
        kind,
        name: name.trim(),
        cron_expression: kind === "cron" ? cron.trim() : null,
        action,
        enabled: true,
      },
    })
    if (data) {
      toast.add({ type: "success", title: `Trigger ${data.name} created` })
      await onCreated(data)
    } else {
      setServerError(errorMessage(error, "Couldn't create the trigger"))
    }
    setSubmitting(false)
  }

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-6">
      <DialogHeader>
        <DialogTitle>New trigger</DialogTitle>
        <DialogDescription>
          Run an app or package action on a schedule, or whenever a webhook is
          called.
        </DialogDescription>
      </DialogHeader>

      <FieldGroup>
        <Field data-invalid={!!show(errors.name)}>
          <FieldLabel htmlFor="trigger-name">Name</FieldLabel>
          <Input
            id="trigger-name"
            placeholder="e.g. Nightly Jellyfin restart"
            maxLength={64}
            value={name}
            aria-invalid={!!show(errors.name)}
            onChange={(e) => setName(e.target.value)}
          />
          <FieldError>{show(errors.name)}</FieldError>
        </Field>

        <FieldSet>
          <FieldLegend variant="label">When it runs</FieldLegend>
          <RadioGroup
            value={kind}
            onValueChange={(v) => setKind(v as "cron" | "http")}
            className="sm:grid-cols-2"
          >
            <Field orientation="horizontal">
              <RadioGroupItem value="cron" id="trigger-kind-cron" />
              <FieldLabel htmlFor="trigger-kind-cron" className="font-normal">
                On a schedule (cron)
              </FieldLabel>
            </Field>
            <Field orientation="horizontal">
              <RadioGroupItem value="http" id="trigger-kind-http" />
              <FieldLabel htmlFor="trigger-kind-http" className="font-normal">
                When a webhook is called
              </FieldLabel>
            </Field>
          </RadioGroup>
        </FieldSet>

        {kind === "cron" ? (
          <Field data-invalid={!!show(errors.cron)}>
            <FieldLabel htmlFor="trigger-cron">Schedule</FieldLabel>
            <div className="flex flex-wrap gap-2">
              {CRON_PRESETS.map((preset) => (
                <Button
                  key={preset.expression}
                  type="button"
                  size="xs"
                  variant={
                    cron.trim() === preset.expression ? "secondary" : "outline"
                  }
                  aria-pressed={cron.trim() === preset.expression}
                  onClick={() => setCron(preset.expression)}
                >
                  {preset.label}
                </Button>
              ))}
            </div>
            <Input
              id="trigger-cron"
              placeholder="minute hour day month weekday, e.g. 0 2 * * *"
              className="font-mono"
              value={cron}
              aria-invalid={
                !!show(errors.cron) || (!!cron.trim() && !cronCheck.ok)
              }
              aria-describedby="trigger-cron-help"
              onChange={(e) => setCron(e.target.value)}
            />
            {cron.trim() && !cronCheck.ok ? (
              <FieldError>{cronCheck.error}</FieldError>
            ) : (
              <FieldError>{show(errors.cron)}</FieldError>
            )}
            <FieldDescription id="trigger-cron-help">
              {cronCheck.ok
                ? cronCheck.description
                : "Five fields: minute, hour, day of month, month, weekday. Times are UTC."}
            </FieldDescription>
          </Field>
        ) : (
          <FieldDescription>
            After you create it you get a secret URL. A POST request to it (from
            n8n, a script or curl) runs the action.
          </FieldDescription>
        )}

        <FieldSeparator />

        <FieldSet>
          <FieldLegend variant="label">What it does</FieldLegend>
          <RadioGroup
            value={actionKind}
            onValueChange={(v) => setActionKind(v as "app" | "package")}
            className="sm:grid-cols-2"
          >
            <Field orientation="horizontal">
              <RadioGroupItem value="app" id="trigger-action-app" />
              <FieldLabel htmlFor="trigger-action-app" className="font-normal">
                App action
              </FieldLabel>
            </Field>
            <Field orientation="horizontal">
              <RadioGroupItem value="package" id="trigger-action-package" />
              <FieldLabel
                htmlFor="trigger-action-package"
                className="font-normal"
              >
                Package action
              </FieldLabel>
            </Field>
          </RadioGroup>
        </FieldSet>

        {actionKind === "app" ? (
          <AppFields
            appName={appName}
            setAppName={setAppName}
            appVerb={appVerb}
            setAppVerb={setAppVerb}
            error={show(errors.app)}
          />
        ) : (
          <PackageFields
            manager={manager}
            setManager={(m) => {
              setManager(m)
              setPackageName("")
            }}
            verb={packageVerb}
            setVerb={setPackageVerb}
            packageName={packageName}
            setPackageName={setPackageName}
            source={source}
            setSource={setSource}
            errors={{
              manager: show(errors.manager),
              packageName: show(errors.packageName),
            }}
          />
        )}

        {serverError ? <FieldError>{serverError}</FieldError> : null}
      </FieldGroup>

      <DialogFooter>
        <DialogClose
          render={<Button type="button" variant="outline" />}
          disabled={submitting}
        >
          Cancel
        </DialogClose>
        <Button type="submit" disabled={submitting}>
          {submitting ? <Spinner /> : null} Create trigger
        </Button>
      </DialogFooter>
    </form>
  )
}

function AppFields({
  appName,
  setAppName,
  appVerb,
  setAppVerb,
  error,
}: {
  appName: string | null
  setAppName: (name: string | null) => void
  appVerb: AppVerb
  setAppVerb: (verb: AppVerb) => void
  error: string | null
}) {
  const { apps, error: listError } = useAppsList()
  const items = (apps ?? []).map((a) => ({
    value: a.name,
    label: a.title ?? a.name,
  }))

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field data-invalid={!!(error || listError)}>
        <FieldLabel htmlFor="trigger-app">App</FieldLabel>
        <Select
          items={items}
          value={appName}
          onValueChange={(v) => setAppName(v as string | null)}
          disabled={!apps || apps.length === 0}
        >
          <SelectTrigger
            id="trigger-app"
            className="w-full"
            aria-invalid={!!error}
          >
            <SelectValue
              placeholder={
                apps === null
                  ? "Loading apps…"
                  : apps.length
                    ? "Choose an app"
                    : "No apps installed"
              }
            />
          </SelectTrigger>
          <SelectContent>
            {items.map((item) => (
              <SelectItem key={item.value} value={item.value}>
                {item.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <FieldError>{listError ?? error}</FieldError>
      </Field>
      <Field>
        <FieldLabel htmlFor="trigger-app-verb">Action</FieldLabel>
        <Select
          items={APP_VERBS}
          value={appVerb}
          onValueChange={(v) => v && setAppVerb(v as AppVerb)}
        >
          <SelectTrigger id="trigger-app-verb" className="w-full">
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
      </Field>
    </div>
  )
}

function PackageFields({
  manager,
  setManager,
  verb,
  setVerb,
  packageName,
  setPackageName,
  source,
  setSource,
  errors,
}: {
  manager: string | null
  setManager: (id: string | null) => void
  verb: PackageVerb
  setVerb: (verb: PackageVerb) => void
  packageName: string
  setPackageName: (name: string) => void
  source: string
  setSource: (source: string) => void
  errors: { manager: string | null; packageName: string | null }
}) {
  const managers = useApi<Manager[]>(() => api.GET("/api/packages"))
  const ready =
    managers.status === "ok" ? managers.data.filter((m) => m.available) : []
  const items = ready.map((m) => ({ value: m.id, label: m.label }))
  const current = ready.find((m) => m.id === manager)
  const verbs = PACKAGE_VERBS.filter(
    (v) => v.value !== "refresh" || current?.can_refresh !== false
  )

  // Pick the first ready manager once the list arrives.
  React.useEffect(() => {
    if (manager === null && ready[0]) setManager(ready[0].id)
  }, [manager, ready, setManager])

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field data-invalid={!!errors.manager || managers.status === "error"}>
        <FieldLabel htmlFor="trigger-manager">Package manager</FieldLabel>
        <Select
          items={items}
          value={manager}
          onValueChange={(v) => setManager(v as string | null)}
          disabled={ready.length === 0}
        >
          <SelectTrigger id="trigger-manager" className="w-full">
            <SelectValue
              placeholder={
                managers.status === "loading"
                  ? "Loading…"
                  : ready.length
                    ? "Choose a manager"
                    : "None ready on this host"
              }
            />
          </SelectTrigger>
          <SelectContent>
            {items.map((item) => (
              <SelectItem key={item.value} value={item.value}>
                {item.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <FieldError>
          {managers.status === "error" ? managers.error : errors.manager}
        </FieldError>
      </Field>
      <Field>
        <FieldLabel htmlFor="trigger-package-verb">Action</FieldLabel>
        <Select
          items={verbs}
          value={verb}
          onValueChange={(v) => v && setVerb(v as PackageVerb)}
        >
          <SelectTrigger id="trigger-package-verb" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {verbs.map((v) => (
              <SelectItem key={v.value} value={v.value}>
                {v.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      {verb !== "refresh" && manager ? (
        <>
          <Field data-invalid={!!errors.packageName} className="sm:col-span-2">
            <FieldLabel htmlFor="trigger-package">Package</FieldLabel>
            {verb === "install" ? (
              <Input
                id="trigger-package"
                placeholder="e.g. jq"
                value={packageName}
                aria-invalid={!!errors.packageName}
                onChange={(e) => setPackageName(e.target.value)}
              />
            ) : (
              <InstalledPackagePicker
                key={manager}
                manager={manager}
                value={packageName}
                onChange={setPackageName}
              />
            )}
            <FieldError>{errors.packageName}</FieldError>
          </Field>
          {verb === "install" ? (
            <Field className="sm:col-span-2">
              <FieldLabel htmlFor="trigger-source">
                Source (optional)
              </FieldLabel>
              <Input
                id="trigger-source"
                value={source}
                onChange={(e) => setSource(e.target.value)}
              />
              <FieldDescription>
                A Flatpak remote, a Scoop bucket, or &quot;cask&quot; for a
                Homebrew cask.
              </FieldDescription>
            </Field>
          ) : null}
        </>
      ) : null}
    </div>
  )
}

/**
 * Uninstall and upgrade work on installed packages, so pick one from the manager's
 * list. Falls back to a text box when the list can't be read.
 */
function InstalledPackagePicker({
  manager,
  value,
  onChange,
}: {
  manager: string
  value: string
  onChange: (name: string) => void
}) {
  const installed = useApi(() =>
    api.GET("/api/packages/{manager}/installed", {
      params: { path: { manager } },
    })
  )

  if (installed.status !== "ok") {
    return (
      <>
        <Input
          id="trigger-package"
          placeholder={
            installed.status === "loading"
              ? "Loading installed packages…"
              : "e.g. jq"
          }
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
        {installed.status === "error" ? (
          <FieldDescription>
            Couldn&apos;t list installed packages ({installed.error}); type the
            name.
          </FieldDescription>
        ) : null}
      </>
    )
  }

  const names = installed.data.map((p) => p.name)
  return (
    <Combobox
      items={names}
      limit={50}
      value={value || null}
      onValueChange={(v: string | null) => onChange(v ?? "")}
    >
      <ComboboxInput
        id="trigger-package"
        placeholder="Search installed packages"
      />
      <ComboboxContent>
        <ComboboxEmpty>No installed package matches.</ComboboxEmpty>
        <ComboboxList>
          {(name: string) => (
            <ComboboxItem key={name} value={name}>
              {name}
            </ComboboxItem>
          )}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  )
}
