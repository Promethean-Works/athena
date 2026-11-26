"use client"

import * as React from "react"

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
import { Skeleton } from "@workspace/ui/components/skeleton"
import { Spinner } from "@workspace/ui/components/spinner"
import { Switch } from "@workspace/ui/components/switch"
import { Textarea } from "@workspace/ui/components/textarea"
import { toast } from "@workspace/ui/components/toast"
import {
  BoxIcon,
  CloudIcon,
  DatabaseIcon,
  HardDriveIcon,
  LinkIcon,
  MailIcon,
  Share2Icon,
} from "lucide-react"
import { useTranslation } from "react-i18next"

type Provider = Schemas["Provider"]
type Option = Schemas["ProviderOption"]
type Question = Schemas["ConfigQuestion"]
type Step = Schemas["ConfigStep"]

/** `null` closes the dialog; `{name: null}` adds a remote. */
export type RemoteEditing = { name: string | null } | null

/** The wizard's first step. */
type WizardPhase = "provider" | "settings"

/** rclone's help starts with a short summary line, then details after a blank line. */
function firstParagraph(help: string): string {
  return help.split("\n\n")[0]!.trim()
}

const ACRONYMS = new Set([
  "id",
  "url",
  "api",
  "sse",
  "kms",
  "acl",
  "uri",
  "ssl",
  "tls",
])

/** "client_id" → "Client ID": rclone names options for config files, not people. */
export function optionLabel(name: string): string {
  const words = name
    .split("_")
    .map((w) => (ACRONYMS.has(w) ? w.toUpperCase() : w))
  const first = words[0] ?? ""
  words[0] = first.charAt(0).toUpperCase() + first.slice(1)
  return words.join(" ")
}

/** Pick a lucide icon for a storage backend, falling back to a generic cloud. */
function ProviderIcon({ provider }: { provider: Provider }) {
  const key = (provider.name + " " + provider.description).toLowerCase()
  let Icon = CloudIcon
  if (
    key.includes("drive") ||
    key.includes("google") ||
    key.includes("onedrive")
  ) {
    Icon = CloudIcon
  } else if (key.includes("dropbox") || key.includes("box")) {
    Icon = BoxIcon
  } else if (
    key.includes("s3") ||
    key.includes("blob") ||
    key.includes("azure")
  ) {
    Icon = DatabaseIcon
  } else if (key.includes("webdav") || key.includes("http")) {
    Icon = LinkIcon
  } else if (key.includes("ftp") || key.includes("sftp")) {
    Icon = Share2Icon
  } else if (key.includes("mail") || key.includes("imap")) {
    Icon = MailIcon
  } else if (key.includes("disk") || key.includes("local")) {
    Icon = HardDriveIcon
  }
  return (
    <div className="flex size-10 items-center justify-center rounded-lg border bg-secondary/10 text-primary">
      <Icon size={20} />
    </div>
  )
}

/** One storage backend in the provider catalog, like a store app tile. */
function ProviderCard({
  provider,
  onSelect,
}: {
  provider: Provider
  onSelect: (provider: Provider) => void
}) {
  const { t } = useTranslation("cloud")
  return (
    <button
      onClick={() => onSelect(provider)}
      className="rounded-xl border transition-colors hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
    >
      <div className="flex flex-col items-start gap-3 p-4">
        <ProviderIcon provider={provider} />
        <div className="w-full">
          <p className="font-medium">{provider.description}</p>
          <p className="truncate text-xs text-muted-foreground">
            {provider.name}
          </p>
          <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">
            {t("remote.settingCount", { count: provider.options.length })}
          </p>
        </div>
      </div>
    </button>
  )
}

/** For backends with sub-providers (S3): does `option` apply to this one? */
function appliesTo(option: Option, provider: string | undefined): boolean {
  if (!option.provider) return true
  const list = option.provider.replace(/^!/, "").split(",")
  const listed = provider !== undefined && list.includes(provider)
  return option.provider.startsWith("!") ? !listed : listed
}

/** One rclone setting as a form field: a choice, a yes/no, a password or text. */
function OptionField({
  option,
  value,
  onChange,
  secretSet,
  error,
}: {
  option: Option
  value: string
  onChange: (value: string) => void
  /** Editing, and a value is stored but not shown. */
  secretSet?: boolean
  error?: string
}) {
  const { t } = useTranslation("cloud")
  const id = `opt-${option.name}`
  const examples = option.examples ?? []
  const label = (
    <FieldLabel htmlFor={id} title={option.name}>
      {optionLabel(option.name)}
      {option.required ? null : (
        <span className="font-normal text-muted-foreground">
          {t("remote.optional")}
        </span>
      )}
    </FieldLabel>
  )
  const description = option.help ? (
    <FieldDescription className="whitespace-pre-line">
      {firstParagraph(option.help)}
    </FieldDescription>
  ) : null

  if (option.type === "bool" && !examples.length) {
    const on = (value || option.default) === "true"
    return (
      <Field orientation="horizontal" data-invalid={error ? true : undefined}>
        <Switch
          id={id}
          checked={on}
          onCheckedChange={(c) => onChange(c ? "true" : "false")}
        />
        <div className="flex flex-col gap-1">
          {label}
          {description}
          {error ? <FieldError>{error}</FieldError> : null}
        </div>
      </Field>
    )
  }

  if (examples.length && (option.exclusive || option.type === "bool")) {
    const items = examples.map((e) => ({
      value: e.value,
      label: e.help ? `${e.help.split("\n")[0]} (${e.value})` : e.value,
    }))
    return (
      <Field data-invalid={error ? true : undefined}>
        {label}
        <Select
          items={items}
          value={value || option.default || null}
          onValueChange={(v) => onChange(v ?? "")}
        >
          <SelectTrigger id={id} className="w-full">
            <SelectValue placeholder={t("remote.choose")} />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {items.map((item) => (
                <SelectItem key={item.value} value={item.value}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        {description}
        {error ? <FieldError>{error}</FieldError> : null}
      </Field>
    )
  }

  const listId = examples.length ? `${id}-examples` : undefined
  return (
    <Field data-invalid={error ? true : undefined}>
      {label}
      <Input
        id={id}
        type={option.password ? "password" : "text"}
        autoComplete={option.password ? "new-password" : "off"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={
          secretSet ? t("remote.unchanged") : option.default ? option.default : undefined
        }
        list={listId}
        aria-invalid={error ? true : undefined}
      />
      {listId ? (
        <datalist id={listId}>
          {examples.map((e) => (
            <option key={e.value} value={e.value}>
              {e.help.split("\n")[0]}
            </option>
          ))}
        </datalist>
      ) : null}
      {description}
      {error ? <FieldError>{error}</FieldError> : null}
    </Field>
  )
}

/** One of rclone's follow-up questions (OAuth token, which drive, ...). */
function QuestionForm({
  question,
  refused,
  onAnswer,
  onCancel,
}: {
  question: Question
  /** Why rclone refused the last answer to this question. */
  refused: string
  onAnswer: (answer: string) => Promise<void>
  onCancel: () => void
}) {
  const { t } = useTranslation("cloud")
  const option = question.option
  const [value, setValue] = React.useState("")
  const [pending, setPending] = React.useState(false)
  React.useEffect(() => setValue(""), [question.state])
  const yesNo = option.type === "bool"
  const long = option.name === "config_token" || option.help.includes("paste")

  async function send(answer: string) {
    setPending(true)
    await onAnswer(answer)
    setPending(false)
  }

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault()
        void send(value || option.default)
      }}
    >
      <p className="rounded-lg border bg-muted/50 p-3 text-sm whitespace-pre-wrap">
        {option.help.trim()}
      </p>
      {refused || question.error ? (
        <FieldError className="whitespace-pre-wrap">
          {refused || question.error}
        </FieldError>
      ) : null}
      {yesNo ? null : option.examples?.length && option.exclusive ? (
        <OptionField option={option} value={value} onChange={setValue} />
      ) : long ? (
        <Field>
          <FieldLabel htmlFor="answer">
            {t("remote.pasteResult")}
          </FieldLabel>
          <Textarea
            id="answer"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="min-h-28 font-mono text-xs"
            required={option.required}
          />
        </Field>
      ) : (
        <OptionField option={option} value={value} onChange={setValue} />
      )}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel}>
          {t("cancel")}
        </Button>
        {yesNo ? (
          <>
            <Button
              type="button"
              variant="outline"
              disabled={pending}
              onClick={() => void send("false")}
            >
              {t("remote.no")}
            </Button>
            <Button
              type="button"
              disabled={pending}
              onClick={() => void send("true")}
            >
              {pending ? <Spinner data-icon="inline-start" /> : null}
              {t("remote.yes")}
            </Button>
          </>
        ) : (
          <Button type="submit" disabled={pending}>
            {pending ? <Spinner data-icon="inline-start" /> : null}
            {t("remote.continue")}
          </Button>
        )}
      </DialogFooter>
    </form>
  )
}

/**
 * Add or edit a cloud remote as a wizard:
 * 1. Pick a storage provider from a catalog (add only).
 * 2. Fill in the connection name and settings.
 * rclone may then ask follow-up questions, answered one at a time.
 */
export function RemoteDialog({
  editing,
  onClose,
  onSaved,
}: {
  editing: RemoteEditing
  onClose: () => void
  onSaved: () => void
}) {
  const { t } = useTranslation("cloud")
  const [providers, setProviders] = React.useState<Provider[] | null>(null)
  const [detail, setDetail] = React.useState<Schemas["RemoteDetail"] | null>(
    null
  )
  const [name, setName] = React.useState("")
  const [type, setType] = React.useState<string | null>(null)
  const [values, setValues] = React.useState<Record<string, string>>({})
  const [advanced, setAdvanced] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [pending, setPending] = React.useState(false)
  const [configStep, setConfigStep] = React.useState<Step | null>(null)
  const [refused, setRefused] = React.useState("")
  const [phase, setPhase] = React.useState<WizardPhase>("provider")
  const isNew = editing?.name === null

  React.useEffect(() => {
    if (!editing) return
    setError(null)
    setConfigStep(null)
    setRefused("")
    setAdvanced(false)
    setDetail(null)
    setName(editing.name ?? "")
    setType(null)
    setValues({})
    setPhase(isNew ? "provider" : "settings")
    void api.GET("/api/cloud/providers").then(({ data, error }) => {
      if (data) setProviders(data)
      else setError(errorMessage(error))
    })
    if (editing.name !== null) {
      void api
        .GET("/api/cloud/remotes/{name}", {
          params: { path: { name: editing.name } },
        })
        .then(({ data, error }) => {
          if (!data) {
            setError(errorMessage(error))
            return
          }
          setDetail(data)
          setType(data.type)
          setValues(data.values)
        })
    }
  }, [editing, isNew])

  const provider = providers?.find((p) => p.name === type)
  const subProvider = values.provider
  const options = (provider?.options ?? []).filter((o) =>
    appliesTo(o, subProvider)
  )
  const basic = options.filter((o) => !o.advanced)
  const extra = options.filter((o) => o.advanced)
  const secrets = new Set(detail?.secrets ?? [])
  const remoteName = isNew ? name.trim() : (editing?.name ?? "")

  async function handle(result: {
    data?: Step
    error?: unknown
  }): Promise<void> {
    if (!result.data) {
      setError(errorMessage(result.error))
      return
    }
    setError(null)
    setRefused(result.data.error ?? "")
    if (!result.data.done && !result.data.question) {
      // Refused: keep asking the same question.
      if (!configStep) setError(result.data.error || t("remote.refused"))
      return
    }
    if (result.data.done) {
      toast.add({
        type: "success",
        title: isNew
          ? t("remote.added", { name: result.data.remote })
          : t("remote.saved", { name: result.data.remote }),
      })
      setConfigStep(null)
      onSaved()
      onClose()
    } else setConfigStep(result.data)
  }

  async function selectProvider(provider: Provider) {
    setType(provider.name)
    setValues({})
    setError(null)
    setPhase("settings")
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!type) return
    setPending(true)
    // Only send what was filled in or changed; rclone keeps its defaults.
    const parameters = Object.fromEntries(
      Object.entries(values).filter(
        ([k, v]) => v !== (detail?.values[k] ?? "") || (isNew && v !== "")
      )
    )
    const result = isNew
      ? await api.POST("/api/cloud/remotes", {
          body: { name: remoteName, type, parameters },
        })
      : await api.PUT("/api/cloud/remotes/{name}", {
          params: { path: { name: remoteName } },
          body: { parameters },
        })
    setPending(false)
    if (isNew && result.data) onSaved()
    await handle(result)
  }

  async function answer(value: string) {
    if (!configStep?.question) return
    await handle(
      await api.POST("/api/cloud/remotes/{name}/answer", {
        params: { path: { name: configStep.remote } },
        body: { state: configStep.question.state, answer: value },
      })
    )
  }

  async function cancel() {
    // A new remote that stopped halfway isn't usable: forget it.
    if (isNew && configStep) {
      await api.DELETE("/api/cloud/remotes/{name}", {
        params: { path: { name: configStep.remote } },
      })
      onSaved()
    }
    onClose()
  }

  const providerItems = providers ?? []
  const loading = providers === null || (!isNew && detail === null)

  // rclone follow-up question takes over the whole dialog.
  if (configStep?.question) {
    return (
      <Dialog
        open={editing !== null}
        onOpenChange={(open) => !open && void cancel()}
      >
        <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>
              {isNew
                ? t("remote.addTitle")
                : t("remote.editTitle", { name: editing?.name ?? "" })}
            </DialogTitle>
            <DialogDescription>
              {t("remote.oneMoreAnswer")}
            </DialogDescription>
          </DialogHeader>
          <QuestionForm
            question={configStep.question}
            refused={refused}
            onAnswer={answer}
            onCancel={() => void cancel()}
          />
        </DialogContent>
      </Dialog>
    )
  }

  return (
    <Dialog
      open={editing !== null}
      onOpenChange={(open) => !open && void cancel()}
    >
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>
            {isNew
              ? t("remote.addTitle")
              : t("remote.editTitle", { name: editing?.name ?? "" })}
          </DialogTitle>
          <DialogDescription>
            {loading
              ? t("remote.loading")
              : phase === "provider"
                ? t("remote.pickKind")
                : provider
                  ? provider.description
                  : t("remote.genericDescription")}
          </DialogDescription>
        </DialogHeader>
        {loading || error ? (
          error ? (
            <FieldError>{error}</FieldError>
          ) : (
            <Skeleton className="h-48 w-full" />
          )
        ) : phase === "provider" ? (
          <ProviderCatalog
            providers={providerItems}
            onSelect={selectProvider}
          />
        ) : (
          <SettingsForm
            isNew={isNew}
            name={name}
            setName={setName}
            provider={provider!}
            values={values}
            setValues={setValues}
            basic={basic}
            extra={extra}
            advanced={advanced}
            setAdvanced={setAdvanced}
            secrets={secrets}
            error={error}
            onSubmit={submit}
          />
        )}
        <DialogFooter>
          {phase === "settings" && (
            <Button
              type="button"
              variant="outline"
              onClick={() => setPhase("provider")}
            >
              {t("remote.back")}
            </Button>
          )}
          <Button type="button" variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          {phase === "provider" ? null : (
            <Button type="submit" disabled={pending || !type || !remoteName}>
              {pending ? <Spinner data-icon="inline-start" /> : null}
              {isNew ? t("remote.add") : t("remote.save")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ProviderCatalog({
  providers,
  onSelect,
}: {
  providers: Provider[]
  onSelect: (provider: Provider) => void
}) {
  const { t } = useTranslation("cloud")
  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        {t("remote.catalogHint")}
      </p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {providers.map((provider) => (
          <ProviderCard
            key={provider.name}
            provider={provider}
            onSelect={onSelect}
          />
        ))}
      </div>
    </div>
  )
}

function SettingsForm({
  isNew,
  name,
  setName,
  provider,
  values,
  setValues,
  basic,
  extra,
  advanced,
  setAdvanced,
  secrets,
  error,
  onSubmit,
}: {
  isNew: boolean
  name: string
  setName: (value: string) => void
  provider: Provider
  values: Record<string, string>
  setValues: React.Dispatch<React.SetStateAction<Record<string, string>>>
  basic: Option[]
  extra: Option[]
  advanced: boolean
  setAdvanced: (checked: boolean) => void
  secrets: Set<string>
  error: string | null
  onSubmit: (event: React.FormEvent) => void
}) {
  const { t } = useTranslation("cloud")
  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <FieldGroup>
        {isNew ? (
          <>
            <Field>
              <FieldLabel htmlFor="remote-name">{t("remote.name")}</FieldLabel>
              <Input
                id="remote-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="gdrive"
                required
                autoComplete="off"
              />
              <FieldDescription>
                {t("remote.nameHint")}
              </FieldDescription>
            </Field>
            <Field>
              <FieldLabel htmlFor="remote-type">{t("remote.storage")}</FieldLabel>
              <p className="text-sm text-muted-foreground">
                {provider.description}
              </p>
            </Field>
          </>
        ) : null}
        {basic.map((option) => (
          <OptionField
            key={option.name}
            option={option}
            value={values[option.name] ?? ""}
            secretSet={secrets.has(option.name)}
            onChange={(v) => setValues((s) => ({ ...s, [option.name]: v }))}
          />
        ))}
        {extra.length ? (
          <Field orientation="horizontal">
            <Switch
              id="show-advanced"
              checked={advanced}
              onCheckedChange={setAdvanced}
            />
            <FieldLabel htmlFor="show-advanced">
              {t("remote.advanced", { count: extra.length })}
            </FieldLabel>
          </Field>
        ) : null}
        {advanced
          ? extra.map((option) => (
              <OptionField
                key={option.name}
                option={option}
                value={values[option.name] ?? ""}
                secretSet={secrets.has(option.name)}
                onChange={(v) => setValues((s) => ({ ...s, [option.name]: v }))}
              />
            ))
          : null}
        {error ? <FieldError>{error}</FieldError> : null}
      </FieldGroup>
    </form>
  )
}
