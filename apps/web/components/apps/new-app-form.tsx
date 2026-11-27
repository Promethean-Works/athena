"use client"

import * as React from "react"
import { Trans, useTranslation } from "react-i18next"
import { useRouter } from "next/navigation"
import {
  CheckIcon,
  CircleAlertIcon,
  RocketIcon,
  UploadIcon,
  WandSparklesIcon,
} from "lucide-react"

import { api, errorMessage } from "@workspace/api-client"
import { ComposeForm } from "@/components/apps/compose-form"
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@workspace/ui/components/alert"
import { Button } from "@workspace/ui/components/button"
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@workspace/ui/components/field"
import { Input } from "@workspace/ui/components/input"
import { Spinner } from "@workspace/ui/components/spinner"
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@workspace/ui/components/tabs"
import { Textarea } from "@workspace/ui/components/textarea"
import { toast } from "@workspace/ui/components/toast"

import { useAppJobs } from "@/components/apps/use-app-jobs"

const NAME_RE = /^[a-z0-9][a-z0-9_-]{0,62}$/

const EXAMPLE = `services:
  web:
    image: nginx:1.29-alpine
    ports:
      - "8080:80"
    volumes:
      # \${ATHENA_APP_DATA} is this app's data folder on the server
      - \${ATHENA_APP_DATA}/html:/usr/share/nginx/html:ro
    restart: unless-stopped
`

function toName(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^[-_]+|[-_]+$/g, "")
    .slice(0, 63)
}

export function NewAppForm() {
  const { t } = useTranslation("apps")
  const router = useRouter()
  const [name, setName] = React.useState("")
  const [compose, setCompose] = React.useState(EXAMPLE)
  const [source, setSource] = React.useState<"compose" | "docker-run">(
    "compose"
  )
  const [tab, setTab] = React.useState<"compose" | "run">("compose")
  const [command, setCommand] = React.useState("")
  const [warnings, setWarnings] = React.useState<string[]>([])
  const [validation, setValidation] = React.useState<{
    ok: boolean
    errors: string[]
  } | null>(null)
  const [busy, setBusy] = React.useState<
    "convert" | "validate" | "deploy" | null
  >(null)
  const file = React.useRef<HTMLInputElement>(null)
  const deployedName = React.useRef("")

  const jobs = useAppJobs((ok) => {
    if (ok) {
      router.push(
        `/apps/view/?name=${encodeURIComponent(deployedName.current)}`
      )
    }
  })

  const nameError = name && !NAME_RE.test(name) ? t("new.nameInvalid") : null

  async function convert() {
    setBusy("convert")
    const { data, error } = await api.POST("/api/apps/convert", {
      body: { command },
    })
    setBusy(null)
    if (!data) {
      toast.add({
        type: "error",
        title: t("new.convertFailed"),
        description: errorMessage(error),
      })
      return
    }
    setCompose(data.compose)
    setWarnings(data.warnings)
    setSource("docker-run")
    setValidation(null)
    if (!name) setName(toName(data.service))
    setTab("compose")
  }

  async function validate() {
    setBusy("validate")
    const { data, error } = await api.POST("/api/apps/validate", {
      body: { compose },
      params: {
        query: { name: name && !nameError ? name : "athena-validate" },
      },
    })
    setBusy(null)
    setValidation(
      data ?? {
        ok: false,
        errors: [errorMessage(error, t("new.validationFailed"))],
      }
    )
  }

  async function deploy() {
    setBusy("deploy")
    deployedName.current = name
    const result = await api.POST("/api/apps", {
      body: { name, compose, source },
    })
    setBusy(null)
    jobs.show(result, t("jobs.failed.deploy", { name }))
  }

  async function upload(event: React.ChangeEvent<HTMLInputElement>) {
    const picked = event.target.files?.[0]
    if (!picked) return
    setCompose(await picked.text())
    setSource("compose")
    setWarnings([])
    setValidation(null)
    if (!name) setName(toName(picked.name.replace(/\.(ya?ml)$/i, "")))
    event.target.value = ""
  }

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <FieldGroup>
        <Field data-invalid={nameError ? true : undefined}>
          <FieldLabel htmlFor="app-name">{t("new.name")}</FieldLabel>
          <Input
            id="app-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="my-app"
            aria-invalid={nameError ? true : undefined}
            autoComplete="off"
          />
          {nameError ? (
            <FieldError>{nameError}</FieldError>
          ) : (
            <FieldDescription>{t("new.nameHelp")}</FieldDescription>
          )}
        </Field>
      </FieldGroup>

      <Tabs value={tab} onValueChange={(v) => setTab(v as "compose" | "run")}>
        <TabsList>
          <TabsTrigger value="compose">{t("new.tabCompose")}</TabsTrigger>
          <TabsTrigger value="run">{t("new.tabRun")}</TabsTrigger>
        </TabsList>

        <TabsContent value="compose" className="flex flex-col gap-4 pt-2">
          {warnings.length > 0 ? (
            <Alert>
              <CircleAlertIcon />
              <AlertTitle>{t("new.reviewConverted")}</AlertTitle>
              <AlertDescription>
                <ul className="list-disc pl-4">
                  {warnings.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              </AlertDescription>
            </Alert>
          ) : null}
          <Field>
            <div className="flex items-center justify-between gap-2">
              <FieldLabel>compose.yaml</FieldLabel>
              <Button
                variant="outline"
                size="sm"
                onClick={() => file.current?.click()}
              >
                <UploadIcon data-icon="inline-start" />
                {t("new.upload")}
              </Button>
              <input
                ref={file}
                type="file"
                accept=".yml,.yaml,application/yaml,text/yaml"
                className="hidden"
                onChange={upload}
              />
            </div>
            <ComposeForm
              value={compose}
              onChange={(value) => {
                setCompose(value)
                setValidation(null)
              }}
              ariaLabel="compose.yaml"
              minHeight="18rem"
            />
            <FieldDescription>
              <Trans
                i18nKey="new.composeHelp"
                ns="apps"
                components={{ code: <code /> }}
              />
            </FieldDescription>
          </Field>
        </TabsContent>

        <TabsContent value="run" className="flex flex-col gap-4 pt-2">
          <Field>
            <FieldLabel htmlFor="docker-run">{t("new.runLabel")}</FieldLabel>
            <Textarea
              id="docker-run"
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              placeholder="docker run -d --name jellyfin -p 8096:8096 -v /srv/media:/media jellyfin/jellyfin"
              className="min-h-32 font-mono text-xs"
            />
            <FieldDescription>{t("new.runHelp")}</FieldDescription>
          </Field>
          <div>
            <Button
              onClick={convert}
              disabled={!command.trim() || busy !== null}
            >
              {busy === "convert" ? (
                <Spinner data-icon="inline-start" />
              ) : (
                <WandSparklesIcon data-icon="inline-start" />
              )}
              {t("new.convert")}
            </Button>
          </div>
        </TabsContent>
      </Tabs>

      {validation ? (
        <Alert variant={validation.ok ? "default" : "destructive"}>
          {validation.ok ? <CheckIcon /> : <CircleAlertIcon />}
          <AlertTitle>
            {validation.ok ? t("new.valid") : t("new.invalid")}
          </AlertTitle>
          {validation.errors.length ? (
            <AlertDescription>
              <pre className="font-mono text-xs whitespace-pre-wrap">
                {validation.errors.join("\n")}
              </pre>
            </AlertDescription>
          ) : null}
        </Alert>
      ) : null}

      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          onClick={validate}
          disabled={!compose.trim() || busy !== null}
        >
          {busy === "validate" ? (
            <Spinner data-icon="inline-start" />
          ) : (
            <CheckIcon data-icon="inline-start" />
          )}
          {t("new.validate")}
        </Button>
        <Button
          onClick={deploy}
          disabled={!name || !!nameError || !compose.trim() || busy !== null}
        >
          {busy === "deploy" ? (
            <Spinner data-icon="inline-start" />
          ) : (
            <RocketIcon data-icon="inline-start" />
          )}
          {t("new.deploy")}
        </Button>
      </div>
      {jobs.dialog}
    </div>
  )
}
