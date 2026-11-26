"use client"

import * as React from "react"
import { useRouter } from "next/navigation"

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

type Step = "choose" | "account" | "ai" | "restore"

export default function SetupPage() {
  const router = useRouter()
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
          <CardTitle className="text-xl">Restore from a backup</CardTitle>
          <CardDescription>
            Pick the backup repository and the Athena snapshot to restore from.
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
                setError(errorMessage(err, "Restore failed"))
                return
              }
              setCsrfToken(null)
              router.replace("/login/")
            }}
          >
            <FieldGroup>
              <FieldLabel>Repository location</FieldLabel>
              <Input
                required
                value={location}
                onChange={(event) => setLocation(event.target.value)}
                placeholder="Local folder or <remote>:<path>"
              />
              <FieldDescription>
                The local folder where the backup repository lives.
              </FieldDescription>
            </FieldGroup>
            <FieldGroup>
              <FieldLabel>Repository password</FieldLabel>
              <Input required type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
              <FieldDescription>
                From the recovery kit made when the backup was created.
              </FieldDescription>
            </FieldGroup>
            <FieldGroup>
              <FieldLabel>Athena snapshot</FieldLabel>
              <Select value={versionId} onValueChange={(value) => setVersionId(value ?? "")} required disabled={versions.length === 0}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {versions.length === 0 ? (
                    <SelectItem disabled>Loading snapshots…</SelectItem>
                  ) : (
                    versions.map((v) => (
                      <SelectItem key={v.id} value={v.id}>
                        {v.id.slice(0, 8)} — {new Date(v.time).toLocaleString()}
                      </SelectItem>
                    ))
                  )}
                </SelectContent>
              </Select>
              <FieldDescription>
                Pick an `athena` snapshot. The newest is chosen by default.
              </FieldDescription>
            </FieldGroup>
            <CardFooter className="flex flex-col sm:flex-row gap-2">
              <Button type="submit" disabled={pending}>
                Restore Athena
              </Button>
              <Button type="button" variant="outline" onClick={() => setStep("choose")}>
                Back
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
          <CardTitle className="text-xl">Welcome to Athena</CardTitle>
          <CardDescription>
            Create the administrator account for this server.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {error && <FieldError>{error}</FieldError>}
          <CredentialsForm
            mode="setup"
            submitLabel="Create account"
            onSubmit={async (credentials) => {
              const { data, error } = await api.POST("/api/auth/setup", {
                body: credentials,
              })
              if (!data) return errorMessage(error, "Couldn't create the account")
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
        <CardTitle className="text-xl">Welcome to Athena</CardTitle>
        <CardDescription>
          Create the administrator account for this server.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid gap-3 sm:grid-cols-2">
          <Button
            className="w-full"
            onClick={() => setStep("account")}
            disabled={pending}
          >
            Create account
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
                  setError(errorMessage(err, "Couldn't list backups"))
                  return
                }
                setVersions(data ?? [])
                setStep("restore")
              })
            }}
            disabled={pending}
          >
            Restore from a backup
          </Button>
        </div>
        {error && <FieldError>{error}</FieldError>}
        {pending && <Spinner />}
      </CardContent>
    </Card>
  )
}
