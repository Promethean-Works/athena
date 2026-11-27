/**
 * A small cron describer for the trigger form. The server (croniter) is the real
 * validator; this only catches the common mistakes early and puts the usual
 * five-field patterns into words. Schedules run in UTC (the scheduler's clock).
 */

import type { ParseKeys } from "i18next"

import i18n, { currentLocale } from "@/lib/i18n"

/** `labelKey` is translated when shown, never at module load. */
export const CRON_PRESETS: {
  labelKey: ParseKeys<"automation">
  expression: string
}[] = [
  { labelKey: "cron.presets.hourly", expression: "0 * * * *" },
  { labelKey: "cron.presets.daily", expression: "0 2 * * *" },
  { labelKey: "cron.presets.sundays", expression: "0 3 * * 0" },
  { labelKey: "cron.presets.monthly", expression: "0 4 1 * *" },
]

const ALIASES: Record<string, string> = {
  "@hourly": "0 * * * *",
  "@daily": "0 0 * * *",
  "@midnight": "0 0 * * *",
  "@weekly": "0 0 * * 0",
  "@monthly": "0 0 1 * *",
  "@yearly": "0 0 1 1 *",
  "@annually": "0 0 1 1 *",
}

const MONTHS = [
  "jan",
  "feb",
  "mar",
  "apr",
  "may",
  "jun",
  "jul",
  "aug",
  "sep",
  "oct",
  "nov",
  "dec",
]
const DAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]

/** Month name (0 = January) in the UI language. */
function monthName(index: number): string {
  return new Date(Date.UTC(2024, index, 1)).toLocaleDateString(currentLocale(), {
    month: "long",
    timeZone: "UTC",
  })
}

/** Weekday name (0 = Sunday) in the UI language. */
function dayName(index: number): string {
  // 7 January 2024 was a Sunday.
  return new Date(Date.UTC(2024, 0, 7 + index)).toLocaleDateString(
    currentLocale(),
    { weekday: "long", timeZone: "UTC" }
  )
}

type FieldSpec = {
  name: "minute" | "hour" | "dayOfMonth" | "month" | "weekday"
  min: number
  max: number
  names?: string[]
  namesStart?: number
}

const FIELDS: FieldSpec[] = [
  { name: "minute", min: 0, max: 59 },
  { name: "hour", min: 0, max: 23 },
  { name: "dayOfMonth", min: 1, max: 31 },
  { name: "month", min: 1, max: 12, names: MONTHS, namesStart: 1 },
  { name: "weekday", min: 0, max: 7, names: DAYS, namesStart: 0 },
]

export type CronCheck =
  { ok: true; description: string } | { ok: false; error: string }

/** A number or a month/day name as a number, or null when it's something else. */
function valueOf(token: string, spec: FieldSpec): number | null {
  if (/^\d+$/.test(token)) return Number(token)
  const index = spec.names?.indexOf(token.toLowerCase()) ?? -1
  return index >= 0 ? index + (spec.namesStart ?? 0) : null
}

/** An error message for a field, or null when it looks fine (or is too fancy to check). */
function checkField(field: string, spec: FieldSpec): string | null {
  const fieldName = i18n.t(`automation:cron.fields.${spec.name}`)
  for (const part of field.split(",")) {
    const [range = "", step, extra] = part.split("/")
    if (extra !== undefined || range === "")
      return i18n.t("automation:cron.errors.invalidField", {
        field: fieldName,
        value: field,
      })
    if (step !== undefined && !/^\d+$/.test(step)) {
      return i18n.t("automation:cron.errors.invalidStep", {
        step,
        field: fieldName,
      })
    }
    if (range === "*") continue
    for (const bound of range.split("-")) {
      const value = valueOf(bound, spec)
      // L, W, # and ? are croniter extensions (last day, nth weekday): leave them
      // to the server.
      if (value === null) {
        if (/^(?:\?|L|LW|\d{1,2}[LW]|[0-7]L|[0-7a-z]{1,3}#[1-5])$/i.test(bound))
          continue
        return i18n.t("automation:cron.errors.invalidField", {
          field: fieldName,
          value: field,
        })
      }
      if (value < spec.min || value > spec.max) {
        return i18n.t("automation:cron.errors.outOfRange", {
          field: fieldName,
          min: spec.min,
          max: spec.max,
        })
      }
    }
  }
  return null
}

const isNumber = (s: string) => /^\d+$/.test(s)
const pad = (n: string) => n.padStart(2, "0")

function dayList(field: string): string | null {
  const parts = field.split(",").map((part) => {
    const [from, to, extra] = part.split("-")
    if (extra !== undefined || part.includes("/")) return null
    const a = from === undefined ? null : valueOf(from, FIELDS[4]!)
    const b = to === undefined ? undefined : valueOf(to, FIELDS[4]!)
    if (a === null || b === null) return null
    return b === undefined
      ? dayName(a % 7)
      : i18n.t("automation:cron.dayRange", {
          from: dayName(a % 7),
          to: dayName(b % 7),
        })
  })
  if (parts.some((p) => p === null)) return null
  return parts.join(", ")
}

function describe([minute, hour, dom, month, dow]: string[]): string {
  const custom = i18n.t("automation:cron.custom")
  const rest = [dom, month, dow].every((f) => f === "*")
  if (minute === "*" && hour === "*" && rest)
    return i18n.t("automation:cron.everyMinute")
  const everyMinutes = /^\*\/(\d+)$/.exec(minute!)
  if (everyMinutes && hour === "*" && rest)
    return i18n.t("automation:cron.everyMinutes", {
      count: Number(everyMinutes[1]),
    })
  if (isNumber(minute!) && hour === "*" && rest) {
    return Number(minute) === 0
      ? i18n.t("automation:cron.everyHourOnTheHour")
      : i18n.t("automation:cron.everyHourAtMinute", { minute: Number(minute) })
  }
  const everyHours = /^\*\/(\d+)$/.exec(hour!)
  if (isNumber(minute!) && everyHours && rest) {
    return i18n.t("automation:cron.everyHoursAtMinute", {
      count: Number(everyHours[1]),
      minute: Number(minute),
    })
  }
  if (!isNumber(minute!) || !isNumber(hour!)) return custom
  const time = `${pad(hour!)}:${pad(minute!)}`
  if (dom === "*" && month === "*") {
    if (dow === "*") return i18n.t("automation:cron.everyDay", { time })
    const days = dayList(dow!)
    return days
      ? i18n.t("automation:cron.everyWeekdays", { days, time })
      : custom
  }
  if (isNumber(dom!) && month === "*" && dow === "*") {
    return i18n.t("automation:cron.onDayOfMonth", { day: Number(dom), time })
  }
  const monthIndex = valueOf(month!, FIELDS[3]!)
  if (isNumber(dom!) && monthIndex !== null && dow === "*") {
    return i18n.t("automation:cron.everyYear", {
      month: monthName(monthIndex - 1),
      day: Number(dom),
      time,
    })
  }
  return custom
}

/** Check a cron expression and describe it in words (times in UTC). */
export function checkCron(expression: string): CronCheck {
  const trimmed = expression.trim()
  if (!trimmed)
    return { ok: false, error: i18n.t("automation:cron.errors.empty") }
  const normalized = ALIASES[trimmed.toLowerCase()] ?? trimmed
  const fields = normalized.split(/\s+/)
  if (fields.length !== 5) {
    return {
      ok: false,
      error: i18n.t("automation:cron.errors.fieldCount", {
        count: fields.length,
      }),
    }
  }
  for (const [i, field] of fields.entries()) {
    const error = checkField(field, FIELDS[i]!)
    if (error) return { ok: false, error }
  }
  return {
    ok: true,
    description: i18n.t("automation:cron.utc", {
      description: describe(fields),
    }),
  }
}
