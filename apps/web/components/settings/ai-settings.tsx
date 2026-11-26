"use client"

import * as React from "react"
import type { ParseKeys } from "i18next"
import { Trans, useTranslation } from "react-i18next"
import {
  CloudIcon,
  CpuIcon,
  PencilIcon,
  PlugZapIcon,
  PlusIcon,
  Trash2Icon,
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
import { Button } from "@workspace/ui/components/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
import {
  Combobox,
  ComboboxCollection,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxGroup,
  ComboboxInput,
  ComboboxItem,
  ComboboxLabel,
  ComboboxList,
  ComboboxTrigger,
} from "@workspace/ui/components/combobox"
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
  FieldGroup,
  FieldLabel,
  FieldSeparator,
} from "@workspace/ui/components/field"
import { Input } from "@workspace/ui/components/input"
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemTitle,
} from "@workspace/ui/components/item"
import { Skeleton } from "@workspace/ui/components/skeleton"
import { Spinner } from "@workspace/ui/components/spinner"
import { Switch } from "@workspace/ui/components/switch"
import { Textarea } from "@workspace/ui/components/textarea"
import { toast } from "@workspace/ui/components/toast"

import { ModelPicker } from "@/components/assistant/model-picker"
import { useModels, type ModelRef } from "@/components/assistant/use-models"
import { useAuth } from "@/components/auth-provider"
import { useCapability } from "@/components/capabilities-provider"
import { IntegrationDialog } from "@/components/settings/ai-integration-dialog"
import {
  ProviderDialog,
  type Provider,
  type ProviderEditing,
  type ProviderKind,
} from "@/components/settings/ai-provider-dialog"
import {
  editingFor,
  LocalServerButtons,
  localServersSentence,
  useLocalAiServers,
} from "@/components/settings/local-ai-servers"

type AiSettings = Schemas["AiSettings"]
type Integration = Schemas["IntegrationOut"]
type IntegrationKind = Schemas["IntegrationKindOut"]

type KindGroup = { value: string; items: ProviderKind[] }

/**
 * A searchable "Add provider" picker: models.dev lists dozens of providers, too many
 * for a plain menu.
 */
export function AddMenu({
  kinds,
  onPick,
  label,
}: {
  kinds: ProviderKind[]
  onPick: (kind: ProviderKind) => void
  label?: string
}) {
  const { t } = useTranslation("ai")
  const groups = React.useMemo<KindGroup[]>(() => {
    const byLabel = (a: ProviderKind, b: ProviderKind) =>
      a.label.localeCompare(b.label)
    return [
      {
        value: "cloud",
        items: kinds.filter((k) => k.group === "cloud").sort(byLabel),
      },
      {
        value: "local",
        items: kinds.filter((k) => k.group === "local").sort(byLabel),
      },
      // Custom endpoints stay last, in the server's order.
      { value: "custom", items: kinds.filter((k) => k.group === "custom") },
    ].filter((g) => g.items.length > 0)
  }, [kinds])
  const groupLabels: Record<string, string> = {
    cloud: t("addMenu.groupCloud"),
    local: t("addMenu.groupLocal"),
    custom: t("addMenu.groupCustom"),
  }
  return (
    <Combobox
      items={groups}
      value={null}
      onValueChange={(k: ProviderKind | null) => {
        if (k) onPick(k)
      }}
      itemToStringLabel={(k: ProviderKind) => k.label}
      itemToStringValue={(k: ProviderKind) => k.id}
    >
      <ComboboxTrigger render={<Button variant="outline" size="sm" />}>
        <PlusIcon />
        {label ?? t("addMenu.addProvider")}
      </ComboboxTrigger>
      <ComboboxContent className="w-64 max-w-[calc(100vw-2rem)]" align="end">
        <ComboboxInput showTrigger={false} placeholder={t("addMenu.search")} />
        <ComboboxEmpty>{t("addMenu.noMatch")}</ComboboxEmpty>
        <ComboboxList>
          {(group: KindGroup) => (
            <ComboboxGroup key={group.value} items={group.items}>
              <ComboboxLabel>{groupLabels[group.value]}</ComboboxLabel>
              <ComboboxCollection>
                {(k: ProviderKind) => (
                  <ComboboxItem key={k.id} value={k}>
                    {k.label}
                  </ComboboxItem>
                )}
              </ComboboxCollection>
            </ComboboxGroup>
          )}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  )
}

function ProvidersCard({ onChanged }: { onChanged: () => void }) {
  const { t } = useTranslation("ai")
  const [kinds, setKinds] = React.useState<ProviderKind[]>([])
  const [providers, setProviders] = React.useState<Provider[] | null>(null)
  const [editing, setEditing] = React.useState<ProviderEditing>(null)
  const [removing, setRemoving] = React.useState<Provider | null>(null)
  const [testing, setTesting] = React.useState<string | null>(null)

  const load = React.useCallback(async () => {
    const { data } = await api.GET("/api/assistant/providers")
    setProviders(data ?? [])
  }, [])

  React.useEffect(() => {
    void api
      .GET("/api/assistant/kinds")
      .then(({ data }) => setKinds(data ?? []))
    void load()
  }, [load])

  const kindOf = (id: string) => kinds.find((k) => k.id === id)
  const local = useLocalAiServers(kinds)

  async function test(p: Provider) {
    setTesting(p.id)
    const { data, error } = await api.POST(
      "/api/assistant/providers/{provider_id}/test",
      {
        params: { path: { provider_id: p.id } },
      }
    )
    setTesting(null)
    if (data?.ok)
      toast.add({ type: "success", title: p.name, description: data.message })
    else
      toast.add({
        type: "error",
        title: t("providers.didntConnect", { name: p.name }),
        description: data?.message ?? errorMessage(error),
      })
  }

  async function remove(p: Provider) {
    setRemoving(null)
    const { error } = await api.DELETE(
      "/api/assistant/providers/{provider_id}",
      {
        params: { path: { provider_id: p.id } },
      }
    )
    if (error) {
      toast.add({
        type: "error",
        title: t("providers.couldntRemove"),
        description: errorMessage(error),
      })
      return
    }
    await load()
    onChanged()
  }

  async function saved(p: Provider) {
    const added = !editing?.provider
    setEditing(null)
    await load()
    onChanged()
    if (added) void test(p)
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("providers.title")}</CardTitle>
        <CardDescription>{t("providers.description")}</CardDescription>
        {providers?.length ? (
          <CardAction>
            <AddMenu kinds={kinds} onPick={(kind) => setEditing({ kind })} />
          </CardAction>
        ) : null}
      </CardHeader>
      <CardContent>
        {providers === null ? (
          <Skeleton className="h-16 w-full" />
        ) : providers.length === 0 ? (
          <Empty className="border">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                {local.length ? <CpuIcon /> : <CloudIcon />}
              </EmptyMedia>
              <EmptyTitle>{t("providers.emptyTitle")}</EmptyTitle>
              <EmptyDescription>
                {local.length
                  ? localServersSentence(local)
                  : t("providers.emptyDescription")}
              </EmptyDescription>
            </EmptyHeader>
            <EmptyContent className="flex-row flex-wrap justify-center">
              <LocalServerButtons
                servers={local}
                onUse={(server) => setEditing(editingFor(server))}
              />
              <AddMenu
                kinds={kinds}
                onPick={(kind) => setEditing({ kind })}
                label={local.length ? t("anotherProvider") : t("addAProvider")}
              />
            </EmptyContent>
          </Empty>
        ) : (
          <ItemGroup className="gap-2">
            {providers.map((p) => (
              <Item key={p.id} variant="outline" size="sm">
                <ItemContent>
                  <ItemTitle>{p.name}</ItemTitle>
                  <ItemDescription>
                    {kindOf(p.kind)?.label ?? p.kind}
                    {p.values.base_url ? ` · ${p.values.base_url}` : ""}
                  </ItemDescription>
                </ItemContent>
                <ItemActions>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void test(p)}
                    disabled={testing === p.id}
                  >
                    {testing === p.id ? <Spinner /> : <PlugZapIcon />}
                    {t("providers.test")}
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={t("providers.editAria", { name: p.name })}
                    onClick={() => {
                      const kind = kindOf(p.kind)
                      if (kind) setEditing({ kind, provider: p })
                    }}
                  >
                    <PencilIcon />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={t("providers.removeAria", { name: p.name })}
                    onClick={() => setRemoving(p)}
                  >
                    <Trash2Icon />
                  </Button>
                </ItemActions>
              </Item>
            ))}
          </ItemGroup>
        )}
      </CardContent>
      <ProviderDialog
        editing={editing}
        onClose={() => setEditing(null)}
        onSaved={saved}
      />
      <AlertDialog
        open={removing !== null}
        onOpenChange={(o) => !o && setRemoving(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("providers.removeTitle", { name: removing?.name })}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t("providers.removeDescription")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => removing && void remove(removing)}
            >
              {t("remove")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}

type SaveAi = (next: AiSettings, message: string) => Promise<void>

/**
 * The AI settings row, shared by the cards so one card's save never undoes another's.
 * Reloaded when providers change (removing one can clear the default model).
 */
function useAiSettings(version: number) {
  const { t } = useTranslation("ai")
  const [settings, setSettings] = React.useState<AiSettings | null>(null)

  React.useEffect(() => {
    void api.GET("/api/settings/ai").then(({ data }) => {
      if (data) setSettings(data)
    })
  }, [version])

  const save = React.useCallback<SaveAi>(
    async (next, message) => {
      const previous = settings
      setSettings(next)
      const { data, error } = await api.PUT("/api/settings/ai", { body: next })
      if (data) {
        setSettings(data)
        toast.add({ type: "success", title: message })
      } else {
        setSettings(previous)
        toast.add({
          type: "error",
          title: t("saveFailed"),
          description: errorMessage(error),
        })
      }
    },
    [settings, t]
  )
  return { settings, save }
}

function DefaultsCard({
  version,
  settings,
  save,
}: {
  version: number
  settings: AiSettings | null
  save: SaveAi
}) {
  const { t } = useTranslation("ai")
  const { providers, reload } = useModels()
  const [limit, setLimit] = React.useState("")
  const savedLimit = settings?.spend_limit_usd

  React.useEffect(() => {
    setLimit(savedLimit ? String(savedLimit) : "")
  }, [savedLimit])

  React.useEffect(() => {
    if (version > 0) void reload()
  }, [version, reload])

  function saveLimit() {
    if (!settings) return
    const value = limit.trim() === "" ? null : Number(limit)
    if (value !== null && (!Number.isFinite(value) || value <= 0)) {
      toast.add({
        type: "error",
        title: t("defaults.limitInvalid"),
      })
      return
    }
    if (value === (settings.spend_limit_usd ?? null)) return
    void save(
      { ...settings, spend_limit_usd: value },
      value ? t("defaults.limitSet", { value }) : t("defaults.limitNone")
    )
  }

  if (!providers?.length && settings !== null) return null

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("defaults.title")}</CardTitle>
        <CardDescription>{t("defaults.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {settings === null ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="default-model">
                {t("defaults.defaultModel")}
              </FieldLabel>
              <ModelPicker
                id="default-model"
                variant="field"
                providers={providers}
                value={settings.default_model}
                onChange={(ref: ModelRef) =>
                  void save(
                    { ...settings, default_model: ref },
                    t("defaults.defaultModelSaved")
                  )
                }
              />
              <FieldDescription>
                {t("defaults.defaultModelHelp")}
              </FieldDescription>
            </Field>
            <Field>
              <FieldLabel htmlFor="title-model">
                {t("defaults.titleModel")}
              </FieldLabel>
              <ModelPicker
                id="title-model"
                variant="field"
                providers={providers}
                value={settings.title_model}
                onChange={(ref: ModelRef) =>
                  void save(
                    { ...settings, title_model: ref },
                    t("defaults.titleModelSaved")
                  )
                }
              />
              <FieldDescription>
                {t("defaults.titleModelHelp")}
              </FieldDescription>
            </Field>
            <Field>
              <FieldLabel htmlFor="advisor-model">
                {t("defaults.advisorModel")}
              </FieldLabel>
              <div className="flex gap-2">
                <ModelPicker
                  id="advisor-model"
                  variant="field"
                  className="flex-1"
                  providers={providers}
                  value={settings.advisor_model}
                  onChange={(ref: ModelRef) =>
                    void save(
                      { ...settings, advisor_model: ref },
                      t("defaults.advisorModelSaved")
                    )
                  }
                />
                {settings.advisor_model && (
                  <Button
                    variant="outline"
                    onClick={() =>
                      void save(
                        { ...settings, advisor_model: null },
                        t("defaults.advisorTurnedOff")
                      )
                    }
                  >
                    {t("defaults.advisorOff")}
                  </Button>
                )}
              </div>
              <FieldDescription>{t("defaults.advisorHelp")}</FieldDescription>
            </Field>
            <Field orientation="horizontal">
              <FieldContent>
                <FieldLabel htmlFor="refine-answers">
                  {t("defaults.refine")}
                </FieldLabel>
                <FieldDescription>{t("defaults.refineHelp")}</FieldDescription>
              </FieldContent>
              <Switch
                id="refine-answers"
                checked={settings.refine_answers}
                onCheckedChange={(checked) =>
                  void save(
                    { ...settings, refine_answers: checked },
                    checked ? t("defaults.refineOn") : t("defaults.refineOff")
                  )
                }
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="spend-limit">
                {t("defaults.spendLimit")}
              </FieldLabel>
              <Input
                id="spend-limit"
                inputMode="decimal"
                value={limit}
                placeholder={t("defaults.spendLimitPlaceholder")}
                onChange={(e) => setLimit(e.target.value)}
                onBlur={saveLimit}
                onKeyDown={(e) => e.key === "Enter" && saveLimit()}
                className="max-w-40"
              />
              <FieldDescription>
                {t("defaults.spendLimitHelp")}
              </FieldDescription>
            </Field>
          </FieldGroup>
        )}
      </CardContent>
    </Card>
  )
}

/** Splits what the admin typed into program names: spaces, commas or new lines. */
function parseCommands(text: string): string[] {
  return [...new Set(text.split(/[\s,]+/).filter(Boolean))]
}

function ShellCard({
  settings,
  save,
}: {
  settings: AiSettings | null
  save: SaveAi
}) {
  const { t } = useTranslation("ai")
  const where = useCapability("assistant.shell")
  const [text, setText] = React.useState("")
  const saved = settings
    ? (settings.shell_commands ?? []).join("\n")
    : undefined

  React.useEffect(() => {
    if (saved !== undefined) setText(saved)
  }, [saved])

  function saveCommands() {
    if (!settings) return
    const commands = parseCommands(text)
    const bad = commands.find((c) => /[;&|<>()`$]/.test(c))
    if (bad) {
      toast.add({
        type: "error",
        title: t("shell.badName", { name: bad }),
        description: t("shell.badNameHelp"),
      })
      return
    }
    if (commands.join("\n") === saved) {
      setText(saved)
      return
    }
    void save(
      { ...settings, shell_commands: commands },
      commands.length ? t("shell.saved") : t("shell.emptied")
    )
  }

  if (where?.status !== "ready") return null

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("shell.title")}</CardTitle>
        <CardDescription>{t("shell.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {settings === null ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          <FieldGroup>
            <Field orientation="horizontal">
              <FieldContent>
                <FieldLabel htmlFor="shell-enabled">
                  {t("shell.enabled")}
                </FieldLabel>
                <FieldDescription>
                  {t("shell.enabledHelp")}
                  {where.detail && ` ${where.detail}.`}
                </FieldDescription>
              </FieldContent>
              <Switch
                id="shell-enabled"
                checked={settings.shell_enabled}
                onCheckedChange={(checked) =>
                  void save(
                    { ...settings, shell_enabled: checked },
                    checked ? t("shell.enabledOn") : t("shell.enabledOff")
                  )
                }
              />
            </Field>
            <Field data-disabled={!settings.shell_enabled || undefined}>
              <FieldLabel htmlFor="shell-commands">
                {t("shell.allowed")}
              </FieldLabel>
              <Textarea
                id="shell-commands"
                value={text}
                disabled={!settings.shell_enabled}
                onChange={(e) => setText(e.target.value)}
                onBlur={saveCommands}
                rows={6}
                spellCheck={false}
                // The shared Textarea grows with its content; a long allowlist
                // made the page scroll for a screen. Keep it at six lines.
                className="[field-sizing:fixed] max-h-48 font-mono"
              />
              <FieldDescription>
                <Trans
                  i18nKey="shell.allowedHelp"
                  ns="ai"
                  components={{
                    pipe: <code>|</code>,
                    and: <code>&amp;&amp;</code>,
                    semi: <code>;</code>,
                  }}
                />
              </FieldDescription>
            </Field>
          </FieldGroup>
        )}
      </CardContent>
    </Card>
  )
}

/** One on/off setting: label, a single description, and the switch. */
function ToggleRow({
  id,
  label,
  checked,
  disabled,
  onChange,
  children,
}: {
  id: string
  label: string
  checked: boolean
  disabled?: boolean
  onChange: (checked: boolean) => void
  children: React.ReactNode
}) {
  return (
    <Field orientation="horizontal" data-disabled={disabled || undefined}>
      <FieldContent>
        <FieldLabel htmlFor={id}>{label}</FieldLabel>
        <FieldDescription>{children}</FieldDescription>
      </FieldContent>
      <Switch
        id={id}
        checked={checked}
        disabled={disabled}
        onCheckedChange={onChange}
      />
    </Field>
  )
}

type ToggleKey =
  | "memory_enabled"
  | "web_research_enabled"
  | "docker_sandbox_enabled"
  | "durable_execution_enabled"
  | "coding_stack_enabled"
  | "browser_use_enabled"

function useToggle(settings: AiSettings | null, save: SaveAi) {
  const { t } = useTranslation("ai")
  return (key: ToggleKey, name: string) => (checked: boolean) => {
    if (!settings) return
    void save(
      { ...settings, [key]: checked },
      t(checked ? "toggle.on" : "toggle.off", { name })
    )
  }
}

/** Everyday tools the assistant can use. Each is one switch. */
function ToolsCard({
  settings,
  save,
}: {
  settings: AiSettings | null
  save: SaveAi
}) {
  const { t } = useTranslation("ai")
  const toggle = useToggle(settings, save)
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("tools.title")}</CardTitle>
        <CardDescription>{t("tools.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {settings === null ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          <FieldGroup>
            <ToggleRow
              id="memory-enabled"
              label={t("tools.memory")}
              checked={settings.memory_enabled}
              onChange={toggle("memory_enabled", t("tools.memoryName"))}
            >
              {t("tools.memoryHelp")}
            </ToggleRow>
            <ToggleRow
              id="web-research-enabled"
              label={t("tools.web")}
              checked={settings.web_research_enabled}
              onChange={toggle("web_research_enabled", t("tools.web"))}
            >
              <Trans
                i18nKey="tools.webHelp"
                ns="ai"
                components={{
                  exa: (
                    <a
                      href="https://exa.ai"
                      target="_blank"
                      rel="noopener noreferrer"
                    />
                  ),
                  code: <code />,
                }}
              />
            </ToggleRow>
            <FieldSeparator />
            <FieldDescription>
              <Trans
                i18nKey="tools.skills"
                ns="ai"
                components={{ code: <code /> }}
              />
            </FieldDescription>
          </FieldGroup>
        )}
      </CardContent>
    </Card>
  )
}

/** Opt-in features that need extra setup on the server. */
function AdvancedCard({
  settings,
  save,
}: {
  settings: AiSettings | null
  save: SaveAi
}) {
  const { t } = useTranslation("ai")
  const containers = useCapability("containers")
  const containersReady = containers?.status === "ready"
  const toggle = useToggle(settings, save)
  return (
    // The section heading above names it; a card title would repeat it.
    <Card>
      <CardContent>
        {settings === null ? (
          <Skeleton className="h-32 w-full" />
        ) : (
          <FieldGroup>
            <ToggleRow
              id="docker-sandbox-enabled"
              label={t("advanced.docker")}
              checked={settings.docker_sandbox_enabled}
              // Let an admin turn it off even when the engine went away.
              disabled={!containersReady && !settings.docker_sandbox_enabled}
              onChange={toggle("docker_sandbox_enabled", t("advanced.docker"))}
            >
              {t("advanced.dockerHelp")}
              {!containersReady &&
                ` ${t("advanced.dockerNeeds", {
                  engine:
                    containers?.label ?? t("advanced.dockerNeedsFallback"),
                })}`}
            </ToggleRow>
            <ToggleRow
              id="coding-stack-enabled"
              label={t("advanced.coding")}
              checked={settings.coding_stack_enabled}
              onChange={toggle("coding_stack_enabled", t("advanced.coding"))}
            >
              <Trans
                i18nKey="advanced.codingHelp"
                ns="ai"
                components={{ code: <code /> }}
              />
            </ToggleRow>
            <ToggleRow
              id="durable-execution-enabled"
              label={t("advanced.durable")}
              checked={settings.durable_execution_enabled}
              onChange={toggle(
                "durable_execution_enabled",
                t("advanced.durableName")
              )}
            >
              <Trans
                i18nKey="advanced.durableHelp"
                ns="ai"
                components={{ code: <code /> }}
              />
            </ToggleRow>
            {/* Hidden until it works (docs/plans/release-0.1.0.md §4): nothing
                provides the browser tool yet, so the switch only shows when an
                old setting left it on, to let you turn it off. */}
            {settings.browser_use_enabled && (
              <ToggleRow
                id="browser-use-enabled"
                label={t("advanced.browser")}
                checked
                onChange={toggle("browser_use_enabled", t("advanced.browser"))}
              >
                {t("advanced.browserHelp")}
              </ToggleRow>
            )}
          </FieldGroup>
        )}
      </CardContent>
    </Card>
  )
}

function ReviewCard({
  settings,
  save,
}: {
  settings: AiSettings | null
  save: SaveAi
}) {
  const { t } = useTranslation("ai")
  const { providers } = useModels()

  function saveModel(ref: ModelRef | null) {
    if (!settings || ref === settings.review_model) return
    void save(
      {
        ...settings,
        review_model: ref,
        // No model means nothing can review; keep the two in step.
        review_tool_calls: ref ? settings.review_tool_calls : false,
      },
      ref ? t("review.modelSaved") : t("review.modelOff")
    )
  }

  // Nothing to pick from until a provider exists; Providers above says so.
  if (!providers?.length && settings !== null) return null

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("review.title")}</CardTitle>
        <CardDescription>{t("review.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {settings === null ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="review-model">
                {t("review.model")}
              </FieldLabel>
              <div className="flex gap-2">
                <ModelPicker
                  id="review-model"
                  variant="field"
                  className="flex-1"
                  providers={providers}
                  value={settings.review_model}
                  onChange={saveModel}
                />
                {settings.review_model && (
                  <Button variant="outline" onClick={() => saveModel(null)}>
                    {t("review.clear")}
                  </Button>
                )}
              </div>
              <FieldDescription>{t("review.modelHelp")}</FieldDescription>
            </Field>
            <ToggleRow
              id="review-tool-calls"
              label={t("review.toggle")}
              checked={settings.review_tool_calls}
              disabled={!settings.review_model && !settings.review_tool_calls}
              onChange={(checked) =>
                void save(
                  { ...settings, review_tool_calls: checked },
                  checked ? t("review.toggleOn") : t("review.toggleOff")
                )
              }
            >
              {settings.review_model
                ? t("review.helpWithModel")
                : t("review.helpNoModel")}
            </ToggleRow>
          </FieldGroup>
        )}
      </CardContent>
    </Card>
  )
}

function IntegrationsCard() {
  const { t } = useTranslation("ai")
  const [kinds, setKinds] = React.useState<IntegrationKind[]>([])
  const [integrations, setIntegrations] = React.useState<Integration[] | null>(
    null
  )
  const [editing, setEditing] = React.useState<{
    integration: Integration | null
    kinds: IntegrationKind[]
  } | null>(null)
  const [removing, setRemoving] = React.useState<Integration | null>(null)
  const [version, setVersion] = React.useState(0)

  React.useEffect(() => {
    void (async () => {
      const [k, i] = await Promise.all([
        api.GET("/api/assistant/integrations/kinds"),
        api.GET("/api/assistant/integrations"),
      ])
      setKinds(k.data ?? [])
      setIntegrations(i.data ?? [])
    })()
  }, [version])

  async function remove(integration: Integration) {
    setRemoving(null)
    const { error } = await api.DELETE(
      "/api/assistant/integrations/{integration_id}",
      {
        params: { path: { integration_id: integration.id } },
      }
    )
    if (error) {
      toast.add({
        type: "error",
        title: t("providers.couldntRemove"),
        description: errorMessage(error),
      })
      return
    }
    setVersion((v) => v + 1)
  }

  function saved() {
    setEditing(null)
    setVersion((v) => v + 1)
  }

  const list = integrations ?? []
  const transportSummary = (t: Integration["transport"]) =>
    t.type === "stdio"
      ? `${t.command} ${(t.args ?? []).join(" ")}`.trim()
      : (t as { url: string }).url

  if (integrations === null) {
    return <Skeleton className="h-24 w-full" />
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("integrations.title")}</CardTitle>
        <CardDescription>{t("integrations.description")}</CardDescription>
        <CardAction>
          {kinds.length ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setEditing({ integration: null, kinds })}
            >
              <PlusIcon />
              {t("integrations.add")}
            </Button>
          ) : null}
        </CardAction>
      </CardHeader>
      <CardContent>
        {list.length === 0 ? (
          <Empty className="border">
            <EmptyHeader>
              <EmptyTitle>{t("integrations.emptyTitle")}</EmptyTitle>
            </EmptyHeader>
          </Empty>
        ) : (
          <ItemGroup className="gap-2">
            {list.map((integration) => (
              <Item key={integration.id} variant="outline" size="sm">
                <ItemContent>
                  <ItemTitle>{integration.name}</ItemTitle>
                  <ItemDescription>
                    {kinds.find((k) => k.id === integration.kind)?.label ??
                      integration.kind}
                    {` · ${transportSummary(integration.transport)}`}
                    {integration.secrets_set?.length
                      ? ` · ${t("integrations.tokenSet")}`
                      : ""}
                  </ItemDescription>
                </ItemContent>
                <ItemActions>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={t("providers.editAria", {
                      name: integration.name,
                    })}
                    onClick={() => setEditing({ integration, kinds })}
                  >
                    <PencilIcon />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={t("providers.removeAria", {
                      name: integration.name,
                    })}
                    onClick={() => setRemoving(integration)}
                  >
                    <Trash2Icon />
                  </Button>
                </ItemActions>
              </Item>
            ))}
          </ItemGroup>
        )}
      </CardContent>
      <IntegrationDialog
        editing={editing}
        onClose={() => setEditing(null)}
        onSaved={saved}
      />
      <AlertDialog
        open={removing !== null}
        onOpenChange={(o) => !o && setRemoving(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("providers.removeTitle", { name: removing?.name })}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t("integrations.removeDescription")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => removing && void remove(removing)}
            >
              {t("remove")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}

const SECTIONS = [
  { id: "models", title: "sections.models" },
  { id: "tools", title: "sections.tools" },
  { id: "advanced", title: "sections.advanced" },
] as const satisfies readonly { id: string; title: ParseKeys<"ai"> }[]

function Section({
  id,
  title,
  description,
  children,
}: {
  id: string
  title: string
  description: string
  children: React.ReactNode
}) {
  return (
    <section
      id={id}
      aria-labelledby={`${id}-title`}
      className="flex scroll-mt-20 flex-col gap-4"
    >
      <div className="flex flex-col gap-1">
        <h2 id={`${id}-title`} className="font-heading text-base font-medium">
          {title}
        </h2>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      {children}
    </section>
  )
}

/** Settings → AI: providers, default models, tools and limits (admins only). */
export function AiSettingsView() {
  const { t } = useTranslation("ai")
  const { user } = useAuth()
  const [version, setVersion] = React.useState(0)
  const { settings, save } = useAiSettings(version)
  if (!user.is_admin) {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyTitle>{t("adminOnly")}</EmptyTitle>
        </EmptyHeader>
      </Empty>
    )
  }
  return (
    <div className="flex flex-col gap-8">
      <nav aria-label={t("sections.navAria")} className="flex flex-wrap gap-1">
        {SECTIONS.map((s) => (
          <Button
            key={s.id}
            variant="outline"
            size="sm"
            nativeButton={false}
            render={<a href={`#${s.id}`} />}
          >
            {t(s.title)}
          </Button>
        ))}
      </nav>
      <Section
        id="models"
        title={t("sections.models")}
        description={t("sections.modelsDescription")}
      >
        <ProvidersCard onChanged={() => setVersion((v) => v + 1)} />
        <DefaultsCard version={version} settings={settings} save={save} />
        <ReviewCard settings={settings} save={save} />
      </Section>
      <Section
        id="tools"
        title={t("sections.tools")}
        description={t("sections.toolsDescription")}
      >
        <ToolsCard settings={settings} save={save} />
        <IntegrationsCard />
        <ShellCard settings={settings} save={save} />
      </Section>
      <Section
        id="advanced"
        title={t("sections.advanced")}
        description={t("sections.advancedDescription")}
      >
        <AdvancedCard settings={settings} save={save} />
      </Section>
    </div>
  )
}
