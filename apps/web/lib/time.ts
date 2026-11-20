/**
 * Reads a server timestamp. Some routes send UTC without an offset
 * ("2026-11-20T10:00:00"), which `new Date` would read as local time.
 */
export function parseServerTime(value: string): Date {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`)
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["day", 86400],
  ["hour", 3600],
  ["minute", 60],
  ["second", 1],
]

const relative = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" })

/** "3 minutes ago", "in 2 hours", "now". */
export function formatRelative(date: Date, now = Date.now()): string {
  const seconds = Math.round((date.getTime() - now) / 1000)
  if (Math.abs(seconds) < 30) return "now"
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size || unit === "second") {
      return relative.format(Math.round(seconds / size), unit)
    }
  }
  return "now"
}
