"use client"

import * as React from "react"
import {
  ChevronDownIcon,
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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@workspace/ui/components/dropdown-menu"
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
import {
  ProviderDialog,
  type Provider,
  type ProviderEditing,
  type ProviderKind,
} from "@/components/settings/ai-provider-dialog"

type AiSettings = Schemas["AiSettings"]

export function AddMenu({
  kinds,
  onPick,
  label = "Add provider",
}: {
  kinds: ProviderKind[]
  onPick: (kind: ProviderKind) => void
  label?: string
}) {
  const groups: [string, ProviderKind[]][] = [
    ["Cloud", kinds.filter((k) => k.group === "cloud")],
    ["Local", kinds.filter((k) => k.group === "local")],
  ]
  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={<Button variant="outline" size="sm" />}>
        <PlusIcon />
        {label}
        <ChevronDownIcon />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        {groups.map(([title, list], i) => (
          <React.Fragment key={title}>
            {i > 0 ? <DropdownMenuSeparator /> : null}
            <DropdownMenuGroup>
              <DropdownMenuLabel>{title}</DropdownMenuLabel>
              {list.map((k) => (
                <DropdownMenuItem key={k.id} onClick={() => onPick(k)}>
                  {k.label}
                </DropdownMenuItem>
              ))}
            </DropdownMenuGroup>
          </React.Fragment>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function ProvidersCard({ onChanged }: { onChanged: () => void }) {
  const ollama = useCapability("ai.ollama")
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
  const ollamaKind = kindOf("ollama")

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
        title: `${p.name} didn't connect`,
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
        title: "Couldn't remove",
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

  function useOllama() {
    if (!ollamaKind || !ollama?.endpoint) return
    setEditing({ kind: ollamaKind, values: { base_url: ollama.endpoint } })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Providers</CardTitle>
        <CardDescription>
          Set up providers once, then pick any of their models in a chat.
        </CardDescription>
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
                {ollama?.available ? <CpuIcon /> : <CloudIcon />}
              </EmptyMedia>
              <EmptyTitle>No providers yet</EmptyTitle>
              <EmptyDescription>
                {ollama?.available
                  ? `${ollama.detail ?? "Ollama"} is running on this server. Its models run on your own hardware and nothing leaves the server.`
                  : "Add a cloud provider with an API key, or install Ollama on this server to run models locally."}
              </EmptyDescription>
            </EmptyHeader>
            <EmptyContent className="flex-row flex-wrap justify-center">
              {ollama?.available && ollamaKind ? (
                <Button onClick={useOllama}>
                  <CpuIcon />
                  Use Ollama on this server
                </Button>
              ) : null}
              <AddMenu
                kinds={kinds}
                onPick={(kind) => setEditing({ kind })}
                label={
                  ollama?.available
                    ? "Another provider"
                    : "Add a cloud provider"
                }
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
                    Test
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Edit ${p.name}`}
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
                    aria-label={`Remove ${p.name}`}
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
            <AlertDialogTitle>Remove {removing?.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              Its key is deleted from this server. Chats that used its models
              stay, and ask for another model.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => removing && void remove(removing)}
            >
              Remove
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
          title: "Couldn't save",
          description: errorMessage(error),
        })
      }
    },
    [settings]
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
        title: "Enter an amount above 0, or leave it empty",
      })
      return
    }
    if (value === (settings.spend_limit_usd ?? null)) return
    void save(
      { ...settings, spend_limit_usd: value },
      value ? `Chats stop at $${value}` : "No spend limit"
    )
  }

  if (!providers?.length && settings !== null) return null

  return (
    <Card>
      <CardHeader>
        <CardTitle>Defaults</CardTitle>
        <CardDescription>
          New chats start with the default model. Each chat can switch model at
          any time.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {settings === null ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="default-model">Default model</FieldLabel>
              <ModelPicker
                id="default-model"
                variant="field"
                providers={providers}
                value={settings.default_model}
                onChange={(ref: ModelRef) =>
                  void save(
                    { ...settings, default_model: ref },
                    "Default model saved"
                  )
                }
              />
              <FieldDescription>
                Only models that can use tools work with the assistant.
              </FieldDescription>
            </Field>
            <Field>
              <FieldLabel htmlFor="title-model">
                Model for chat titles
              </FieldLabel>
              <ModelPicker
                id="title-model"
                variant="field"
                providers={providers}
                value={settings.title_model}
                onChange={(ref: ModelRef) =>
                  void save(
                    { ...settings, title_model: ref },
                    "Title model saved"
                  )
                }
              />
              <FieldDescription>
                Optional. A small, cheap model is enough.
              </FieldDescription>
            </Field>
            <Field>
              <FieldLabel htmlFor="advisor-model">Advisor model</FieldLabel>
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
                      "Advisor model saved"
                    )
                  }
                />
                {settings.advisor_model && (
                  <Button
                    variant="outline"
                    onClick={() =>
                      void save(
                        { ...settings, advisor_model: null },
                        "Advisor turned off"
                      )
                    }
                  >
                    Turn off
                  </Button>
                )}
              </div>
              <FieldDescription>
                Optional. A stronger model the assistant can ask for a second
                opinion, once per step. Its provider sees the question the
                assistant writes, not the whole chat, and what it costs counts
                toward the spend limit.
              </FieldDescription>
            </Field>
            <Field orientation="horizontal">
              <FieldContent>
                <FieldLabel htmlFor="refine-answers">
                  Double-check answers
                </FieldLabel>
                <FieldDescription>
                  Before it finishes, the assistant reviews its answer and
                  writes it again, fixed. At least one more model request per
                  reply, so slower and costlier; the first draft stays folded in
                  the reply.
                </FieldDescription>
              </FieldContent>
              <Switch
                id="refine-answers"
                checked={settings.refine_answers}
                onCheckedChange={(checked) =>
                  void save(
                    { ...settings, refine_answers: checked },
                    checked
                      ? "Answers are double-checked"
                      : "Answers are no longer double-checked"
                  )
                }
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="spend-limit">
                Spend limit per chat (USD)
              </FieldLabel>
              <Input
                id="spend-limit"
                inputMode="decimal"
                value={limit}
                placeholder="No limit"
                onChange={(e) => setLimit(e.target.value)}
                onBlur={saveLimit}
                onKeyDown={(e) => e.key === "Enter" && saveLimit()}
                className="max-w-40"
              />
              <FieldDescription>
                A chat stops once it has cost this much. Only applies to models
                with known prices; local models are free.
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
        title: `“${bad}” isn't a program name`,
        description:
          "List programs only, one per line, without shell operators like ; | & > or $.",
      })
      return
    }
    if (commands.join("\n") === saved) {
      setText(saved)
      return
    }
    void save(
      { ...settings, shell_commands: commands },
      commands.length ? "Allowlist saved" : "Allowlist emptied"
    )
  }

  if (where?.status !== "ready") return null

  return (
    <Card>
      <CardHeader>
        <CardTitle>Shell</CardTitle>
        <CardDescription>
          Let the assistant ask to run commands on this server, as the user
          Athena runs as. You approve every command before it runs, and each one
          is written to the audit log.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {settings === null ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          <FieldGroup>
            <Field orientation="horizontal">
              <FieldContent>
                <FieldLabel htmlFor="shell-enabled">Assistant shell</FieldLabel>
                <FieldDescription>
                  Off by default. Athena&apos;s own tools (apps, packages,
                  files) don&apos;t need it.
                  {where.detail && ` ${where.detail}.`}
                </FieldDescription>
              </FieldContent>
              <Switch
                id="shell-enabled"
                checked={settings.shell_enabled}
                onCheckedChange={(checked) =>
                  void save(
                    { ...settings, shell_enabled: checked },
                    checked
                      ? "Assistant shell turned on"
                      : "Assistant shell turned off"
                  )
                }
              />
            </Field>
            <Field data-disabled={!settings.shell_enabled || undefined}>
              <FieldLabel htmlFor="shell-commands">Allowed programs</FieldLabel>
              <Textarea
                id="shell-commands"
                value={text}
                disabled={!settings.shell_enabled}
                onChange={(e) => setText(e.target.value)}
                onBlur={saveCommands}
                rows={6}
                spellCheck={false}
                className="font-mono"
              />
              <FieldDescription>
                One per line. Every program in a command is checked, including
                each part of a pipe (<code>|</code>) or chain (<code>&&</code>,{" "}
                <code>;</code>); others are refused before you&apos;re asked.
                This guards against mistakes, not a determined model: an allowed
                program can start others, so read each command before you
                approve it. Empty means no shell.
              </FieldDescription>
            </Field>
          </FieldGroup>
        )}
      </CardContent>
    </Card>
  )
}

function MemoryCard({
  settings,
  save,
}: {
  settings: AiSettings | null
  save: SaveAi
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Memory and skills</CardTitle>
        <CardDescription>
          The assistant can keep notes that later chats read, such as how this
          server is set up. Each admin has their own notes. Notes and skills
          that look like hidden instructions are refused and written to the
          audit log.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {settings === null ? (
          <Skeleton className="h-12 w-full" />
        ) : (
          <FieldGroup>
            <Field orientation="horizontal">
              <FieldContent>
                <FieldLabel htmlFor="memory-enabled">
                  Remember across chats
                </FieldLabel>
                <FieldDescription>
                  Turning it off keeps the saved notes; the assistant just stops
                  reading and writing them.
                </FieldDescription>
              </FieldContent>
              <Switch
                id="memory-enabled"
                checked={settings.memory_enabled}
                onCheckedChange={(checked) =>
                  void save(
                    { ...settings, memory_enabled: checked },
                    checked ? "Memory turned on" : "Memory turned off"
                  )
                }
              />
            </Field>
            <FieldDescription>
              Skills are instructions the assistant loads when a task needs
              them. Add one as a folder with a <code>SKILL.md</code> file in{" "}
              <code>assistant/skills</code> inside Athena&apos;s data folder.
            </FieldDescription>
          </FieldGroup>
        )}
      </CardContent>
    </Card>
  )
}

/** Settings → AI: providers, default models and limits (admins only). */
export function AiSettingsView() {
  const { user } = useAuth()
  const [version, setVersion] = React.useState(0)
  const { settings, save } = useAiSettings(version)
  if (!user.is_admin) {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyTitle>Only admins can set up the assistant</EmptyTitle>
        </EmptyHeader>
      </Empty>
    )
  }
  return (
    <div className="flex flex-col gap-4 md:gap-6">
      <ProvidersCard onChanged={() => setVersion((v) => v + 1)} />
      <DefaultsCard version={version} settings={settings} save={save} />
      <MemoryCard settings={settings} save={save} />
      <ShellCard settings={settings} save={save} />
    </div>
  )
}
