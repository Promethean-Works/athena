"use client"

import * as React from "react"
import { CheckIcon, PlusIcon } from "lucide-react"
import type { ParseKeys } from "i18next"
import { useTranslation } from "react-i18next"

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

/** `labelKey` is translated when shown, never at module load. */
const APP_VERBS: { value: AppVerb; labelKey: ParseKeys<"automation"> }[] = [
  { value: "start", labelKey: "dialog.appVerbs.start" },
  { value: "stop", labelKey: "dialog.appVerbs.stop" },
  { value: "restart", labelKey: "dialog.appVerbs.restart" },
  { value: "update", labelKey: "dialog.appVerbs.update" },
]

const PACKAGE_VERBS: {
  value: PackageVerb
  labelKey: ParseKeys<"automation">
}[] = [
  { value: "install", labelKey: "dialog.packageVerbs.install" },
  { value: "uninstall", labelKey: "dialog.packageVerbs.uninstall" },
  { value: "upgrade", labelKey: "dialog.packageVerbs.upgrade" },
  { value: "refresh", labelKey: "dialog.packageVerbs.refresh" },
]

/** "New trigger" button and dialog. Calls `onCreated` so the list reloads. */
export function NewTriggerDialog({
  onCreated,
}: {
  onCreated: () => Promise<void>
}) {
  const { t } = useTranslation("automation")
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
        <PlusIcon /> {t("dialog.new")}
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
  const { t } = useTranslation("automation")
  return (
    <>
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <CheckIcon className="size-4" /> {t("dialog.created.title")}
        </DialogTitle>
        <DialogDescription>
          {t("dialog.created.description", { name: trigger.name })}
        </DialogDescription>
      </DialogHeader>
      <Field>
        <FieldLabel htmlFor="new-webhook-url">
          {t("external.webhookUrl")}
        </FieldLabel>
        <CopyUrl
          id="new-webhook-url"
          label={t("external.webhookUrl")}
          value={webhookUrl(trigger.webhook_token ?? "")}
        />
      </Field>
      <DialogFooter>
        <DialogClose render={<Button />}>
          {t("dialog.created.done")}
        </DialogClose>
      </DialogFooter>
    </>
  )
}

function NewTriggerForm({
  onCreated,
}: {
  onCreated: (trigger: Trigger) => Promise<void>
}) {
  const { t } = useTranslation("automation")
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
    name: name.trim() ? null : t("dialog.errors.name"),
    cron: kind === "cron" && !cronCheck.ok ? cronCheck.error : null,
    app: actionKind === "app" && !appName ? t("dialog.errors.app") : null,
    manager:
      actionKind === "package" && !manager
        ? t("dialog.errors.manager")
        : null,
    packageName:
      actionKind === "package" && needsPackageName && !packageName.trim()
        ? t("dialog.errors.packageName")
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
      toast.add({ type: "success", title: t("dialog.createdToast", { name: data.name }) })
      await onCreated(data)
    } else {
      setServerError(errorMessage(error, t("dialog.createFailed")))
    }
    setSubmitting(false)
  }

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-6">
      <DialogHeader>
        <DialogTitle>{t("dialog.new")}</DialogTitle>
        <DialogDescription>
          {t("dialog.description")}
        </DialogDescription>
      </DialogHeader>

      <FieldGroup>
        <Field data-invalid={!!show(errors.name)}>
          <FieldLabel htmlFor="trigger-name">{t("dialog.name")}</FieldLabel>
          <Input
            id="trigger-name"
            placeholder={t("dialog.namePlaceholder")}
            maxLength={64}
            value={name}
            aria-invalid={!!show(errors.name)}
            onChange={(e) => setName(e.target.value)}
          />
          <FieldError>{show(errors.name)}</FieldError>
        </Field>

        <FieldSet>
          <FieldLegend variant="label">{t("dialog.whenItRuns")}</FieldLegend>
          <RadioGroup
            value={kind}
            onValueChange={(v) => setKind(v as "cron" | "http")}
            className="sm:grid-cols-2"
          >
            <Field orientation="horizontal">
              <RadioGroupItem value="cron" id="trigger-kind-cron" />
              <FieldLabel htmlFor="trigger-kind-cron" className="font-normal">
                {t("dialog.onSchedule")}
              </FieldLabel>
            </Field>
            <Field orientation="horizontal">
              <RadioGroupItem value="http" id="trigger-kind-http" />
              <FieldLabel htmlFor="trigger-kind-http" className="font-normal">
                {t("dialog.onWebhook")}
              </FieldLabel>
            </Field>
          </RadioGroup>
        </FieldSet>

        {kind === "cron" ? (
          <Field data-invalid={!!show(errors.cron)}>
            <FieldLabel htmlFor="trigger-cron">{t("dialog.schedule")}</FieldLabel>
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
                  {t(preset.labelKey)}
                </Button>
              ))}
            </div>
            <Input
              id="trigger-cron"
              placeholder={t("dialog.cronPlaceholder")}
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
                : t("dialog.cronHelp")}
            </FieldDescription>
          </Field>
        ) : (
          <FieldDescription>
            {t("dialog.webhookHint")}
          </FieldDescription>
        )}

        <FieldSeparator />

        <FieldSet>
          <FieldLegend variant="label">{t("dialog.whatItDoes")}</FieldLegend>
          <RadioGroup
            value={actionKind}
            onValueChange={(v) => setActionKind(v as "app" | "package")}
            className="sm:grid-cols-2"
          >
            <Field orientation="horizontal">
              <RadioGroupItem value="app" id="trigger-action-app" />
              <FieldLabel htmlFor="trigger-action-app" className="font-normal">
                {t("dialog.appAction")}
              </FieldLabel>
            </Field>
            <Field orientation="horizontal">
              <RadioGroupItem value="package" id="trigger-action-package" />
              <FieldLabel
                htmlFor="trigger-action-package"
                className="font-normal"
              >
                {t("dialog.packageAction")}
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
          {t("cancel")}
        </DialogClose>
        <Button type="submit" disabled={submitting}>
          {submitting ? <Spinner /> : null} {t("dialog.create")}
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
  const { t } = useTranslation("automation")
  const { apps, error: listError } = useAppsList()
  const verbItems = APP_VERBS.map((v) => ({
    value: v.value,
    label: t(v.labelKey),
  }))
  const items = (apps ?? []).map((a) => ({
    value: a.name,
    label: a.title ?? a.name,
  }))

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field data-invalid={!!(error || listError)}>
        <FieldLabel htmlFor="trigger-app">{t("dialog.app")}</FieldLabel>
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
                  ? t("dialog.loadingApps")
                  : apps.length
                    ? t("dialog.chooseApp")
                    : t("dialog.noApps")
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
        <FieldLabel htmlFor="trigger-app-verb">{t("dialog.action")}</FieldLabel>
        <Select
          items={verbItems}
          value={appVerb}
          onValueChange={(v) => v && setAppVerb(v as AppVerb)}
        >
          <SelectTrigger id="trigger-app-verb" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {verbItems.map((v) => (
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
  const { t } = useTranslation("automation")
  const managers = useApi<Manager[]>(() => api.GET("/api/packages"))
  const ready = React.useMemo(
    () =>
      managers.status === "ok" ? managers.data.filter((m) => m.available) : [],
    [managers]
  )
  const items = ready.map((m) => ({ value: m.id, label: m.label }))
  const current = ready.find((m) => m.id === manager)
  const verbs = PACKAGE_VERBS.filter(
    (v) => v.value !== "refresh" || current?.can_refresh !== false
  ).map((v) => ({ value: v.value, label: t(v.labelKey) }))

  // Pick the first ready manager once the list arrives.
  React.useEffect(() => {
    if (manager === null && ready[0]) setManager(ready[0].id)
  }, [manager, ready, setManager])

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field data-invalid={!!errors.manager || managers.status === "error"}>
        <FieldLabel htmlFor="trigger-manager">
          {t("dialog.packageManager")}
        </FieldLabel>
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
                  ? t("dialog.loading")
                  : ready.length
                    ? t("dialog.chooseManager")
                    : t("dialog.noManagers")
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
        <FieldLabel htmlFor="trigger-package-verb">
          {t("dialog.action")}
        </FieldLabel>
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
            <FieldLabel htmlFor="trigger-package">
              {t("dialog.package")}
            </FieldLabel>
            {verb === "install" ? (
              <Input
                id="trigger-package"
                placeholder={t("dialog.packagePlaceholder")}
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
                {t("dialog.source")}
              </FieldLabel>
              <Input
                id="trigger-source"
                value={source}
                onChange={(e) => setSource(e.target.value)}
              />
              <FieldDescription>
                {t("dialog.sourceHint")}
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
  const { t } = useTranslation("automation")
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
              ? t("dialog.loadingInstalled")
              : t("dialog.packagePlaceholder")
          }
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
        {installed.status === "error" ? (
          <FieldDescription>
            {t("dialog.installedFailed", { error: installed.error })}
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
        placeholder={t("dialog.searchInstalled")}
      />
      <ComboboxContent>
        <ComboboxEmpty>{t("dialog.noMatch")}</ComboboxEmpty>
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
