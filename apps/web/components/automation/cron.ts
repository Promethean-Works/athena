/**
 * A small cron describer for the trigger form. The server (croniter) is the real
 * validator; this only catches the common mistakes early and puts the usual
 * five-field patterns into words. Schedules run in UTC (the scheduler's clock).
 */

export const CRON_PRESETS: { label: string; expression: string }[] = [
  { label: "Every hour", expression: "0 * * * *" },
  { label: "Daily at 02:00", expression: "0 2 * * *" },
  { label: "Sundays at 03:00", expression: "0 3 * * 0" },
  { label: "Monthly on the 1st", expression: "0 4 1 * *" },
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
const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
]
const DAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]
const DAY_NAMES = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
]

type FieldSpec = {
  name: string
  min: number
  max: number
  names?: string[]
  namesStart?: number
}

const FIELDS: FieldSpec[] = [
  { name: "minute", min: 0, max: 59 },
  { name: "hour", min: 0, max: 23 },
  { name: "day of month", min: 1, max: 31 },
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
  for (const part of field.split(",")) {
    const [range = "", step, extra] = part.split("/")
    if (extra !== undefined || range === "")
      return `The ${spec.name} field "${field}" isn't valid.`
    if (step !== undefined && !/^\d+$/.test(step)) {
      return `The step "/${step}" in the ${spec.name} field must be a number.`
    }
    if (range === "*") continue
    for (const bound of range.split("-")) {
      const value = valueOf(bound, spec)
      // L, W, # and ? are croniter extensions (last day, nth weekday): leave them
      // to the server.
      if (value === null) {
        if (/^(?:\?|L|LW|\d{1,2}[LW]|[0-7]L|[0-7a-z]{1,3}#[1-5])$/i.test(bound))
          continue
        return `The ${spec.name} field "${field}" isn't valid.`
      }
      if (value < spec.min || value > spec.max) {
        return `The ${spec.name} must be between ${spec.min} and ${spec.max}.`
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
    const name = (n: number) => DAY_NAMES[n % 7]
    return b === undefined ? name(a) : `${name(a)} to ${name(b)}`
  })
  if (parts.some((p) => p === null)) return null
  return parts.join(", ")
}

function describe([minute, hour, dom, month, dow]: string[]): string {
  const rest = [dom, month, dow].every((f) => f === "*")
  if (minute === "*" && hour === "*" && rest) return "Every minute"
  const everyMinutes = /^\*\/(\d+)$/.exec(minute!)
  if (everyMinutes && hour === "*" && rest)
    return `Every ${everyMinutes[1]} minutes`
  if (isNumber(minute!) && hour === "*" && rest) {
    return Number(minute) === 0
      ? "Every hour, on the hour"
      : `Every hour at minute ${Number(minute)}`
  }
  const everyHours = /^\*\/(\d+)$/.exec(hour!)
  if (isNumber(minute!) && everyHours && rest) {
    return `Every ${everyHours[1]} hours at minute ${Number(minute)}`
  }
  if (!isNumber(minute!) || !isNumber(hour!)) return "Custom schedule"
  const at = `at ${pad(hour!)}:${pad(minute!)}`
  if (dom === "*" && month === "*") {
    if (dow === "*") return `Every day ${at}`
    const days = dayList(dow!)
    return days ? `Every ${days} ${at}` : "Custom schedule"
  }
  if (isNumber(dom!) && month === "*" && dow === "*") {
    return `On day ${Number(dom)} of every month ${at}`
  }
  const monthIndex = valueOf(month!, FIELDS[3]!)
  if (isNumber(dom!) && monthIndex !== null && dow === "*") {
    return `Every year on ${MONTH_NAMES[monthIndex - 1]} ${Number(dom)} ${at}`
  }
  return "Custom schedule"
}

/** Check a cron expression and describe it in words (times in UTC). */
export function checkCron(expression: string): CronCheck {
  const trimmed = expression.trim()
  if (!trimmed)
    return { ok: false, error: "Enter a cron expression or pick a preset." }
  const normalized = ALIASES[trimmed.toLowerCase()] ?? trimmed
  const fields = normalized.split(/\s+/)
  if (fields.length !== 5) {
    return {
      ok: false,
      error: `Use five fields (minute hour day month weekday); this has ${fields.length}.`,
    }
  }
  for (const [i, field] of fields.entries()) {
    const error = checkField(field, FIELDS[i]!)
    if (error) return { ok: false, error }
  }
  return { ok: true, description: `${describe(fields)} (UTC)` }
}
