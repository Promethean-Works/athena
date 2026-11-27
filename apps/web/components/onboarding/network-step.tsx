"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"

import { api, errorMessage } from "@workspace/api-client"
import { Alert, AlertDescription } from "@workspace/ui/components/alert"
import { Field, FieldError, FieldLabel } from "@workspace/ui/components/field"
import { Input } from "@workspace/ui/components/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"

import { StepCard } from "@/components/onboarding/step-card"

type Host = "0.0.0.0" | "127.0.0.1"

/** Saves where Athena listens (`server.host` and `server.port`); applies on restart. */
export function NetworkStep({ onNext }: { onNext: () => void }) {
  const { t } = useTranslation("onboarding")
  const [host, setHost] = React.useState<Host>("0.0.0.0")
  const [port, setPort] = React.useState("")
  const [loaded, setLoaded] = React.useState(false)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [restart, setRestart] = React.useState(false)
  const items = [
    { value: "0.0.0.0", label: t("network.hostAll") },
    { value: "127.0.0.1", label: t("network.hostLocal") },
  ]

  React.useEffect(() => {
    void api.GET("/api/onboarding").then(({ data, error: err }) => {
      if (data) {
        setHost(data.network.host as Host)
        setPort(String(data.network.port))
        setLoaded(true)
      } else setError(errorMessage(err, t("network.loadFailed")))
    })
  }, [t])

  const portNumber = Number(port)
  const valid = Number.isInteger(portNumber) && portNumber >= 1 && portNumber <= 65535

  async function save() {
    setBusy(true)
    setError(null)
    const { data, error: err } = await api.PUT("/api/onboarding/network", {
      body: { host, port: portNumber },
    })
    setBusy(false)
    if (!data) return setError(errorMessage(err, t("saveFailed")))
    if (data.restart_required) {
      setRestart(true) // show the note; the next click moves on
      return
    }
    onNext()
  }

  return (
    <StepCard
      title={t("network.title")}
      description={t("network.description")}
      onContinue={restart ? onNext : save}
      continueLabel={restart ? t("continue") : t("network.save")}
      onSkip={onNext}
      busy={busy}
      canContinue={loaded && (restart || valid)}
    >
      <Field>
        <FieldLabel htmlFor="net-host">{t("network.host")}</FieldLabel>
        <Select
          items={items}
          value={host}
          onValueChange={(v) => v && setHost(v as Host)}
          disabled={restart}
        >
          <SelectTrigger id="net-host" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {items.map((i) => (
                <SelectItem key={i.value} value={i.value}>
                  {i.label}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      </Field>
      <Field>
        <FieldLabel htmlFor="net-port">{t("network.port")}</FieldLabel>
        <Input
          id="net-port"
          inputMode="numeric"
          value={port}
          onChange={(e) => setPort(e.target.value)}
          aria-invalid={port !== "" && !valid}
          disabled={restart}
        />
        {port !== "" && !valid && <FieldError>{t("network.portInvalid")}</FieldError>}
      </Field>
      {error && <FieldError>{error}</FieldError>}
      {restart && (
        <Alert>
          <AlertDescription>{t("network.restart")}</AlertDescription>
        </Alert>
      )}
    </StepCard>
  )
}
