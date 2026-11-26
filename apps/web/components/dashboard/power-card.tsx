"use client"

import { useTranslation } from "react-i18next"
import { type ParseKeys } from "i18next"
import { PlugZapIcon } from "lucide-react"

import { Badge } from "@workspace/ui/components/badge"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"

import { useHostStats } from "@/components/dashboard/host-stats-provider"

type Flag = "under_voltage" | "freq_capped" | "throttled" | "soft_temp_limit"

const FLAGS: {
  id: Flag
  label: ParseKeys<"dashboard">
  hint: ParseKeys<"dashboard">
}[] = [
  {
    id: "under_voltage",
    label: "power.flags.underVoltage.label",
    hint: "power.flags.underVoltage.hint",
  },
  {
    id: "throttled",
    label: "power.flags.throttled.label",
    hint: "power.flags.throttled.hint",
  },
  {
    id: "freq_capped",
    label: "power.flags.freqCapped.label",
    hint: "power.flags.freqCapped.hint",
  },
  {
    id: "soft_temp_limit",
    label: "power.flags.softTempLimit.label",
    hint: "power.flags.softTempLimit.hint",
  },
]

/** Raspberry Pi power and throttling flags. Rendered only where the host reports them. */
export function PowerCard() {
  const { t } = useTranslation("dashboard")
  const { host } = useHostStats()
  const power = host?.power
  if (!power) return null
  const now = FLAGS.filter((f) => power.now.includes(f.id))
  const earlier = FLAGS.filter(
    (f) => power.since_boot.includes(f.id) && !power.now.includes(f.id)
  )
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <PlugZapIcon className="size-4 text-muted-foreground" />
          {t("power.title")}
        </CardTitle>
        <CardDescription>{t("power.description")}</CardDescription>
        <CardAction>
          <Badge variant={now.length > 0 ? "destructive" : "secondary"}>
            {now.length > 0 ? t("power.problemNow") : t("power.ok")}
          </Badge>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        {now.map((f) => (
          <div key={f.id}>
            <p className="font-medium text-destructive">{t("power.flagNow", { label: t(f.label) })}</p>
            <p className="text-muted-foreground">{t(f.hint)}</p>
          </div>
        ))}
        {earlier.map((f) => (
          <div key={f.id}>
            <p className="font-medium">{t("power.flagSinceBoot", { label: t(f.label) })}</p>
            <p className="text-muted-foreground">{t(f.hint)}</p>
          </div>
        ))}
        {now.length === 0 && earlier.length === 0 && (
          <p className="text-muted-foreground">{t("power.none")}</p>
        )}
      </CardContent>
    </Card>
  )
}
