"use client"

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

const FLAGS: { id: Flag; label: string; hint: string }[] = [
  {
    id: "under_voltage",
    label: "Under-voltage",
    hint: "The power supply or cable can't keep up. Use the official supply and a short, thick cable.",
  },
  {
    id: "throttled",
    label: "Throttled",
    hint: "The CPU is slowed down to protect itself.",
  },
  {
    id: "freq_capped",
    label: "Frequency capped",
    hint: "The firmware lowered the maximum CPU speed.",
  },
  {
    id: "soft_temp_limit",
    label: "Soft temperature limit",
    hint: "The CPU is close to its temperature limit. Check cooling.",
  },
]

/** Raspberry Pi power and throttling flags. Rendered only where the host reports them. */
export function PowerCard() {
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
          Power
        </CardTitle>
        <CardDescription>Raspberry Pi power and throttling</CardDescription>
        <CardAction>
          <Badge variant={now.length > 0 ? "destructive" : "secondary"}>
            {now.length > 0 ? "Problem now" : "OK"}
          </Badge>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        {now.map((f) => (
          <div key={f.id}>
            <p className="font-medium text-destructive">{f.label} now</p>
            <p className="text-muted-foreground">{f.hint}</p>
          </div>
        ))}
        {earlier.map((f) => (
          <div key={f.id}>
            <p className="font-medium">{f.label} since boot</p>
            <p className="text-muted-foreground">{f.hint}</p>
          </div>
        ))}
        {now.length === 0 && earlier.length === 0 && (
          <p className="text-muted-foreground">
            No under-voltage or throttling since this server booted.
          </p>
        )}
      </CardContent>
    </Card>
  )
}
