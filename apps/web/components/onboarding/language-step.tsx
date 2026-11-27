"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"

import { api, errorMessage } from "@workspace/api-client"
import { Field, FieldError, FieldLabel } from "@workspace/ui/components/field"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"

import { StepCard } from "@/components/onboarding/step-card"
import { LANGUAGES, setLanguage } from "@/lib/i18n"

/** Saves the language in the account's appearance (the same setting as Settings). */
export function LanguageStep({ onNext }: { onNext: () => void }) {
  const { t } = useTranslation("onboarding")
  const [value, setValue] = React.useState("auto")
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const items = [
    { value: "auto", label: t("language.auto") },
    ...LANGUAGES.map((l) => ({ value: l.code as string, label: l.name })),
  ]

  React.useEffect(() => {
    void api.GET("/api/settings/appearance").then(({ data }) => {
      if (data) setValue(data.language)
    })
  }, [])

  async function save() {
    setBusy(true)
    setError(null)
    const current = await api.GET("/api/settings/appearance")
    if (!current.data) {
      setBusy(false)
      setError(errorMessage(current.error, t("saveFailed")))
      return
    }
    const { error: err } = await api.PUT("/api/settings/appearance", {
      body: { ...current.data, language: value },
    })
    setBusy(false)
    if (err) return setError(errorMessage(err, t("saveFailed")))
    onNext()
  }

  return (
    <StepCard
      title={t("language.title")}
      description={t("language.description")}
      onContinue={save}
      onSkip={onNext}
      busy={busy}
    >
      <Field>
        <FieldLabel htmlFor="onboarding-language">
          {t("language.label")}
        </FieldLabel>
        <Select
          items={items}
          value={value}
          onValueChange={(v) => {
            if (!v) return
            setValue(v as string)
            void setLanguage(v as string) // preview at once
          }}
        >
          <SelectTrigger id="onboarding-language" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {items.map((item) => (
                <SelectItem key={item.value} value={item.value}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        {error && <FieldError>{error}</FieldError>}
      </Field>
    </StepCard>
  )
}
