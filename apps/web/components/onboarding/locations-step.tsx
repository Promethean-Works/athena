"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"
import { FolderIcon } from "lucide-react"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import { Field, FieldError, FieldLabel } from "@workspace/ui/components/field"
import { Input } from "@workspace/ui/components/input"
import { Button } from "@workspace/ui/components/button"
import { Spinner } from "@workspace/ui/components/spinner"
import { toast } from "@workspace/ui/components/toast"

import { StepCard } from "@/components/onboarding/step-card"

type Location = Schemas["LocationOut"]

/** Lists the folders Files can open and adds more (POST /api/files/locations). */
export function LocationsStep({ onNext }: { onNext: () => void }) {
  const { t } = useTranslation("onboarding")
  const [locations, setLocations] = React.useState<Location[] | null>(null)
  const [name, setName] = React.useState("")
  const [path, setPath] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const load = React.useCallback(async () => {
    const { data, error: err } = await api.GET("/api/files/locations")
    if (data) setLocations(data)
    else setError(errorMessage(err, t("locations.loadFailed")))
  }, [t])
  React.useEffect(() => {
    void load()
  }, [load])

  async function add(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    const { data, error: err } = await api.POST("/api/files/locations", {
      body: { name, path, users_can_open: false },
    })
    setBusy(false)
    if (!data) return setError(errorMessage(err, t("locations.addFailed")))
    toast.add({
      type: "success",
      title: t("locations.added", { name: data.name }),
    })
    setName("")
    setPath("")
    await load()
  }

  return (
    <StepCard
      title={t("locations.title")}
      description={t("locations.description")}
      onContinue={onNext}
      onSkip={onNext}
    >
      <section className="flex flex-col gap-1">
        <h3 className="text-xs font-medium text-muted-foreground">
          {t("locations.existing")}
        </h3>
        <ul className="flex flex-col divide-y rounded-lg border">
          {(locations ?? []).map((l) => (
            <li key={l.id} className="flex items-center gap-2 p-2 text-sm">
              <FolderIcon className="size-4 shrink-0 text-muted-foreground" />
              <span className="font-medium">{l.name}</span>
              <span className="min-w-0 truncate text-xs text-muted-foreground">
                {l.path}
              </span>
            </li>
          ))}
        </ul>
      </section>
      <form onSubmit={add} className="flex flex-col gap-3">
        <Field>
          <FieldLabel htmlFor="loc-name">{t("locations.name")}</FieldLabel>
          <Input
            id="loc-name"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("locations.namePlaceholder")}
          />
        </Field>
        <Field>
          <FieldLabel htmlFor="loc-path">{t("locations.path")}</FieldLabel>
          <Input
            id="loc-path"
            required
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder={t("locations.pathPlaceholder")}
          />
        </Field>
        {error && <FieldError>{error}</FieldError>}
        <Button
          type="submit"
          variant="secondary"
          className="self-start"
          disabled={busy}
        >
          {busy ? <Spinner data-icon="inline-start" /> : null}
          {t("locations.add")}
        </Button>
      </form>
    </StepCard>
  )
}
