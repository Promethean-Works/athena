"use client"

import * as React from "react"
import {
  CopyIcon,
  DownloadIcon,
  ExternalLinkIcon,
  LockIcon,
  LockOpenIcon,
  RefreshCwIcon,
} from "lucide-react"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@workspace/ui/components/alert"
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
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@workspace/ui/components/empty"
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@workspace/ui/components/field"
import { Input } from "@workspace/ui/components/input"
import {
  RadioGroup,
  RadioGroupItem,
} from "@workspace/ui/components/radio-group"
import { Skeleton } from "@workspace/ui/components/skeleton"
import { Switch } from "@workspace/ui/components/switch"
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@workspace/ui/components/tabs"
import { toast } from "@workspace/ui/components/toast"

import { useAuth } from "@/components/auth-provider"
import { useCapability } from "@/components/capabilities-provider"
import { copyText } from "@/lib/clipboard"

type Status = Schemas["HttpsStatus"]
type Settings = Schemas["HttpsSettings"]
type Mode = NonNullable<Settings["mode"]>

const RECOVERY_COMMAND = "athena https off"
const CA_URL = "/api/https/ca.crt"

type Draft = { mode: Mode; port: string; redirect: boolean; names: string }

function toDraft(s: Settings): Draft {
  return {
    mode: s.mode ?? "off",
    port: String(s.port ?? 8443),
    redirect: s.redirect ?? true,
    names: (s.extra_names ?? []).join(", "),
  }
}

function parseNames(text: string): string[] {
  return text
    .split(/[\s,]+/)
    .map((n) => n.trim())
    .filter(Boolean)
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  })
}

function daysUntil(iso: string): number {
  return Math.floor((new Date(iso).getTime() - Date.now()) / 86_400_000)
}

/** The HTTPS address for the name this page was opened with, if the certificate covers it. */
function preferredUrl(status: Status): string | null {
  if (status.urls.length === 0) return null
  if (typeof window !== "undefined") {
    const host = window.location.hostname.toLowerCase()
    const match = status.urls.find((u) => {
      try {
        return new URL(u).hostname.toLowerCase() === host
      } catch {
        return false
      }
    })
    if (match) return match
  }
  // Otherwise a name that works without DNS setup: the .local name, then an IPv4 address.
  const host = (u: string) => new URL(u).hostname
  return (
    status.urls.find((u) => host(u).endsWith(".local")) ??
    status.urls.find((u) => /^\d+\.\d+\.\d+\.\d+$/.test(host(u))) ??
    status.urls[0] ??
    null
  )
}

/**
 * If this page came over the HTTPS listener and that listener just stopped or moved,
 * go to where Athena now answers (the session cookie isn't tied to a port). True if
 * the page is leaving.
 */
function followListener(saved: Status): boolean {
  if (typeof window === "undefined") return false
  const loc = window.location
  if (loc.protocol !== "https:") return false
  const here = Number(loc.port || 443)
  const path = `${loc.pathname}${loc.search}`
  if (saved.settings.mode === "off") {
    loc.assign(`http://${loc.hostname}:${saved.http_port}${path}`)
    return true
  }
  const port = saved.settings.port ?? here
  if (here !== saved.http_port && port !== here) {
    loc.assign(
      `https://${loc.hostname}${port === 443 ? "" : `:${port}`}${path}`
    )
    return true
  }
  return false
}

function onPlainHttp(): boolean {
  return typeof window !== "undefined" && window.location.protocol === "http:"
}

function defaultDeviceTab(): string {
  if (typeof navigator === "undefined") return "macos"
  const ua = navigator.userAgent
  if (/iPhone|iPad|iPod/.test(ua)) return "ios"
  if (/Android/.test(ua)) return "android"
  if (/Windows/.test(ua)) return "windows"
  if (/Linux/.test(ua)) return "linux"
  return "macos"
}

async function copy(value: string, what: string) {
  const ok = await copyText(value)
  toast.add(
    ok
      ? { type: "success", title: `${what} copied` }
      : { type: "error", title: "Couldn't copy" }
  )
}

/** Settings → HTTPS (docs/specs/https.md). Admins only. */
export function HttpsSettings() {
  const { user } = useAuth()
  const capability = useCapability("https")
  const [status, setStatus] = React.useState<Status | null>(null)
  const [loadError, setLoadError] = React.useState<string | null>(null)

  const load = React.useCallback(async () => {
    const { data, error } = await api.GET("/api/https")
    if (data) {
      setStatus(data)
      setLoadError(null)
    } else setLoadError(errorMessage(error))
  }, [])

  React.useEffect(() => {
    if (user.is_admin) void load()
  }, [load, user.is_admin])

  if (!user.is_admin) {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyTitle>Only admins can change HTTPS</EmptyTitle>
        </EmptyHeader>
      </Empty>
    )
  }
  if (!capability) {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyTitle>HTTPS isn&apos;t available</EmptyTitle>
          <EmptyDescription>
            This Athena server doesn&apos;t report HTTPS support.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }
  if (loadError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Couldn&apos;t load HTTPS settings</AlertTitle>
        <AlertDescription>{loadError}</AlertDescription>
      </Alert>
    )
  }
  if (status === null) {
    return (
      <div className="flex flex-col gap-4 md:gap-6">
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-72 w-full" />
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-4 md:gap-6">
      <StatusCard status={status} />
      <SettingsCard status={status} onSaved={setStatus} />
      {status.ca && status.settings.mode === "self_signed" ? (
        <TrustCard status={status} onRotated={setStatus} />
      ) : null}
    </div>
  )
}

function StatusCard({ status }: { status: Status }) {
  const on = status.settings.mode !== "off"
  const url = preferredUrl(status)
  const cert = status.certificate
  const left = cert ? daysUntil(cert.not_after) : null
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {status.listening ? (
            <LockIcon className="size-4" aria-hidden />
          ) : (
            <LockOpenIcon
              className="size-4 text-muted-foreground"
              aria-hidden
            />
          )}
          HTTPS
          <Badge variant={status.listening ? "default" : "secondary"}>
            {status.listening
              ? `On, port ${status.settings.port}`
              : on
                ? "Not running"
                : "Off"}
          </Badge>
        </CardTitle>
        <CardDescription>
          {on
            ? "Athena encrypts the connection with its own certificate. Plain HTTP stays on port " +
              `${status.http_port}.`
            : `Athena is served over plain HTTP on port ${status.http_port}, so passwords and files cross the network unencrypted.`}
        </CardDescription>
      </CardHeader>
      {status.last_error || (on && (url || cert)) ? (
        <CardContent className="flex flex-col gap-4">
          {status.last_error ? (
            <Alert variant="destructive">
              <AlertTitle>HTTPS problem</AlertTitle>
              <AlertDescription>{status.last_error}</AlertDescription>
            </Alert>
          ) : null}
          {on && url && status.listening ? (
            <div className="flex flex-wrap items-center gap-2">
              <Button
                render={<a href={url} target="_blank" rel="noreferrer" />}
                nativeButton={false}
              >
                <ExternalLinkIcon data-icon="inline-start" />
                Open over HTTPS
              </Button>
              <code className="text-sm break-all text-muted-foreground">
                {url}
              </code>
            </div>
          ) : null}
          {on && cert ? (
            <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[auto_1fr]">
              <dt className="text-muted-foreground">Expires</dt>
              <dd>
                {formatDate(cert.not_after)}
                {left !== null && left <= 30 ? (
                  <span className="text-muted-foreground">
                    {" "}
                    (in {Math.max(left, 0)} days; renewed automatically)
                  </span>
                ) : null}
              </dd>
              <dt className="text-muted-foreground">Names</dt>
              <dd className="flex flex-wrap gap-1">
                {cert.names.map((n) => (
                  <Badge key={n} variant="outline" className="font-mono">
                    {n}
                  </Badge>
                ))}
              </dd>
              {status.urls.length > 1 ? (
                <>
                  <dt className="text-muted-foreground">Also at</dt>
                  <dd className="flex flex-col gap-0.5">
                    {status.urls
                      .filter((u) => u !== url)
                      .map((u) => (
                        <a
                          key={u}
                          href={u}
                          target="_blank"
                          rel="noreferrer"
                          className="w-fit font-mono break-all underline-offset-4 hover:underline"
                        >
                          {u}
                        </a>
                      ))}
                  </dd>
                </>
              ) : null}
            </dl>
          ) : null}
        </CardContent>
      ) : null}
    </Card>
  )
}

function SettingsCard({
  status,
  onSaved,
}: {
  status: Status
  onSaved: (s: Status) => void
}) {
  const [draft, setDraft] = React.useState<Draft>(() =>
    toDraft(status.settings)
  )
  const [saving, setSaving] = React.useState(false)
  const [confirming, setConfirming] = React.useState(false)
  const [serverError, setServerError] = React.useState<string | null>(null)

  const saved = toDraft(status.settings)
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved)
  const on = draft.mode !== "off"
  const port = Number(draft.port)
  const portError = !on
    ? null
    : !Number.isInteger(port) || port < 1 || port > 65535
      ? "Enter a port from 1 to 65535."
      : port === status.http_port
        ? `Port ${port} is Athena's HTTP port. Pick another one.`
        : null

  function next(): Settings {
    return {
      mode: draft.mode,
      port: on ? port : Number(saved.port),
      redirect: draft.redirect,
      extra_names: parseNames(draft.names),
    }
  }

  /** Turning on (or moving) the redirect while this page is open over HTTP. */
  function needsConfirm(): boolean {
    if (!on || !draft.redirect || !onPlainHttp()) return false
    const wasRedirecting =
      saved.mode !== "off" && saved.redirect && saved.port === draft.port
    return !wasRedirecting
  }

  async function save() {
    setConfirming(false)
    setSaving(true)
    setServerError(null)
    const { data, error } = await api.PUT("/api/https", { body: next() })
    setSaving(false)
    if (data) {
      if (followListener(data)) return
      onSaved(data)
      setDraft(toDraft(data.settings))
      toast.add({
        type: "success",
        title:
          data.settings.mode === "off"
            ? "HTTPS turned off"
            : "HTTPS settings saved",
      })
    } else {
      setServerError(errorMessage(error))
    }
  }

  const newUrl =
    typeof window === "undefined"
      ? ""
      : `https://${window.location.hostname}${port === 443 ? "" : `:${draft.port}`}`

  return (
    <Card>
      <CardHeader>
        <CardTitle>Settings</CardTitle>
        <CardDescription>
          Changes apply right away; Athena doesn&apos;t restart.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          id="https-settings"
          onSubmit={(e) => {
            e.preventDefault()
            if (portError) return
            if (needsConfirm()) setConfirming(true)
            else void save()
          }}
        >
          <FieldGroup>
            <FieldSet>
              <FieldLegend variant="label">Mode</FieldLegend>
              <RadioGroup
                value={draft.mode}
                onValueChange={(v) => setDraft({ ...draft, mode: v as Mode })}
              >
                <Field orientation="horizontal">
                  <RadioGroupItem value="off" id="https-mode-off" />
                  <FieldContent>
                    <FieldLabel
                      htmlFor="https-mode-off"
                      className="font-normal"
                    >
                      Off
                    </FieldLabel>
                    <FieldDescription>Plain HTTP only.</FieldDescription>
                  </FieldContent>
                </Field>
                <Field orientation="horizontal">
                  <RadioGroupItem value="self_signed" id="https-mode-self" />
                  <FieldContent>
                    <FieldLabel
                      htmlFor="https-mode-self"
                      className="font-normal"
                    >
                      Self-signed
                    </FieldLabel>
                    <FieldDescription>
                      Athena makes its own certificate authority (CA). Trust it
                      once on each device and browsers show a padlock with no
                      warning. Works on your home network with no domain.
                    </FieldDescription>
                  </FieldContent>
                </Field>
              </RadioGroup>
            </FieldSet>

            {on ? (
              <>
                <Field data-invalid={!!portError}>
                  <FieldLabel htmlFor="https-port">HTTPS port</FieldLabel>
                  <Input
                    id="https-port"
                    inputMode="numeric"
                    className="w-32"
                    value={draft.port}
                    aria-invalid={!!portError}
                    onChange={(e) =>
                      setDraft({ ...draft, port: e.target.value })
                    }
                  />
                  <FieldDescription>
                    Ports below 1024 (like 443) may need Athena to run as root.
                    You may have to allow the port in the host&apos;s firewall.
                  </FieldDescription>
                  {portError ? <FieldError>{portError}</FieldError> : null}
                </Field>

                <Field orientation="horizontal">
                  <FieldContent>
                    <FieldLabel htmlFor="https-redirect">
                      Send browsers to HTTPS
                    </FieldLabel>
                    <FieldDescription>
                      Pages opened on port {status.http_port} move to HTTPS.
                      File shares, webhooks, apps and the server itself keep
                      using plain HTTP.
                    </FieldDescription>
                  </FieldContent>
                  <Switch
                    id="https-redirect"
                    checked={draft.redirect}
                    onCheckedChange={(checked) =>
                      setDraft({ ...draft, redirect: checked })
                    }
                  />
                </Field>

                <Field>
                  <FieldLabel htmlFor="https-names">Extra names</FieldLabel>
                  <Input
                    id="https-names"
                    placeholder="nas.home.lan, 10.0.0.5"
                    value={draft.names}
                    onChange={(e) =>
                      setDraft({ ...draft, names: e.target.value })
                    }
                  />
                  <FieldDescription>
                    The certificate already covers this server&apos;s name, its
                    .local name and its network addresses. Add any other name or
                    address you open Athena with, separated by commas.
                  </FieldDescription>
                </Field>
              </>
            ) : null}

            {serverError ? (
              <Alert variant="destructive">
                <AlertTitle>Couldn&apos;t save</AlertTitle>
                <AlertDescription>{serverError}</AlertDescription>
              </Alert>
            ) : null}
          </FieldGroup>
        </form>
      </CardContent>
      <CardFooter className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          Locked out? Run <code className="font-mono">{RECOVERY_COMMAND}</code>{" "}
          on the server and restart Athena.
        </p>
        <div className="flex gap-2">
          {dirty ? (
            <Button
              type="button"
              variant="ghost"
              disabled={saving}
              onClick={() => {
                setDraft(saved)
                setServerError(null)
              }}
            >
              Cancel
            </Button>
          ) : null}
          <Button
            type="submit"
            form="https-settings"
            disabled={!dirty || saving || !!portError}
          >
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      </CardFooter>

      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Send browsers to HTTPS?</AlertDialogTitle>
            <AlertDialogDescription>
              After saving, opening Athena on port {status.http_port} takes you
              to <span className="font-mono break-all">{newUrl}</span>. Until
              you trust Athena&apos;s CA on a device, its browser shows a
              warning there. If you can&apos;t get back in, run{" "}
              <span className="font-mono">{RECOVERY_COMMAND}</span> on the
              server and restart Athena.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => void save()}>
              Save and redirect
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}

const DEVICE_STEPS: { id: string; label: string; steps: React.ReactNode[] }[] =
  [
    {
      id: "macos",
      label: "macOS",
      steps: [
        "Open the downloaded file. Keychain Access adds it to the login keychain.",
        <>
          In Keychain Access, double-click <b>Athena Local CA</b>, open{" "}
          <b>Trust</b>, and set <b>When using this certificate</b> to{" "}
          <b>Always Trust</b>.
        </>,
        "Close the window and enter your Mac password. Restart the browser.",
      ],
    },
    {
      id: "windows",
      label: "Windows",
      steps: [
        <>
          Open the downloaded file and choose <b>Install Certificate</b>.
        </>,
        <>
          Pick <b>Current User</b>, then{" "}
          <b>Place all certificates in the following store</b> →{" "}
          <b>Trusted Root Certification Authorities</b>.
        </>,
        "Finish and confirm the security warning. Restart the browser.",
      ],
    },
    {
      id: "linux",
      label: "Linux",
      steps: [
        <>
          Debian or Ubuntu:{" "}
          <code className="font-mono break-all">
            sudo cp athena-local-ca.crt /usr/local/share/ca-certificates/
            &amp;&amp; sudo update-ca-certificates
          </code>
        </>,
        <>
          Fedora:{" "}
          <code className="font-mono break-all">
            sudo cp athena-local-ca.crt /etc/pki/ca-trust/source/anchors/
            &amp;&amp; sudo update-ca-trust
          </code>
        </>,
        <>
          Firefox and Chrome keep their own list on Linux: import the file under
          the browser&apos;s certificate settings, in <b>Authorities</b>.
        </>,
      ],
    },
    {
      id: "ios",
      label: "iPhone and iPad",
      steps: [
        "Download the file in Safari and allow the profile download.",
        <>
          In Settings, open <b>Profile Downloaded</b> (or{" "}
          <b>General → VPN &amp; Device Management</b>) and install it.
        </>,
        <>
          Go to <b>General → About → Certificate Trust Settings</b> and turn on
          full trust for <b>Athena Local CA</b>.
        </>,
      ],
    },
    {
      id: "android",
      label: "Android",
      steps: [
        "Download the file.",
        <>
          In Settings, search for <b>CA certificate</b> (usually{" "}
          <b>
            Security → Encryption &amp; credentials → Install a certificate → CA
            certificate
          </b>
          ) and pick the file.
        </>,
        "Confirm the warning. Some apps ignore user certificates; browsers use them.",
      ],
    },
  ]

function TrustCard({
  status,
  onRotated,
}: {
  status: Status
  onRotated: (s: Status) => void
}) {
  const [rotating, setRotating] = React.useState(false)
  const [confirming, setConfirming] = React.useState(false)
  const ca = status.ca
  if (!ca) return null

  async function rotate() {
    setConfirming(false)
    setRotating(true)
    const { data, error } = await api.POST("/api/https/ca/rotate")
    setRotating(false)
    if (data) {
      onRotated(data)
      toast.add({
        type: "success",
        title: "New CA made",
        description: "Download it and trust it again on each device.",
      })
    } else {
      toast.add({
        type: "error",
        title: "Couldn't make a new CA",
        description: errorMessage(error),
      })
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Trust Athena on your devices</CardTitle>
        <CardDescription>
          Install Athena&apos;s CA once on each phone, tablet and computer you
          use. Then the browser trusts every certificate Athena makes, including
          renewals.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <div className="flex flex-wrap items-center gap-3">
          <Button render={<a href={CA_URL} download />} nativeButton={false}>
            <DownloadIcon data-icon="inline-start" />
            Download CA certificate
          </Button>
          <span className="text-sm text-muted-foreground">
            Valid until {formatDate(ca.not_after)}
          </span>
        </div>
        <Field>
          <FieldLabel>SHA-256 fingerprint</FieldLabel>
          <div className="flex items-start gap-2">
            <code className="min-w-0 flex-1 font-mono text-xs break-all text-muted-foreground">
              {ca.sha256}
            </code>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Copy fingerprint"
              onClick={() => void copy(ca.sha256, "Fingerprint")}
            >
              <CopyIcon />
            </Button>
          </div>
          <FieldDescription>
            Check it matches what the device shows before trusting the file.
          </FieldDescription>
        </Field>
        <Tabs defaultValue={defaultDeviceTab()}>
          <TabsList className="flex-wrap group-data-horizontal/tabs:h-auto">
            {DEVICE_STEPS.map((d) => (
              <TabsTrigger key={d.id} value={d.id}>
                {d.label}
              </TabsTrigger>
            ))}
          </TabsList>
          {DEVICE_STEPS.map((d) => (
            <TabsContent key={d.id} value={d.id} className="pt-2">
              <ol className="ml-5 flex list-decimal flex-col gap-1.5 text-sm">
                {d.steps.map((step, i) => (
                  <li key={i}>{step}</li>
                ))}
              </ol>
            </TabsContent>
          ))}
        </Tabs>
      </CardContent>
      <CardFooter className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          Make a new CA if the key may have leaked. Every device has to trust
          the new one.
        </p>
        <Button
          variant="outline"
          disabled={rotating}
          onClick={() => setConfirming(true)}
        >
          <RefreshCwIcon data-icon="inline-start" />
          {rotating ? "Making…" : "Make a new CA"}
        </Button>
      </CardFooter>

      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Make a new CA?</AlertDialogTitle>
            <AlertDialogDescription>
              Devices that trust the current CA show a warning until you install
              the new one on each of them.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => void rotate()}
            >
              Make a new CA
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}
