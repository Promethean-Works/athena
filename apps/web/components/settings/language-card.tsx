"use client"

import { useTranslation } from "react-i18next"

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
import { Field, FieldLabel } from "@workspace/ui/components/field"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"

import { useAppearance } from "@/components/settings/appearance-provider"
import { LANGUAGES } from "@/lib/i18n"

/** The UI language, saved with the rest of the account's appearance settings. */
export function LanguageCard() {
  const { t } = useTranslation("settings")
  const { appearance, update } = useAppearance()
  const items = [
    { value: "auto", label: t("language.auto") },
    // Each language is named in itself, so it can be found when the UI is in another one.
    ...LANGUAGES.map((l) => ({ value: l.code as string, label: l.name })),
  ]
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("language.title")}</CardTitle>
        <CardDescription>{t("language.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <Field>
          <FieldLabel htmlFor="language">{t("language.label")}</FieldLabel>
          <Select
            items={items}
            value={appearance.language}
            onValueChange={(v) =>
              v && update((a) => ({ ...a, language: v as string }))
            }
          >
            <SelectTrigger id="language" className="w-full sm:w-72">
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
        </Field>
      </CardContent>
    </Card>
  )
}
