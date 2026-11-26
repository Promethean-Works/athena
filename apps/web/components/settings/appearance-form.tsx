"use client"

import * as React from "react"
import type { TFunction } from "i18next"
import { Trans, useTranslation } from "react-i18next"
import {
  CheckIcon,
  CopyIcon,
  MonitorIcon,
  MoonIcon,
  SunIcon,
} from "lucide-react"

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
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@workspace/ui/components/field"
import { Input } from "@workspace/ui/components/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import { toast } from "@workspace/ui/components/toast"
import {
  ToggleGroup,
  ToggleGroupItem,
} from "@workspace/ui/components/toggle-group"

import { LanguageCard } from "@/components/settings/language-card"
import { useAppearance } from "@/components/settings/appearance-provider"
import {
  type Appearance,
  BASES,
  CHARTS,
  FONTS,
  fromPresetCode,
  label,
  RADII,
  THEMES,
  toPresetCode,
  withBase,
} from "@/lib/appearance"

/** The label of a radius step; an id the app doesn't know falls back to its name. */
function radiusLabel(id: string, t: TFunction<"settings">): string {
  switch (id) {
    case "default":
      return t("appearance.radius.default")
    case "none":
      return t("appearance.radius.none")
    case "small":
      return t("appearance.radius.small")
    case "medium":
      return t("appearance.radius.medium")
    case "large":
      return t("appearance.radius.large")
    default:
      return label(id)
  }
}

type Option = { id: string; label: string; swatch?: string }

/** A single-choice row of swatch toggles. Clicking the selected one keeps it selected. */
function SwatchPicker({
  id,
  options,
  value,
  onChange,
}: {
  id: string
  options: Option[]
  value: string
  onChange: (value: string) => void
}) {
  return (
    <ToggleGroup
      aria-labelledby={id}
      value={[value]}
      onValueChange={(v: string[]) => v[0] && onChange(v[0])}
      variant="outline"
      size="sm"
      spacing={2}
      className="flex-wrap"
    >
      {options.map((o) => (
        <ToggleGroupItem key={o.id} value={o.id} aria-label={o.label}>
          {o.swatch ? (
            <span
              aria-hidden
              className="size-3.5 shrink-0 rounded-full border border-border"
              style={{ background: o.swatch }}
            />
          ) : null}
          {o.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}

function FontSelect({
  id,
  value,
  onChange,
  inherit,
}: {
  id: string
  value: string
  onChange: (value: string) => void
  inherit?: boolean
}) {
  const { t } = useTranslation("settings")
  const items = [
    ...(inherit
      ? [{ value: "inherit", label: t("appearance.type.sameAsBody") }]
      : []),
    ...FONTS.map((f) => ({ value: f, label: label(f) })),
  ]
  return (
    <Select
      items={items}
      value={value}
      onValueChange={(v) => v && onChange(v as string)}
    >
      <SelectTrigger id={id} className="w-full sm:w-72">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {items.map((item) => (
            <SelectItem
              key={item.value}
              value={item.value}
              // Each option is shown in its own font (fetched the first time it's seen).
              style={
                item.value === "inherit"
                  ? undefined
                  : { fontFamily: `var(--font-${item.value})` }
              }
            >
              {item.label}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  )
}

function PresetCode({
  appearance,
  update,
}: {
  appearance: Appearance
  update: (next: Appearance) => void
}) {
  const { t } = useTranslation("settings")
  const code = toPresetCode(appearance)
  const [input, setInput] = React.useState("")
  const [error, setError] = React.useState<string | null>(null)
  const [copied, setCopied] = React.useState(false)

  async function copy() {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      toast.add({ type: "error", title: t("appearance.preset.copyFailed") })
    }
  }

  function apply(event: React.FormEvent) {
    event.preventDefault()
    const result = fromPresetCode(input, appearance)
    if (!result) {
      setError(t("appearance.preset.invalid"))
      return
    }
    setError(null)
    setInput("")
    update(result.appearance)
    toast.add({
      type: result.ignored.length ? "warning" : "success",
      title: t("appearance.preset.applied", { code: input.trim() }),
      description: result.ignored.length
        ? t("appearance.preset.ignored", {
            parts: result.ignored.join(", "),
          })
        : undefined,
    })
  }

  return (
    <FieldGroup>
      <Field>
        <FieldLabel htmlFor="preset-current">
          {t("appearance.preset.current")}
        </FieldLabel>
        <div className="flex gap-2">
          <Input
            id="preset-current"
            value={code}
            readOnly
            className="font-mono sm:w-56"
          />
          <Button type="button" variant="outline" onClick={copy}>
            {copied ? (
              <CheckIcon data-icon="inline-start" />
            ) : (
              <CopyIcon data-icon="inline-start" />
            )}
            {copied
              ? t("appearance.preset.copied")
              : t("appearance.preset.copy")}
          </Button>
        </div>
        <FieldDescription>
          <Trans
            i18nKey="appearance.preset.use"
            ns="settings"
            values={{ code }}
            components={{ code: <code /> }}
          />
        </FieldDescription>
      </Field>
      <form onSubmit={apply}>
        <Field data-invalid={error ? true : undefined}>
          <FieldLabel htmlFor="preset-import">
            {t("appearance.preset.apply")}
          </FieldLabel>
          <div className="flex gap-2">
            <Input
              id="preset-import"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="b0"
              className="font-mono sm:w-56"
              aria-invalid={error ? true : undefined}
              autoComplete="off"
            />
            <Button type="submit" variant="outline" disabled={!input.trim()}>
              {t("appearance.preset.applyButton")}
            </Button>
          </div>
          {error ? <FieldError>{error}</FieldError> : null}
          <FieldDescription>
            <Trans
              i18nKey="appearance.preset.fill"
              ns="settings"
              components={{
                link: (
                  <a
                    href="https://ui.shadcn.com/create"
                    target="_blank"
                    rel="noreferrer"
                    className="underline underline-offset-4"
                  />
                ),
              }}
            />
          </FieldDescription>
        </Field>
      </form>
    </FieldGroup>
  )
}

/** Settings → Appearance: every change applies to the whole UI at once and is saved. */
export function AppearanceForm() {
  const { t } = useTranslation("settings")
  const { appearance, update, saving } = useAppearance()
  const set = (patch: Partial<Appearance>) =>
    update({ ...appearance, ...patch })

  const base = BASES.find((b) => b.id === appearance.base_color)
  const themeOptions: Option[] = [
    {
      id: appearance.base_color,
      label: t("appearance.colors.matchBase"),
      swatch: base?.swatch,
    },
    ...THEMES.filter((th) => !th.matchesBase).map((th) => ({
      id: th.id,
      label: label(th.id),
      swatch: th.swatch,
    })),
  ]
  const baseChart = CHARTS.find((c) => c.id === appearance.base_color)
  const chartOptions: Option[] = [
    { id: "neutral", label: t("appearance.colors.matchTheme") },
    ...(baseChart
      ? [
          {
            id: baseChart.id,
            label: t("appearance.colors.base"),
            swatch: baseChart.swatch,
          },
        ]
      : []),
    ...CHARTS.filter((c) => !c.matchesBase).map((c) => ({
      id: c.id,
      label: label(c.id),
      swatch: c.swatch,
    })),
  ]

  return (
    <div className="flex flex-col gap-4 md:gap-6">
      <LanguageCard />
      <Card>
        <CardHeader>
          <CardTitle>{t("appearance.colors.title")}</CardTitle>
          <CardDescription>
            {saving
              ? t("appearance.colors.saving")
              : t("appearance.colors.description")}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <FieldGroup>
            <Field>
              <FieldLabel id="mode-label">
                {t("appearance.mode.label")}
              </FieldLabel>
              <ToggleGroup
                aria-labelledby="mode-label"
                value={[appearance.mode]}
                onValueChange={(v: string[]) =>
                  v[0] && set({ mode: v[0] as Appearance["mode"] })
                }
                variant="outline"
                size="sm"
                spacing={0}
              >
                <ToggleGroupItem value="light">
                  <SunIcon data-icon="inline-start" />
                  {t("appearance.mode.light")}
                </ToggleGroupItem>
                <ToggleGroupItem value="dark">
                  <MoonIcon data-icon="inline-start" />
                  {t("appearance.mode.dark")}
                </ToggleGroupItem>
                <ToggleGroupItem value="system">
                  <MonitorIcon data-icon="inline-start" />
                  {t("appearance.mode.system")}
                </ToggleGroupItem>
              </ToggleGroup>
            </Field>
            <Field>
              <FieldLabel id="base-label">
                {t("appearance.colors.baseColor")}
              </FieldLabel>
              <SwatchPicker
                id="base-label"
                options={BASES.map((b) => ({
                  id: b.id,
                  label: label(b.id),
                  swatch: b.swatch,
                }))}
                value={appearance.base_color}
                onChange={(id) => update((current) => withBase(current, id))}
              />
              <FieldDescription>
                {t("appearance.colors.baseHint")}
              </FieldDescription>
            </Field>
            <Field>
              <FieldLabel id="theme-label">
                {t("appearance.colors.theme")}
              </FieldLabel>
              <SwatchPicker
                id="theme-label"
                options={themeOptions}
                value={appearance.theme}
                onChange={(id) => set({ theme: id })}
              />
              <FieldDescription>
                {t("appearance.colors.themeHint")}
              </FieldDescription>
            </Field>
            <Field>
              <FieldLabel id="chart-label">
                {t("appearance.colors.charts")}
              </FieldLabel>
              <SwatchPicker
                id="chart-label"
                options={chartOptions}
                value={appearance.chart_color}
                onChange={(id) => set({ chart_color: id })}
              />
            </Field>
          </FieldGroup>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("appearance.type.title")}</CardTitle>
        </CardHeader>
        <CardContent>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="font">
                {t("appearance.type.font")}
              </FieldLabel>
              <FontSelect
                id="font"
                value={appearance.font}
                onChange={(font) => set({ font })}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="font-heading">
                {t("appearance.type.headingFont")}
              </FieldLabel>
              <FontSelect
                id="font-heading"
                inherit
                value={appearance.font_heading}
                onChange={(font_heading) => set({ font_heading })}
              />
            </Field>
            <Field>
              <FieldLabel id="radius-label">
                {t("appearance.type.radius")}
              </FieldLabel>
              <SwatchPicker
                id="radius-label"
                options={RADII.map((r) => ({
                  id: r.id,
                  label: `${radiusLabel(r.id, t)} · ${r.value}`,
                }))}
                value={appearance.radius}
                onChange={(radius) => set({ radius })}
              />
            </Field>
            <Field>
              <FieldLabel>{t("appearance.type.style")}</FieldLabel>
              <p className="text-sm">
                {t("appearance.type.styleValue")}{" "}
                <span className="text-muted-foreground">
                  · {t("appearance.type.styleSoon")}
                </span>
              </p>
            </Field>
          </FieldGroup>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("appearance.preset.title")}</CardTitle>
          <CardDescription>
            {t("appearance.preset.description")}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <PresetCode appearance={appearance} update={update} />
        </CardContent>
      </Card>
    </div>
  )
}
