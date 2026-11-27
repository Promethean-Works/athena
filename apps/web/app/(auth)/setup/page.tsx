"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import { useTranslation } from "react-i18next"

import { api, errorMessage, setCsrfToken } from "@workspace/api-client"
import {
  Button,
} from "@workspace/ui/components/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
import {
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldError,
} from "@workspace/ui/components/field"
import { Input } from "@workspace/ui/components/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import {
  Spinner,
} from "@workspace/ui/components/spinner"

import { CapabilitiesProvider } from "@/components/capabilities-provider"
import { CredentialsForm } from "@/components/credentials-form"
import { AiSetupStep } from "@/components/settings/ai-setup-step"
import { currentLocale } from "@/lib/i18n"

type Step = "choose" | "account" | "ai" | "restore"

export default function SetupPage() {
  const router = useRouter()
  const { t } = useTranslation("auth")
  const [step, setStep] = React.useState<Step>("choose")
  const [error, setError] = React.useState<string | null>(null)
  const [pending, setPending] = React.useState(false)
  const [location, setLocation] = React.useState("")
  const [password, setPassword] = React.useState("")
  const [versions, setVersions] = React.useState<Array<{ id: string; time: string }>>([])
  const [versionId, setVersionId] = React.useState("")

  // Setup only makes sense on first run (checked once, before the account exists).
  React.useEffect(() => {
    api.GET("/api/auth/status").then(({ data }) => {
      if (data && !data.setup_required)
        router.replace(data.user ? "/" : "/login/")
    })
  }, [router])

  if (step === "ai")
    return (
      <CapabilitiesProvider>
        <AiSetupStep onDone={() => router.replace("/")} />
      </CapabilitiesProvider>
    )

  if (step === "restore")
    return (
      <Card>
        <CardHeader className="text-center">
          <CardTitle className="text-xl">{t("setup.restore.title")}</CardTitle>
          <CardDescription>
            {t("setup.restore.description")}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {error && <FieldError>{error}</FieldError>}
          <form
            onSubmit={async (event) => {
              event.preventDefault()
              setPending(true)
              setError(null)
              const { data, error: err } = await api.POST("/api/backup/restore/athena", {
                body: { location, password, version_id: versionId },
              })
              setPending(false)
              if (!data) {
                setError(errorMessage(err, t("setup.restore.failed")))
                return
              }
              setCsrfToken(null)
              router.replace("/login/")
            }}
          >
            <FieldGroup>
              <FieldLabel>{t("setup.restore.location")}</FieldLabel>
              <Input
                required
                value={location}
                onChange={(event) => setLocation(event.target.value)}
                placeholder={t("setup.restore.locationPlaceholder")}
              />
              <FieldDescription>
                {t("setup.restore.locationHelp")}
              </FieldDescription>
            </FieldGroup>
            <FieldGroup>
              <FieldLabel>{t("setup.restore.password")}</FieldLabel>
              <Input required type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
              <FieldDescription>
                {t("setup.restore.passwordHelp")}
              </FieldDescription>
            </FieldGroup>
            <FieldGroup>
              <FieldLabel>{t("setup.restore.snapshot")}</FieldLabel>
              <Select value={versionId} onValueChange={(value) => setVersionId(value ?? "")} required disabled={versions.length === 0}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {versions.length === 0 ? (
                    <SelectItem disabled>{t("setup.restore.loadingSnapshots")}</SelectItem>
                  ) : (
                    versions.map((v) => (
                      <SelectItem key={v.id} value={v.id}>
                        {v.id.slice(0, 8)} — {new Date(v.time).toLocaleString(currentLocale())}
                      </SelectItem>
                    ))
                  )}
                </SelectContent>
              </Select>
              <FieldDescription>
                {t("setup.restore.snapshotHelp")}
              </FieldDescription>
            </FieldGroup>
            <CardFooter className="flex flex-col sm:flex-row gap-2">
              <Button type="submit" disabled={pending}>
                {t("setup.restore.submit")}
              </Button>
              <Button type="button" variant="outline" onClick={() => setStep("choose")}>
                {t("setup.restore.back")}
              </Button>
            </CardFooter>
          </form>
        </CardContent>
      </Card>
    )

  if (step === "account")
    return (
      <Card>
        <CardHeader className="text-center">
          <CardTitle className="text-xl">{t("setup.welcome")}</CardTitle>
          <CardDescription>
            {t("setup.welcomeDescription")}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {error && <FieldError>{error}</FieldError>}
          <CredentialsForm
            mode="setup"
            submitLabel={t("setup.createAccount")}
            onSubmit={async (credentials) => {
              const { data, error } = await api.POST("/api/auth/setup", {
                body: credentials,
              })
              if (!data) return errorMessage(error, t("setup.createFailed"))
              // Setup signs in; the AI step's writes need this session's token.
              setCsrfToken(data.csrf_token ?? null)
              setStep("ai")
              return null
            }}
          />
        </CardContent>
      </Card>
    )

  // step === "choose"
  return (
    <Card>
      <CardHeader className="text-center">
        <CardTitle className="text-xl">{t("setup.welcome")}</CardTitle>
        <CardDescription>
          {t("setup.welcomeDescription")}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid gap-3 sm:grid-cols-2">
          <Button
            className="w-full"
            onClick={() => setStep("account")}
            disabled={pending}
          >
            {t("setup.createAccount")}
          </Button>
          <Button
            className="w-full"
            variant="outline"
            onClick={() => {
              setPending(true)
              setError(null)
              api.GET("/api/backup/versions", {
                query: { item: "athena" },
              }).then(({ data, error: err }) => {
                setPending(false)
                if (!data) {
                  setError(errorMessage(err, t("setup.listFailed")))
                  return
                }
                setVersions(data ?? [])
                setStep("restore")
              })
            }}
            disabled={pending}
          >
            {t("setup.restoreFromBackup")}
          </Button>
        </div>
        {error && <FieldError>{error}</FieldError>}
        {pending && <Spinner />}
      </CardContent>
    </Card>
  )
}
