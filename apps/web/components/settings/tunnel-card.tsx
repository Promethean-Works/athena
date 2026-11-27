"use client"

import * as React from "react"
import {
  AlertTriangleIcon,
  DownloadIcon,
  EyeIcon,
  EyeOffIcon,
  PlayIcon,
  RotateCcwIcon,
  SquareIcon,
} from "lucide-react"
import { Trans, useTranslation } from "react-i18next"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@workspace/ui/components/alert"
import { Badge } from "@workspace/ui/components/badge"
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
  Field,
  FieldContent,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldSeparator,
} from "@workspace/ui/components/field"
import { Input } from "@workspace/ui/components/input"
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupInput,
} from "@workspace/ui/components/input-group"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import { Skeleton } from "@workspace/ui/components/skeleton"
import { Switch } from "@workspace/ui/components/switch"
import { toast } from "@workspace/ui/components/toast"

import { useAuth } from "@/components/auth-provider"
import { useCapability } from "@/components/capabilities-provider"
import { JobDialog } from "@/components/job-dialog"
import { patchSystemSettings } from "@/components/settings/system-settings"
import { CopyField } from "@/components/settings/copy-field"
import { TunnelQr } from "@/components/tunnel/tunnel-qr"

type TunnelProvider = "cloudflare" | "tailscale" | "ngrok"
type SystemSettings = Schemas["SystemSettings"]
type TunnelStatus = Schemas["TunnelStatusResponse"]
type Job = Schemas["JobOut"]
type Config = Record<string, unknown>

const PROVIDER_LABELS: Record<TunnelProvider, string> = {
  cloudflare: "Cloudflare Tunnel",
  tailscale: "Tailscale Funnel",
  ngrok: "ngrok",
}

function SecretInput({
  id,
  label,
  value,
  onChange,
  disabled,
  placeholder,
}: {
  id: string
  label: string
  value: string
  onChange: (v: string) => void
  disabled?: boolean
  placeholder?: string
}) {
  const { t } = useTranslation("settings")
  const [show, setShow] = React.useState(false)
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <InputGroup>
        <InputGroupInput
          id={id}
          type={show ? "text" : "password"}
          autoComplete="off"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          placeholder={placeholder}
        />
        <InputGroupAddon align="inline-end">
          <InputGroupButton
            size="icon-xs"
            aria-label={
              show ? t("tunnel.hide", { label }) : t("tunnel.show", { label })
            }
            onClick={() => setShow(!show)}
          >
            {show ? <EyeOffIcon /> : <EyeIcon />}
          </InputGroupButton>
        </InputGroupAddon>
      </InputGroup>
    </Field>
  )
}

function TextField({
  id,
  label,
  value,
  onChange,
  disabled,
  placeholder,
  description,
}: {
  id: string
  label: string
  value: string
  onChange: (v: string) => void
  disabled?: boolean
  placeholder?: string
  description: string
}) {
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Input
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        placeholder={placeholder}
      />
      <FieldDescription>{description}</FieldDescription>
    </Field>
  )
}

function ProviderConfigForm({
  provider,
  config,
  secretsSet,
  onChange,
  disabled,
}: {
  provider: TunnelProvider
  config: Config
  /** Secret keys with a stored value. The server never sends secrets back. */
  secretsSet: string[]
  onChange: (config: Config) => void
  disabled: boolean
}) {
  const { t } = useTranslation("settings")
  const set = (key: string) => (value: unknown) =>
    onChange({ ...config, [key]: value })
  const str = (key: string) => (config[key] as string | undefined) ?? ""
  const secretPlaceholder = (key: string, empty: string) =>
    secretsSet.includes(key) ? t("tunnel.secretSaved") : empty

  if (provider === "cloudflare") {
    const quickTunnel = (config.quick_tunnel as boolean | undefined) ?? true
    return (
      <>
        <Field orientation="horizontal">
          <FieldContent>
            <FieldLabel htmlFor="cf-quick">
              {t("tunnel.cloudflare.quick")}
            </FieldLabel>
            <FieldDescription>
              {t("tunnel.cloudflare.quickHelp")}
            </FieldDescription>
          </FieldContent>
          <Switch
            id="cf-quick"
            checked={quickTunnel}
            disabled={disabled}
            onCheckedChange={set("quick_tunnel")}
          />
        </Field>
        {!quickTunnel && (
          <>
            <SecretInput
              id="cf-api-token"
              label={t("tunnel.cloudflare.apiToken")}
              value={str("api_token")}
              onChange={set("api_token")}
              disabled={disabled}
              placeholder={secretPlaceholder(
                "api_token",
                t("tunnel.cloudflare.apiTokenPlaceholder")
              )}
            />
            <TextField
              id="cf-tunnel-name"
              label={t("tunnel.cloudflare.tunnelName")}
              value={str("tunnel_name")}
              onChange={set("tunnel_name")}
              disabled={disabled}
              placeholder="my-tunnel"
              description={t("tunnel.cloudflare.tunnelNameHelp")}
            />
            <TextField
              id="cf-domain"
              label={t("tunnel.customDomain")}
              value={str("domain")}
              onChange={set("domain")}
              disabled={disabled}
              placeholder="athena.example.com"
              description={t("tunnel.cloudflare.domainHelp")}
            />
          </>
        )}
      </>
    )
  }

  if (provider === "tailscale") {
    return (
      <Field>
        <FieldLabel htmlFor="ts-tailnet">
          {t("tunnel.tailscale.tailnet")}
        </FieldLabel>
        <Input
          id="ts-tailnet"
          readOnly
          value={str("tailnet_name") || t("tunnel.tailscale.auto")}
        />
        <FieldDescription>
          <Trans
            i18nKey="tunnel.tailscale.help"
            ns="settings"
            components={{ code: <code /> }}
          />
        </FieldDescription>
      </Field>
    )
  }

  return (
    <>
      <SecretInput
        id="ngrok-auth-token"
        label={t("tunnel.ngrok.authToken")}
        value={str("auth_token")}
        onChange={set("auth_token")}
        disabled={disabled}
        placeholder={secretPlaceholder(
          "auth_token",
          t("tunnel.ngrok.authTokenPlaceholder")
        )}
      />
      <TextField
        id="ngrok-domain"
        label={t("tunnel.customDomain")}
        value={str("domain")}
        onChange={set("domain")}
        disabled={disabled}
        placeholder="athena.example.com"
        description={t("tunnel.ngrok.paidPlan")}
      />
      <TextField
        id="ngrok-subdomain"
        label={t("tunnel.ngrok.subdomain")}
        value={str("subdomain")}
        onChange={set("subdomain")}
        disabled={disabled}
        placeholder="my-athena"
        description={t("tunnel.ngrok.paidPlan")}
      />
      <Alert>
        <AlertTriangleIcon />
        <AlertTitle>{t("tunnel.ngrok.freeTitle")}</AlertTitle>
        <AlertDescription>{t("tunnel.ngrok.freeDescription")}</AlertDescription>
      </Alert>
    </>
  )
}

function StatusBadge({ status }: { status: TunnelStatus | null }) {
  const { t } = useTranslation("settings")
  if (!status) return <Skeleton className="h-5 w-20" />
  if (status.running) return <Badge>{t("tunnel.status.running")}</Badge>
  switch (status.capability_status) {
    case "stopped":
      return <Badge variant="secondary">{t("tunnel.status.stopped")}</Badge>
    case "not_installed":
      return (
        <Badge variant="destructive">{t("tunnel.status.notInstalled")}</Badge>
      )
    default:
      return <Badge variant="outline">{t("tunnel.status.notSetUp")}</Badge>
  }
}

const sameJson = (a: unknown, b: unknown) =>
  JSON.stringify(a) === JSON.stringify(b)

export function TunnelCard() {
  const { t } = useTranslation("settings")
  const { user } = useAuth()
  // Call each hook on every render: `a || b || c` skipped calls and broke
  // React's rules of hooks.
  const cloudflare = useCapability("tunnel.cloudflare")
  const tailscale = useCapability("tunnel.tailscale")
  const ngrok = useCapability("tunnel.ngrok")
  const hasTunnelCapability = Boolean(cloudflare || tailscale || ngrok)

  const [status, setStatus] = React.useState<TunnelStatus | null>(null)
  const [settings, setSettings] = React.useState<SystemSettings | null>(null)
  const [saving, setSaving] = React.useState(false)
  const [job, setJob] = React.useState<Job | null>(null)
  // Typed fields stay a draft until Save: typing used to send a request per
  // keystroke and lock the field while each one ran.
  const [config, setConfig] = React.useState<Config>({})
  const [port, setPort] = React.useState("8420")

  const refreshStatus = React.useCallback(async () => {
    const { data } = await api.GET("/api/tunnel/status")
    if (data) setStatus(data)
  }, [])

  const loadDraft = (data: SystemSettings) => {
    setConfig(data.tunnel_config ?? {})
    setPort(String(data.tunnel_port ?? 8420))
  }

  React.useEffect(() => {
    void api.GET("/api/settings/system").then(({ data }) => {
      if (!data) return
      setSettings(data)
      loadDraft(data)
    })
    void refreshStatus()
  }, [refreshStatus])

  if (!hasTunnelCapability) return null

  const canEdit = user.is_admin && !saving
  const provider = (settings?.tunnel_provider as TunnelProvider) ?? "cloudflare"
  const portNumber = Number(port)
  const portValid =
    Number.isInteger(portNumber) && portNumber >= 1 && portNumber <= 65535
  const dirty =
    settings !== null &&
    (!sameJson(config, settings.tunnel_config ?? {}) ||
      portNumber !== (settings.tunnel_port ?? 8420))

  async function save(
    next: Partial<SystemSettings>,
    message: string
  ): Promise<SystemSettings | null> {
    if (!settings) return null
    setSaving(true)
    const { data, error } = await patchSystemSettings(next)
    setSaving(false)
    if (!data) {
      toast.add({
        type: "error",
        title: t("tunnel.saveFailed"),
        description: errorMessage(error),
      })
      return null
    }
    setSettings(data)
    toast.add({ type: "success", title: message })
    void refreshStatus()
    return data
  }

  async function saveDraft() {
    if (!portValid) return
    const data = await save(
      { tunnel_config: config, tunnel_port: portNumber },
      t("tunnel.saved")
    )
    // The server never returns secrets, so this also clears typed tokens and
    // shows their "Saved" placeholder instead.
    if (data) loadDraft(data)
  }

  async function runJob(
    request: Promise<{
      data?: { job_id?: string | null } | null
      error?: unknown
    }>,
    failure: string
  ) {
    const { data, error } = await request
    if (!data?.job_id) {
      toast.add({
        type: "error",
        title: failure,
        description: errorMessage(error),
      })
      return
    }
    const { data: jobData } = await api.GET("/api/jobs/{job_id}", {
      params: { path: { job_id: data.job_id } },
    })
    if (jobData) setJob(jobData)
  }

  async function changeAutoStart(enabled: boolean) {
    const saved = await save(
      { tunnel_auto_start: enabled },
      enabled ? t("tunnel.autoStart.on") : t("tunnel.autoStart.off")
    )
    if (!saved) return
    await runJob(
      api.PUT("/api/tunnel/service", { params: { query: { enabled } } }),
      t("tunnel.serviceFailed")
    )
  }

  const running = status?.running ?? false
  const capabilityStatus = status?.capability_status ?? "missing"
  const needsInstall =
    capabilityStatus === "missing" || capabilityStatus === "not_installed"

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("tunnel.title")}</CardTitle>
        <CardDescription>{t("tunnel.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {settings === null ? (
          <Skeleton className="h-12 w-full" />
        ) : (
          <FieldGroup>
            <Field orientation="horizontal">
              <FieldContent>
                <FieldLabel htmlFor="tunnel-enabled">
                  {t("tunnel.label")}
                </FieldLabel>
                <FieldDescription>
                  {t("tunnel.help")}
                  {!user.is_admin && ` ${t("tunnel.adminOnly")}`}
                </FieldDescription>
              </FieldContent>
              <Switch
                id="tunnel-enabled"
                checked={settings.tunnel_enabled}
                disabled={!canEdit}
                onCheckedChange={(checked) =>
                  void save(
                    { tunnel_enabled: checked },
                    checked ? t("tunnel.on") : t("tunnel.off")
                  )
                }
              />
            </Field>

            {settings.tunnel_enabled && (
              <>
                <Alert variant="destructive">
                  <AlertTriangleIcon />
                  <AlertTitle>{t("tunnel.exposed.title")}</AlertTitle>
                  <AlertDescription>
                    <Trans
                      i18nKey="tunnel.exposed.description"
                      ns="settings"
                      components={{
                        terminal: (
                          <a className="underline" href="#terminal-enabled" />
                        ),
                        assistant: (
                          <a className="underline" href="/settings/ai/" />
                        ),
                      }}
                    />
                  </AlertDescription>
                </Alert>
                <FieldSeparator />
                <Field orientation="horizontal">
                  <FieldContent>
                    <FieldLabel htmlFor="tunnel-provider">
                      {t("tunnel.provider")}
                    </FieldLabel>
                  </FieldContent>
                  <Select
                    value={provider}
                    onValueChange={(value) =>
                      value &&
                      void save(
                        { tunnel_provider: value },
                        t("tunnel.using", {
                          name: PROVIDER_LABELS[value as TunnelProvider],
                        })
                      )
                    }
                    disabled={!canEdit}
                  >
                    <SelectTrigger id="tunnel-provider" className="w-48">
                      <SelectValue>
                        {(value: TunnelProvider) => PROVIDER_LABELS[value]}
                      </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      {(Object.keys(PROVIDER_LABELS) as TunnelProvider[]).map(
                        (p) => (
                          <SelectItem key={p} value={p}>
                            {PROVIDER_LABELS[p]}
                          </SelectItem>
                        )
                      )}
                    </SelectContent>
                  </Select>
                </Field>

                <ProviderConfigForm
                  provider={provider}
                  config={config}
                  secretsSet={settings.tunnel_secrets_set ?? []}
                  onChange={setConfig}
                  disabled={!user.is_admin}
                />

                <Field orientation="horizontal">
                  <FieldContent>
                    <FieldLabel htmlFor="tunnel-port">
                      {t("tunnel.port.label")}
                    </FieldLabel>
                    <FieldDescription>{t("tunnel.port.help")}</FieldDescription>
                  </FieldContent>
                  <Input
                    id="tunnel-port"
                    inputMode="numeric"
                    value={port}
                    onChange={(e) => setPort(e.target.value)}
                    disabled={!user.is_admin}
                    aria-invalid={!portValid || undefined}
                    className="w-24"
                  />
                </Field>

                {dirty && (
                  <div className="flex justify-end gap-2">
                    <Button
                      variant="outline"
                      onClick={() => loadDraft(settings)}
                    >
                      {t("tunnel.discard")}
                    </Button>
                    <Button
                      onClick={() => void saveDraft()}
                      disabled={!canEdit || !portValid}
                    >
                      {t("tunnel.saveChanges")}
                    </Button>
                  </div>
                )}

                <Field orientation="horizontal">
                  <FieldContent>
                    <FieldLabel htmlFor="tunnel-auto-start">
                      {t("tunnel.autoStart.label")}
                    </FieldLabel>
                    <FieldDescription>
                      {needsInstall
                        ? t("tunnel.autoStart.installFirst", {
                            name: PROVIDER_LABELS[provider],
                          })
                        : t("tunnel.autoStart.help")}
                    </FieldDescription>
                  </FieldContent>
                  <Switch
                    id="tunnel-auto-start"
                    // Nothing can start on boot before the tool is installed.
                    checked={
                      !needsInstall && (settings.tunnel_auto_start ?? true)
                    }
                    disabled={!canEdit || needsInstall}
                    onCheckedChange={(checked) => void changeAutoStart(checked)}
                  />
                </Field>

                <FieldSeparator />

                <div className="flex flex-col gap-3">
                  <div className="flex items-center gap-2 text-sm">
                    <span className="text-muted-foreground">
                      {t("tunnel.status.label")}
                    </span>
                    <StatusBadge status={status} />
                  </div>
                  {status?.public_url && (
                    <>
                      <CopyField
                        id="tunnel-url"
                        label={t("tunnel.publicAddress")}
                        value={status.public_url}
                      />
                      <TunnelQr value={status.public_url} />
                    </>
                  )}
                  {status?.detail && (
                    <p className="text-sm text-muted-foreground">
                      {status.detail}
                    </p>
                  )}
                </div>
              </>
            )}
          </FieldGroup>
        )}
      </CardContent>
      {settings?.tunnel_enabled && (
        <CardFooter className="flex flex-wrap gap-2">
          {needsInstall ? (
            <Button
              variant="outline"
              disabled={!canEdit}
              onClick={() =>
                void runJob(
                  api.POST("/api/tunnel/install", { body: { provider } }),
                  t("tunnel.installFailed")
                )
              }
            >
              <DownloadIcon data-icon="inline-start" />
              {t("tunnel.install", { name: PROVIDER_LABELS[provider] })}
            </Button>
          ) : running ? (
            <Button
              variant="destructive"
              disabled={!canEdit}
              onClick={() =>
                void runJob(
                  api.POST("/api/tunnel/stop"),
                  t("tunnel.stopFailed")
                )
              }
            >
              <SquareIcon data-icon="inline-start" />
              {t("tunnel.stop")}
            </Button>
          ) : (
            <Button
              disabled={!canEdit || dirty}
              title={dirty ? t("tunnel.saveFirst") : undefined}
              onClick={() =>
                void runJob(
                  api.POST("/api/tunnel/start"),
                  t("tunnel.startFailed")
                )
              }
            >
              <PlayIcon data-icon="inline-start" />
              {t("tunnel.start")}
            </Button>
          )}
          <Button variant="ghost" onClick={() => void refreshStatus()}>
            <RotateCcwIcon data-icon="inline-start" />
            {t("tunnel.refresh")}
          </Button>
        </CardFooter>
      )}
      <JobDialog
        job={job}
        onClose={() => setJob(null)}
        onFinished={() => void refreshStatus()}
      />
    </Card>
  )
}
