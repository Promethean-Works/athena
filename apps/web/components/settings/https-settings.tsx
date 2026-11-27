"use client"

import * as React from "react"
import {
  CopyIcon,
  DownloadIcon,
  ExternalLinkIcon,
  FileBadgeIcon,
  LockIcon,
  LockOpenIcon,
  RefreshCwIcon,
} from "lucide-react"
import type { ParseKeys } from "i18next"
import { Trans, useTranslation } from "react-i18next"

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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
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
import { JobDialog } from "@/components/job-dialog"
import { copyText } from "@/lib/clipboard"
import i18n, { currentLocale } from "@/lib/i18n"

type Status = Schemas["HttpsStatus"]
type Settings = Schemas["HttpsSettings"]
type Mode = NonNullable<Settings["mode"]>
type LetsEncrypt = Schemas["LetsEncryptSettings"]
type Challenge = NonNullable<LetsEncrypt["challenge"]>
type DnsProvider = Schemas["DnsProvider"]
type Job = Schemas["JobOut"]

const RECOVERY_COMMAND = "athena https off"
const CA_URL = "/api/https/ca.crt"

type Draft = {
  mode: Mode
  port: string
  redirect: boolean
  names: string
  domains: string
  email: string
  challenge: Challenge
  provider: string
  /** The DNS provider's fields. Secrets start empty: an empty one keeps the stored value. */
  dns: Record<string, string>
  staging: boolean
  /** The PEM-encoded certificate for custom mode. */
  custom_cert: string
  /** The PEM-encoded private key for custom mode. */
  custom_key: string
}

function toDraft(s: Settings): Draft {
  const le = s.letsencrypt
  const dns: Record<string, string> = {}
  for (const [k, v] of Object.entries(le?.dns_config ?? {})) {
    if (typeof v === "string") dns[k] = v
  }
  return {
    mode: s.mode ?? "off",
    port: String(s.port ?? 8443),
    redirect: s.redirect ?? true,
    names: (s.extra_names ?? []).join(", "),
    domains: (le?.domains ?? []).join(", "),
    email: le?.email ?? "",
    challenge: le?.challenge ?? "http",
    provider: le?.dns_provider ?? "cloudflare",
    dns,
    staging: le?.staging ?? false,
    custom_cert: s.custom_cert ?? "",
    custom_key: s.custom_key ?? "",
  }
}

function toLetsEncrypt(draft: Draft): LetsEncrypt {
  const dns = draft.challenge === "dns"
  return {
    domains: parseNames(draft.domains),
    email: draft.email.trim(),
    challenge: draft.challenge,
    dns_provider: dns ? draft.provider : null,
    // Empty values are left out, so stored secrets are kept.
    dns_config: dns
      ? Object.fromEntries(
          Object.entries(draft.dns).filter(([, v]) => v.trim() !== "")
        )
      : {},
    staging: draft.staging,
  }
}

function parseNames(text: string): string[] {
  return text
    .split(/[\s,]+/)
    .map((n) => n.trim())
    .filter(Boolean)
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(currentLocale(), {
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

async function copy(value: string, copiedTitle: string) {
  const ok = await copyText(value)
  toast.add(
    ok
      ? { type: "success", title: copiedTitle }
      : { type: "error", title: i18n.t("settings:https.copyFailed") }
  )
}

/** Settings → HTTPS (docs/specs/https.md). Admins only. */
export function HttpsSettings() {
  const { t } = useTranslation("settings")
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

  // A certificate job started elsewhere (the daily check, another tab): follow it.
  const jobRunning = status?.renewal_job != null
  React.useEffect(() => {
    if (!jobRunning) return
    const timer = window.setInterval(() => void load(), 3000)
    return () => window.clearInterval(timer)
  }, [jobRunning, load])

  if (!user.is_admin) {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyTitle>{t("https.adminOnly")}</EmptyTitle>
        </EmptyHeader>
      </Empty>
    )
  }
  if (!capability) {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyTitle>{t("https.unavailable.title")}</EmptyTitle>
          <EmptyDescription>
            {t("https.unavailable.description")}
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }
  if (loadError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>{t("https.loadFailed")}</AlertTitle>
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
      <SettingsCard status={status} onSaved={setStatus} reload={load} />
      {status.ca && status.settings.mode === "self_signed" ? (
        <TrustCard status={status} onRotated={setStatus} />
      ) : null}
    </div>
  )
}

function StatusCard({ status }: { status: Status }) {
  const { t } = useTranslation("settings")
  const on = status.settings.mode !== "off"
  const url = preferredUrl(status)
  const cert = status.certificate
  const left = cert ? daysUntil(cert.not_after) : null
  const renewalError =
    status.settings.mode === "letsencrypt" ? status.renewal_error : null
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
              ? t("https.status.on", { port: status.settings.port })
              : on
                ? t("https.status.notRunning")
                : t("https.status.off")}
          </Badge>
        </CardTitle>
        <CardDescription>
          {on
            ? status.settings.mode === "letsencrypt"
              ? t("https.status.encryptedLetsEncrypt", {
                  port: status.http_port,
                })
              : status.settings.mode === "custom"
                ? t("https.status.encryptedCustom", { port: status.http_port })
                : t("https.status.encryptedSelf", { port: status.http_port })
            : t("https.status.plain", { port: status.http_port })}
        </CardDescription>
      </CardHeader>
      {status.last_error || renewalError || (on && (url || cert)) ? (
        <CardContent className="flex flex-col gap-4">
          {status.last_error ? (
            <Alert variant="destructive">
              <AlertTitle>{t("https.status.problem")}</AlertTitle>
              <AlertDescription>{status.last_error}</AlertDescription>
            </Alert>
          ) : null}
          {renewalError ? (
            <Alert variant="destructive">
              <AlertTitle>{t("https.status.renewalFailed")}</AlertTitle>
              <AlertDescription>
                {renewalError} {t("https.status.renewalStillServed")}
              </AlertDescription>
            </Alert>
          ) : null}
          {on && url && status.listening ? (
            <div className="flex flex-wrap items-center gap-2">
              <Button
                render={<a href={url} target="_blank" rel="noreferrer" />}
                nativeButton={false}
              >
                <ExternalLinkIcon data-icon="inline-start" />
                {t("https.status.open")}
              </Button>
              <code className="text-sm break-all text-muted-foreground">
                {url}
              </code>
            </div>
          ) : null}
          {on && cert ? (
            <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[auto_1fr]">
              <dt className="text-muted-foreground">{t("https.status.expires")}</dt>
              <dd>
                {formatDate(cert.not_after)}
                {left !== null && left <= 30 ? (
                  <span className="text-muted-foreground">
                    {" "}
                    ({t("https.status.expiresIn", { count: Math.max(left, 0) })})
                  </span>
                ) : null}
              </dd>
              <dt className="text-muted-foreground">{t("https.status.names")}</dt>
              <dd className="flex flex-wrap gap-1">
                {cert.names.map((n) => (
                  <Badge key={n} variant="outline" className="font-mono">
                    {n}
                  </Badge>
                ))}
              </dd>
              {status.urls.length > 1 ? (
                <>
                  <dt className="text-muted-foreground">{t("https.status.alsoAt")}</dt>
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
  reload,
}: {
  status: Status
  onSaved: (s: Status) => void
  reload: () => Promise<void>
}) {
  const { t } = useTranslation("settings")
  const [draft, setDraft] = React.useState<Draft>(() =>
    toDraft(status.settings)
  )
  const [saving, setSaving] = React.useState(false)
  const [confirming, setConfirming] = React.useState(false)
  const [serverError, setServerError] = React.useState<string | null>(null)
  const [errorTitle, setErrorTitle] = React.useState(() => t("https.saveFailed"))
  const [job, setJob] = React.useState<Job | null>(null)
  const [requesting, setRequesting] = React.useState(false)

  const saved = toDraft(status.settings)
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved)
  const on = draft.mode !== "off"
  const port = Number(draft.port)
  const portError = !on
    ? null
    : !Number.isInteger(port) || port < 1 || port > 65535
      ? t("https.port.range")
      : port === status.http_port
        ? t("https.port.taken", { port })
        : null
  const needsCertificate =
    (draft.mode === "letsencrypt" && !status.letsencrypt_certificate) ||
    (draft.mode === "custom" && (!draft.custom_cert.trim() || !draft.custom_key.trim()))

  function next(): Settings {
    return {
      mode: draft.mode,
      port: on ? port : Number(saved.port),
      redirect: draft.redirect,
      extra_names: parseNames(draft.names),
      letsencrypt: toLetsEncrypt(draft),
      custom_cert: draft.custom_cert,
      custom_key: draft.custom_key,
    }
  }

  async function requestCertificate() {
    setRequesting(true)
    setServerError(null)
    const { data, error } = await api.POST("/api/https/certificate", {
      body: toLetsEncrypt(draft),
    })
    setRequesting(false)
    if (data) {
      setJob(data)
      // The server stored the settings (and any secret typed), so start over from them.
      const secrets = new Set(
        status.dns_providers.flatMap((p) =>
          p.fields.filter((f) => f.secret).map((f) => f.key)
        )
      )
      setDraft({
        ...draft,
        dns: Object.fromEntries(
          Object.entries(draft.dns).filter(([k]) => !secrets.has(k))
        ),
      })
    } else {
      setErrorTitle(t("https.requestFailed"))
      setServerError(errorMessage(error))
    }
  }

  async function certificateFinished(succeeded: boolean) {
    await reload()
    if (succeeded && status.settings.mode !== "letsencrypt") {
      toast.add({
        type: "success",
        title: t("https.certificateReady"),
        description: t("https.certificateReadyHint"),
      })
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
    setErrorTitle(t("https.saveFailed"))
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
            ? t("https.turnedOff")
            : t("https.saved"),
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
        <CardTitle>{t("https.settings.title")}</CardTitle>
        <CardDescription>
          {t("https.settings.description")}
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
              <FieldLegend variant="label">{t("https.mode.label")}</FieldLegend>
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
                      {t("https.mode.off")}
                    </FieldLabel>
                    <FieldDescription>
                      {t("https.mode.offHelp")}
                    </FieldDescription>
                  </FieldContent>
                </Field>
                <Field orientation="horizontal">
                  <RadioGroupItem value="self_signed" id="https-mode-self" />
                  <FieldContent>
                    <FieldLabel
                      htmlFor="https-mode-self"
                      className="font-normal"
                    >
                      {t("https.mode.self")}
                    </FieldLabel>
                    <FieldDescription>
                      {t("https.mode.selfHelp")}
                    </FieldDescription>
                  </FieldContent>
                </Field>
                <Field orientation="horizontal">
                  <RadioGroupItem value="letsencrypt" id="https-mode-le" />
                  <FieldContent>
                    <FieldLabel htmlFor="https-mode-le" className="font-normal">
                      {t("https.mode.letsencrypt")}
                    </FieldLabel>
                    <FieldDescription>
                      {t("https.mode.letsencryptHelp")}
                    </FieldDescription>
                  </FieldContent>
                </Field>
                <Field orientation="horizontal">
                  <RadioGroupItem value="custom" id="https-mode-custom" />
                  <FieldContent>
                    <FieldLabel
                      htmlFor="https-mode-custom"
                      className="font-normal"
                    >
                      {t("https.mode.custom")}
                    </FieldLabel>
                    <FieldDescription>
                      {t("https.mode.customHelp")}
                    </FieldDescription>
                  </FieldContent>
                </Field>
              </RadioGroup>
            </FieldSet>

            {on ? (
              <>
                <Field data-invalid={!!portError}>
                  <FieldLabel htmlFor="https-port">
                    {t("https.port.label")}
                  </FieldLabel>
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
                    {t("https.port.help")}
                  </FieldDescription>
                  {portError ? <FieldError>{portError}</FieldError> : null}
                </Field>

                <Field orientation="horizontal">
                  <FieldContent>
                    <FieldLabel htmlFor="https-redirect">
                      {t("https.redirect.label")}
                    </FieldLabel>
                    <FieldDescription>
                      {t("https.redirect.help", { port: status.http_port })}
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

                {draft.mode === "letsencrypt" ? (
                  <LetsEncryptFields
                    draft={draft}
                    setDraft={setDraft}
                    status={status}
                    requesting={requesting || job !== null}
                    onRequest={() => void requestCertificate()}
                  />
                ) : null}

                {draft.mode === "self_signed" ? (
                  <Field>
                    <FieldLabel htmlFor="https-names">
                      {t("https.names.label")}
                    </FieldLabel>
                    <Input
                      id="https-names"
                      placeholder="nas.home.lan, 10.0.0.5"
                      value={draft.names}
                      onChange={(e) =>
                        setDraft({ ...draft, names: e.target.value })
                      }
                    />
                    <FieldDescription>
                      {t("https.names.help")}
                    </FieldDescription>
                  </Field>
                ) : null}

                {draft.mode === "custom" ? (
                  <CustomFields
                    draft={draft}
                    setDraft={setDraft}
                  />
                ) : null}
              </>
            ) : null}

            {serverError ? (
              <Alert variant="destructive">
                <AlertTitle>{errorTitle}</AlertTitle>
                <AlertDescription>{serverError}</AlertDescription>
              </Alert>
            ) : null}
          </FieldGroup>
        </form>
      </CardContent>
      <CardFooter className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          <Trans
            i18nKey="https.lockedOut"
            ns="settings"
            values={{ command: RECOVERY_COMMAND }}
            components={{ code: <code className="font-mono" /> }}
          />
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
              {t("https.cancel")}
            </Button>
          ) : null}
          <Button
            type="submit"
            form="https-settings"
            disabled={!dirty || saving || !!portError || needsCertificate}
            title={needsCertificate ? t("https.needsCertificate") : undefined}
          >
            {saving ? t("https.saving") : t("https.save")}
          </Button>
        </div>
      </CardFooter>

      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("https.confirm.title")}</AlertDialogTitle>
            <AlertDialogDescription>
              <Trans
                i18nKey="https.confirm.redirect"
                ns="settings"
                values={{ port: status.http_port, url: newUrl }}
                components={{ url: <span className="font-mono break-all" /> }}
              />{" "}
              {draft.mode === "letsencrypt"
                ? t("https.confirm.letsencrypt")
                : draft.mode === "custom"
                  ? t("https.confirm.custom")
                  : t("https.confirm.self")}{" "}
              <Trans
                i18nKey="https.confirm.recovery"
                ns="settings"
                values={{ command: RECOVERY_COMMAND }}
                components={{ cmd: <span className="font-mono" /> }}
              />
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("https.cancel")}</AlertDialogCancel>
            <AlertDialogAction onClick={() => void save()}>
              {t("https.confirm.action")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <JobDialog
        job={job}
        onClose={() => setJob(null)}
        onFinished={(ok) => void certificateFinished(ok)}
      />
    </Card>
  )
}

function LetsEncryptFields({
  draft,
  setDraft,
  status,
  requesting,
  onRequest,
}: {
  draft: Draft
  setDraft: (d: Draft) => void
  status: Status
  requesting: boolean
  onRequest: () => void
}) {
  const { t } = useTranslation("settings")
  const provider: DnsProvider | undefined = status.dns_providers.find(
    (p) => p.id === draft.provider
  )
  const secretsSet = new Set(status.settings.letsencrypt?.dns_secrets_set ?? [])
  const cert = status.letsencrypt_certificate
  const running = requesting || status.renewal_job !== null
  return (
    <FieldSet>
      <FieldLegend variant="label">{t("https.le.legend")}</FieldLegend>
      <FieldGroup>
        <Field>
          <FieldLabel htmlFor="le-domains">{t("https.le.domains")}</FieldLabel>
          <Input
            id="le-domains"
            placeholder="nas.example.com"
            value={draft.domains}
            onChange={(e) => setDraft({ ...draft, domains: e.target.value })}
          />
          <FieldDescription>
            {t("https.le.domainsHelp")}
          </FieldDescription>
        </Field>
        <Field>
          <FieldLabel htmlFor="le-email">{t("https.le.email")}</FieldLabel>
          <Input
            id="le-email"
            type="email"
            placeholder="you@example.com"
            value={draft.email}
            onChange={(e) => setDraft({ ...draft, email: e.target.value })}
          />
          <FieldDescription>
            {t("https.le.emailHelp")}
          </FieldDescription>
        </Field>

        <FieldSet>
          <FieldLegend variant="label">{t("https.le.challenge")}</FieldLegend>
          <RadioGroup
            value={draft.challenge}
            onValueChange={(v) =>
              setDraft({ ...draft, challenge: v as Challenge })
            }
          >
            <Field orientation="horizontal">
              <RadioGroupItem value="http" id="le-challenge-http" />
              <FieldContent>
                <FieldLabel htmlFor="le-challenge-http" className="font-normal">
                  {t("https.le.http")}
                </FieldLabel>
                <FieldDescription>
                  {t("https.le.httpHelp")}
                </FieldDescription>
              </FieldContent>
            </Field>
            <Field orientation="horizontal">
              <RadioGroupItem value="dns" id="le-challenge-dns" />
              <FieldContent>
                <FieldLabel htmlFor="le-challenge-dns" className="font-normal">
                  {t("https.le.dns")}
                </FieldLabel>
                <FieldDescription>
                  {t("https.le.dnsHelp")}
                </FieldDescription>
              </FieldContent>
            </Field>
          </RadioGroup>
        </FieldSet>

        {draft.challenge === "http" && !status.port80_free ? (
          <Alert>
            <AlertTitle>{t("https.le.port80Title")}</AlertTitle>
            <AlertDescription>
              {t("https.le.port80Description")}
            </AlertDescription>
          </Alert>
        ) : null}

        {draft.challenge === "dns" ? (
          <>
            <Field>
              <FieldLabel htmlFor="le-provider">
                {t("https.le.provider")}
              </FieldLabel>
              <Select
                value={draft.provider}
                onValueChange={(v) =>
                  v && setDraft({ ...draft, provider: v as string })
                }
              >
                <SelectTrigger id="le-provider" className="w-48">
                  <SelectValue>
                    {(value: string) =>
                      status.dns_providers.find((p) => p.id === value)?.label ??
                      value
                    }
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {status.dns_providers.map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            {provider?.fields.map((f) => (
              <Field key={f.key}>
                <FieldLabel htmlFor={`le-dns-${f.key}`}>{f.label}</FieldLabel>
                <Input
                  id={`le-dns-${f.key}`}
                  type={f.secret ? "password" : "text"}
                  autoComplete="off"
                  placeholder={
                    f.secret && secretsSet.has(f.key) ? t("https.le.savedUnchanged") : ""
                  }
                  value={draft.dns[f.key] ?? ""}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      dns: { ...draft.dns, [f.key]: e.target.value },
                    })
                  }
                />
                {f.help ? <FieldDescription>{f.help}</FieldDescription> : null}
              </Field>
            ))}
          </>
        ) : null}

        <Field orientation="horizontal">
          <FieldContent>
            <FieldLabel htmlFor="le-staging">
              {t("https.le.staging")}
            </FieldLabel>
            <FieldDescription>
              {t("https.le.stagingHelp")}
            </FieldDescription>
          </FieldContent>
          <Switch
            id="le-staging"
            checked={draft.staging}
            onCheckedChange={(checked) =>
              setDraft({ ...draft, staging: checked })
            }
          />
        </Field>

        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="outline"
            disabled={running}
            onClick={onRequest}
          >
            <FileBadgeIcon data-icon="inline-start" />
            {running
              ? t("https.le.getting")
              : cert
                ? t("https.le.renew")
                : t("https.le.get")}
          </Button>
          <span className="text-sm text-muted-foreground">
            {cert
              ? t("https.le.current", {
                  names: cert.names.join(", "),
                  date: formatDate(cert.not_after),
                })
              : t("https.le.getThenSave")}
          </span>
        </div>
        {status.renewal_error ? (
          <FieldError>
            {t("https.le.lastFailed", { error: status.renewal_error })}
          </FieldError>
        ) : null}
      </FieldGroup>
    </FieldSet>
  )
}

function CustomFields({
  draft,
  setDraft,
}: {
  draft: Draft
  setDraft: (d: Draft) => void
}) {
  const { t } = useTranslation("settings")
  return (
    <FieldSet>
      <FieldLegend variant="label">{t("https.custom.legend")}</FieldLegend>
      <FieldGroup>
        <Field>
          <FieldLabel htmlFor="custom-cert">
            {t("https.custom.cert")}
          </FieldLabel>
          <textarea
            id="custom-cert"
            className="w-full h-40 font-mono text-sm p-2 border rounded-md bg-background"
            placeholder="-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----"
            value={draft.custom_cert}
            onChange={(e) => setDraft({ ...draft, custom_cert: e.target.value })}
          />
          <FieldDescription>
            {t("https.custom.certHelp")}
          </FieldDescription>
        </Field>
        <Field>
          <FieldLabel htmlFor="custom-key">
            {t("https.custom.key")}
          </FieldLabel>
          <textarea
            id="custom-key"
            className="w-full h-40 font-mono text-sm p-2 border rounded-md bg-background"
            placeholder="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
            value={draft.custom_key}
            onChange={(e) => setDraft({ ...draft, custom_key: e.target.value })}
          />
          <FieldDescription>
            {t("https.custom.keyHelp")}
          </FieldDescription>
        </Field>
      </FieldGroup>
    </FieldSet>
  )
}

type SettingsKey = ParseKeys<"settings">
type DeviceStep = { key: SettingsKey; values?: Record<string, string> }

const DEVICE_STEPS: { id: string; label: SettingsKey; steps: DeviceStep[] }[] = [
  {
    id: "macos",
    label: "https.trust.macos.label",
    steps: [
      { key: "https.trust.macos.step1" },
      { key: "https.trust.macos.step2" },
      { key: "https.trust.macos.step3" },
    ],
  },
  {
    id: "windows",
    label: "https.trust.windows.label",
    steps: [
      { key: "https.trust.windows.step1" },
      { key: "https.trust.windows.step2" },
      { key: "https.trust.windows.step3" },
    ],
  },
  {
    id: "linux",
    label: "https.trust.linux.label",
    steps: [
      {
        key: "https.trust.linux.step1",
        values: {
          command:
            "sudo cp athena-local-ca.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates",
        },
      },
      {
        key: "https.trust.linux.step2",
        values: {
          command:
            "sudo cp athena-local-ca.crt /etc/pki/ca-trust/source/anchors/ && sudo update-ca-trust",
        },
      },
      { key: "https.trust.linux.step3" },
    ],
  },
  {
    id: "ios",
    label: "https.trust.ios.label",
    steps: [
      { key: "https.trust.ios.step1" },
      { key: "https.trust.ios.step2" },
      { key: "https.trust.ios.step3" },
    ],
  },
  {
    id: "android",
    label: "https.trust.android.label",
    steps: [
      { key: "https.trust.android.step1" },
      { key: "https.trust.android.step2" },
      { key: "https.trust.android.step3" },
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
  const { t } = useTranslation("settings")
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
        title: t("https.trust.rotated"),
        description: t("https.trust.rotatedHint"),
      })
    } else {
      toast.add({
        type: "error",
        title: t("https.trust.rotateFailed"),
        description: errorMessage(error),
      })
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("https.trust.title")}</CardTitle>
        <CardDescription>
          {t("https.trust.description")}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <div className="flex flex-wrap items-center gap-3">
          <Button render={<a href={CA_URL} download />} nativeButton={false}>
            <DownloadIcon data-icon="inline-start" />
            {t("https.trust.download")}
          </Button>
          <span className="text-sm text-muted-foreground">
            {t("https.trust.validUntil", { date: formatDate(ca.not_after) })}
          </span>
        </div>
        <Field>
          <FieldLabel>{t("https.trust.fingerprint")}</FieldLabel>
          <div className="flex items-start gap-2">
            <code className="min-w-0 flex-1 font-mono text-xs break-all text-muted-foreground">
              {ca.sha256}
            </code>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={t("https.trust.copyFingerprint")}
              onClick={() => void copy(ca.sha256, t("https.trust.fingerprintCopied"))}
            >
              <CopyIcon />
            </Button>
          </div>
          <FieldDescription>
            {t("https.trust.fingerprintHelp")}
          </FieldDescription>
        </Field>
        <Tabs defaultValue={defaultDeviceTab()}>
          <TabsList className="flex-wrap group-data-horizontal/tabs:h-auto">
            {DEVICE_STEPS.map((d) => (
              <TabsTrigger key={d.id} value={d.id}>
                {t(d.label)}
              </TabsTrigger>
            ))}
          </TabsList>
          {DEVICE_STEPS.map((d) => (
            <TabsContent key={d.id} value={d.id} className="pt-2">
              <ol className="ml-5 flex list-decimal flex-col gap-1.5 text-sm">
                {d.steps.map((step, i) => (
                  <li key={i}>
                    <Trans
                      i18nKey={step.key}
                      ns="settings"
                      values={step.values}
                      components={{
                        b: <b />,
                        code: <code className="font-mono break-all" />,
                      }}
                    />
                  </li>
                ))}
              </ol>
            </TabsContent>
          ))}
        </Tabs>
      </CardContent>
      <CardFooter className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          {t("https.trust.rotateHint")}
        </p>
        <Button
          variant="outline"
          disabled={rotating}
          onClick={() => setConfirming(true)}
        >
          <RefreshCwIcon data-icon="inline-start" />
          {rotating ? t("https.trust.rotating") : t("https.trust.rotate")}
        </Button>
      </CardFooter>

      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("https.trust.confirmTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("https.trust.confirmDescription")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("https.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => void rotate()}
            >
              {t("https.trust.rotate")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}
