"use client"

import * as React from "react"
import {
  CopyIcon,
  DownloadIcon,
  PlayIcon,
  RotateCcwIcon,
  SquareIcon,
  WifiIcon,
  AlertTriangleIcon,
} from "lucide-react"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@workspace/ui/components/alert"
import { Button } from "@workspace/ui/components/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@workspace/ui/components/field"
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@workspace/ui/components/tabs"
import { toast } from "@workspace/ui/components/toast"
import { JobDialog } from "@/components/job-dialog"

import { useAuth } from "@/components/auth-provider"
import { useCapability } from "@/components/capabilities-provider"
import { copyText } from "@/lib/clipboard"

type TunnelProvider = "cloudflare" | "tailscale" | "ngrok"
type SystemSettings = Schemas["SystemSettings"]
type TunnelStatus = Schemas["TunnelStatusResponse"]

const PROVIDER_LABELS: Record<TunnelProvider, string> = {
  cloudflare: "Cloudflare Tunnel",
  tailscale: "Tailscale Funnel",
  ngrok: "Ngrok",
}

function ProviderIcon({ provider }: { provider: TunnelProvider }) {
  return <WifiIcon className="h-4 w-4" />
}

function CopyField({
  id,
  label,
  value,
}: {
  id: string
  label: string
  value: string
}) {
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <InputGroup>
        <InputGroupInput id={id} readOnly value={value} className="font-mono" />
        <InputGroupAddon align="inline-end">
          <InputGroupButton
            size="icon-xs"
            aria-label={`Copy ${label.toLowerCase()}`}
            onClick={async () => {
              const ok = await copyText(value)
              toast.add(
                ok
                  ? { type: "success", title: `${label} copied` }
                  : { type: "error", title: "Couldn't copy" }
              )
            }}
          >
            <CopyIcon />
          </InputGroupButton>
        </InputGroupAddon>
      </InputGroup>
    </Field>
  )
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
  const [show, setShow] = React.useState(false)
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <InputGroup>
        <InputGroupInput
          id={id}
          type={show ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          placeholder={placeholder}
        />
        <InputGroupAddon align="inline-end">
          <InputGroupButton
            size="icon-xs"
            aria-label={show ? "Hide" : "Show"}
            onClick={() => setShow(!show)}
          >
            {show ? <RotateCcwIcon className="h-4 w-4" /> : <RotateCcwIcon className="h-4 w-4" />}
          </InputGroupButton>
        </InputGroupAddon>
      </InputGroup>
    </Field>
  )
}

function ProviderConfigForm({
  provider,
  config,
  onChange,
  disabled,
}: {
  provider: TunnelProvider
  config: Record<string, unknown>
  onChange: (config: Record<string, unknown>) => void
  disabled: boolean
}) {
  const handleChange = (key: string, value: unknown) => {
    onChange({ ...config, [key]: value })
  }

  if (provider === "cloudflare") {
    const quickTunnel = (config.quick_tunnel as boolean) ?? true
    return (
      <FieldGroup>
        <Field orientation="horizontal">
          <FieldContent>
            <FieldLabel>Quick Tunnel</FieldLabel>
            <FieldDescription>
              Use an ephemeral trycloudflare.com URL (no auth needed).
            </FieldDescription>
          </FieldContent>
          <Switch
            checked={quickTunnel}
            disabled={disabled}
            onCheckedChange={(checked) => handleChange("quick_tunnel", checked)}
          />
        </Field>
        {!quickTunnel && (
          <>
            <SecretInput
              id="cf-api-token"
              label="API Token"
              value={(config.api_token as string) ?? ""}
              onChange={(v) => handleChange("api_token", v)}
              disabled={disabled}
              placeholder="Cloudflare API Token with Tunnel permissions"
            />
            <Field>
              <FieldLabel htmlFor="cf-tunnel-name">Tunnel Name</FieldLabel>
              <InputGroup>
                <InputGroupInput
                  id="cf-tunnel-name"
                  value={(config.tunnel_name as string) ?? ""}
                  onChange={(e) => handleChange("tunnel_name", e.target.value)}
                  disabled={disabled}
                  placeholder="my-tunnel"
                />
              </InputGroup>
              <FieldDescription>
                Name of the named tunnel in Cloudflare.
              </FieldDescription>
            </Field>
            <Field>
              <FieldLabel htmlFor="cf-domain">Custom Domain (optional)</FieldLabel>
              <InputGroup>
                <InputGroupInput
                  id="cf-domain"
                  value={(config.domain as string) ?? ""}
                  onChange={(e) => handleChange("domain", e.target.value)}
                  disabled={disabled}
                  placeholder="tunnel.example.com"
                />
              </InputGroup>
              <FieldDescription>
                Custom domain for the tunnel (requires DNS setup).
              </FieldDescription>
            </Field>
          </>
        )}
      </FieldGroup>
    )
  }

  if (provider === "tailscale") {
    return (
      <FieldGroup>
        <Field>
          <FieldLabel htmlFor="ts-tailnet">Tailnet</FieldLabel>
          <InputGroup>
            <InputGroupInput
              id="ts-tailnet"
              readOnly
              value={(config.tailnet_name as string) ?? "Detected automatically"}
            />
          </InputGroup>
          <FieldDescription>
            Your Tailscale tailnet. Configured via <code>tailscale up</code>.
          </FieldDescription>
        </Field>
      </FieldGroup>
    )
  }

  if (provider === "ngrok") {
    return (
      <FieldGroup>
        <SecretInput
          id="ngrok-auth-token"
          label="Auth Token"
          value={(config.auth_token as string) ?? ""}
          onChange={(v) => handleChange("auth_token", v)}
          disabled={disabled}
          placeholder="Your ngrok auth token (required)"
        />
        <Field>
          <FieldLabel htmlFor="ngrok-domain">Custom Domain (optional)</FieldLabel>
          <InputGroup>
            <InputGroupInput
              id="ngrok-domain"
              value={(config.domain as string) ?? ""}
              onChange={(e) => handleChange("domain", e.target.value)}
              disabled={disabled}
              placeholder="tunnel.example.com"
            />
          </InputGroup>
          <FieldDescription>
            Custom domain (requires paid ngrok plan).
          </FieldDescription>
        </Field>
        <Field>
          <FieldLabel htmlFor="ngrok-subdomain">Subdomain (optional)</FieldLabel>
          <InputGroup>
            <InputGroupInput
              id="ngrok-subdomain"
              value={(config.subdomain as string) ?? ""}
              onChange={(e) => handleChange("subdomain", e.target.value)}
              disabled={disabled}
              placeholder="my-subdomain"
            />
          </InputGroup>
          <FieldDescription>
            Custom subdomain (requires paid ngrok plan).
          </FieldDescription>
        </Field>
        <Alert variant="default">
          <AlertTitle>
            <AlertTriangleIcon className="h-4 w-4" />
            Free tier limits
          </AlertTitle>
          <AlertDescription>
            Ngrok free tier: 1 tunnel, 40 connections/min, random URL each session.
            Custom domains and subdomains require a paid plan.
          </AlertDescription>
        </Alert>
      </FieldGroup>
    )
  }

  return null
}

export function TunnelCard() {
  const { user } = useAuth()
  const hasTunnelCapability =
    useCapability("tunnel.cloudflare") ||
    useCapability("tunnel.tailscale") ||
    useCapability("tunnel.ngrok")
  const [status, setStatus] = React.useState<TunnelStatus | null>(null)
  const [systemSettings, setSystemSettings] = React.useState<SystemSettings | null>(null)
  const [saving, setSaving] = React.useState(false)
  const [jobDialog, setJobDialog] = React.useState<{ job: Schemas["JobOut"]; title: string } | null>(null)
  const [config, setConfig] = React.useState<Record<string, unknown>>({})
  const [provider, setProvider] = React.useState<TunnelProvider>("cloudflare")
  const [autoStart, setAutoStart] = React.useState(true)
  const [port, setPort] = React.useState(8420)

  // Fetch system settings to get tunnel config
  React.useEffect(() => {
    api.GET("/api/settings/system").then(({ data }) => {
      if (data) {
        setSystemSettings(data)
        setConfig(data.tunnel_config ?? {})
        setProvider((data.tunnel_provider as TunnelProvider) ?? "cloudflare")
        setAutoStart(data.tunnel_auto_start ?? true)
        setPort(data.tunnel_port ?? 8420)
      }
    })
  }, [])

  // Fetch tunnel status
  React.useEffect(() => {
    let cancelled = false
    api.GET("/api/tunnel/status").then(({ data }) => {
      if (!cancelled && data) setStatus(data)
    })
    return () => {
      cancelled = true
    }
  }, [])

  const refreshStatus = async () => {
    const { data } = await api.GET("/api/tunnel/status")
    if (data) setStatus(data)
  }

  if (!hasTunnelCapability) return null

  async function updateTunnelSettings(next: Partial<SystemSettings>) {
    if (!systemSettings) return
    const previous = systemSettings
    const merged = { ...systemSettings, ...next }
    setSystemSettings(merged)
    setSaving(true)
    const { data, error } = await api.PUT("/api/settings/system", {
      body: merged,
    })
    setSaving(false)
    if (data) {
      setSystemSettings(data)
      toast.add({
        type: "success",
        title: data.tunnel_enabled ? "Tunnel enabled" : "Tunnel disabled",
      })
    } else {
      setSystemSettings(previous)
      toast.add({
        type: "error",
        title: "Couldn't save",
        description: errorMessage(error),
      })
    }
  }

  async function updateConfig(nextConfig: Record<string, unknown>) {
    setConfig(nextConfig)
    await updateTunnelSettings({ tunnel_config: nextConfig })
  }

  async function handleProviderChange(newProvider: TunnelProvider | null) {
    if (newProvider) {
      setProvider(newProvider)
      await updateTunnelSettings({ tunnel_provider: newProvider })
    }
  }

  async function handleAutoStartChange(enabled: boolean) {
    setAutoStart(enabled)
    await updateTunnelSettings({ tunnel_auto_start: enabled })
  }

  async function handlePortChange(newPort: number) {
    setPort(newPort)
    await updateTunnelSettings({ tunnel_port: newPort })
  }

  async function startTunnel() {
    const { data, error } = await api.POST("/api/tunnel/start")
    if (data && data.job_id) {
      // Poll for job to get full job object
      const { data: jobData } = await api.GET("/api/jobs/{job_id}", {
        params: { path: { job_id: data.job_id } },
      })
      if (jobData) {
        setJobDialog({ job: jobData, title: "Starting tunnel" })
      }
      setTimeout(refreshStatus, 2000)
    } else {
      toast.add({
        type: "error",
        title: "Couldn't start tunnel",
        description: errorMessage(error),
      })
    }
  }

  async function stopTunnel() {
    const { data, error } = await api.POST("/api/tunnel/stop")
    if (data && data.job_id) {
      const { data: jobData } = await api.GET("/api/jobs/{job_id}", {
        params: { path: { job_id: data.job_id } },
      })
      if (jobData) {
        setJobDialog({ job: jobData, title: "Stopping tunnel" })
      }
      setTimeout(refreshStatus, 2000)
    } else {
      toast.add({
        type: "error",
        title: "Couldn't stop tunnel",
        description: errorMessage(error),
      })
    }
  }

  async function installBinary() {
    const { data, error } = await api.POST("/api/tunnel/install", {
      body: { provider },
    })
    if (data && data.job_id) {
      const { data: jobData } = await api.GET("/api/jobs/{job_id}", {
        params: { path: { job_id: data.job_id } },
      })
      if (jobData) {
        setJobDialog({ job: jobData, title: `Installing ${PROVIDER_LABELS[provider]}` })
      }
    } else {
      toast.add({
        type: "error",
        title: "Couldn't install",
        description: errorMessage(error),
      })
    }
  }

  async function configureService(enabled: boolean) {
    const { data, error } = await api.PUT("/api/tunnel/service", {
      params: { query: { enabled } },
    })
    if (data && data.job_id) {
      const { data: jobData } = await api.GET("/api/jobs/{job_id}", {
        params: { path: { job_id: data.job_id } },
      })
      if (jobData) {
        setJobDialog({ job: jobData, title: `${enabled ? "Enabling" : "Disabling"} auto-start` })
      }
    } else {
      toast.add({
        type: "error",
        title: "Couldn't update service",
        description: errorMessage(error),
      })
    }
  }

  const isRunning = status?.running ?? false
  const capabilityStatus = status?.capability_status ?? "missing"
  const isMissing = capabilityStatus === "missing"
  const isStopped = capabilityStatus === "stopped"

  return (
    <Card>
      <CardHeader>
        <CardTitle>Remote Access Tunnel</CardTitle>
        <CardDescription>
          Expose Athena to the internet securely via Cloudflare, Tailscale, or Ngrok.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {systemSettings === null ? (
          <Skeleton className="h-12 w-full" />
        ) : (
          <FieldGroup>
            <Field orientation="horizontal">
              <FieldContent>
                <FieldLabel htmlFor="tunnel-enabled">Tunnel</FieldLabel>
                <FieldDescription>
                  Master toggle for remote access tunnel.
                  {!user.is_admin && " Only admins can change this."}
                </FieldDescription>
              </FieldContent>
              <Switch
                id="tunnel-enabled"
                checked={systemSettings.tunnel_enabled}
                disabled={saving || !user.is_admin}
                onCheckedChange={(checked) => void updateTunnelSettings({ tunnel_enabled: checked })}
              />
            </Field>

            {systemSettings.tunnel_enabled && (
              <>
                <Field orientation="horizontal">
                  <FieldContent>
                    <FieldLabel htmlFor="tunnel-provider">Provider</FieldLabel>
                    <FieldDescription>
                      Choose your tunnel provider.
                    </FieldDescription>
                  </FieldContent>
                  <Select
                    value={provider}
                    onValueChange={handleProviderChange}
                    disabled={saving || !user.is_admin}
                  >
                    <SelectTrigger id="tunnel-provider">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="cloudflare">
                        <ProviderIcon provider="cloudflare" />
                        Cloudflare Tunnel
                      </SelectItem>
                      <SelectItem value="tailscale">
                        <ProviderIcon provider="tailscale" />
                        Tailscale Funnel
                      </SelectItem>
                      <SelectItem value="ngrok">
                        <ProviderIcon provider="ngrok" />
                        Ngrok
                      </SelectItem>
                    </SelectContent>
                  </Select>
                </Field>

                <ProviderConfigForm
                  provider={provider}
                  config={config}
                  onChange={updateConfig}
                  disabled={saving || !user.is_admin}
                />

                <Field orientation="horizontal">
                  <FieldContent>
                    <FieldLabel htmlFor="tunnel-port">Local Port</FieldLabel>
                    <FieldDescription>
                      The local port Athena runs on.
                    </FieldDescription>
                  </FieldContent>
                  <InputGroup>
                    <InputGroupInput
                      id="tunnel-port"
                      type="number"
                      value={port}
                      onChange={(e) => handlePortChange(parseInt(e.target.value) || 8420)}
                      disabled={saving || !user.is_admin}
                      min="1"
                      max="65535"
                      className="w-24"
                    />
                  </InputGroup>
                </Field>

                <Field orientation="horizontal">
                  <FieldContent>
                    <FieldLabel htmlFor="tunnel-auto-start">Auto-start on boot</FieldLabel>
                    <FieldDescription>
                      Start the tunnel automatically when the server boots.
                    </FieldDescription>
                  </FieldContent>
                  <Switch
                    id="tunnel-auto-start"
                    checked={autoStart}
                    disabled={saving || !user.is_admin}
                    onCheckedChange={handleAutoStartChange}
                  />
                </Field>

                <div className="flex flex-col gap-2 pt-2">
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-muted-foreground">Status:</span>
                    <span
                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${
                        isRunning
                          ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
                          : isStopped
                          ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200"
                          : "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200"
                      }`}
                    >
                      {isRunning ? (
                        <>
                          <PlayIcon className="h-3 w-3" />
                          Running
                        </>
                      ) : isStopped ? (
                        <>
                          <SquareIcon className="h-3 w-3" />
                          Stopped
                        </>
                      ) : (
                        <>
                          <WifiIcon className="h-3 w-3" />
                          Not configured
                        </>
                      )}
                    </span>
                  </div>

                  {status?.public_url && (
                    <CopyField
                      id="tunnel-url"
                      label="Public URL"
                      value={status.public_url}
                    />
                  )}

                  <div className="flex flex-wrap gap-2">
                    {isMissing ? (
                      <>
                        <Button
                          variant="outline"
                          onClick={installBinary}
                          disabled={saving || !user.is_admin}
                        >
                          <DownloadIcon className="h-4 w-4 mr-1" />
                          Install {PROVIDER_LABELS[provider]}
                        </Button>
                      </>
                    ) : (
                      <>
                        {isRunning ? (
                          <Button
                            variant="destructive"
                            onClick={stopTunnel}
                            disabled={saving || !user.is_admin}
                          >
                            <SquareIcon className="h-4 w-4 mr-1" />
                            Stop
                          </Button>
                        ) : (
                          <Button onClick={startTunnel} disabled={saving || !user.is_admin}>
                            <PlayIcon className="h-4 w-4 mr-1" />
                            Start
                          </Button>
                        )}
                        <Button
                          variant="outline"
                          onClick={() => configureService(!autoStart)}
                          disabled={saving || !user.is_admin}
                        >
                          {autoStart ? "Disable auto-start" : "Enable auto-start"}
                        </Button>
                        <Button
                          variant="outline"
                          onClick={refreshStatus}
                          disabled={saving}
                        >
                          <RotateCcwIcon className="h-4 w-4 mr-1" />
                          Refresh
                        </Button>
                      </>
                    )}
                  </div>

                  {status?.detail && (
                    <p className="text-sm text-muted-foreground">{status.detail}</p>
                  )}
                </div>
              </>
            )}
          </FieldGroup>
        )}
      </CardContent>
    </Card>
  )
}