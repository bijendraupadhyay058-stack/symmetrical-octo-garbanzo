/**
 * All accounting dates are calendar dates in India (Asia/Kolkata) stored as
 * ISO strings "YYYY-MM-DD". Comparing these strings lexically is equivalent to
 * comparing dates, which keeps ordering exact and timezone-proof.
 */
export const APP_TIME_ZONE = 'Asia/Kolkata'

export type ISODate = string

const isoFmt = new Intl.DateTimeFormat('en-CA', {
  timeZone: APP_TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

/** Today's date in India, regardless of the device timezone. */
export function todayIST(now: Date = new Date()): ISODate {
  return isoFmt.format(now)
}

export function isValidISODate(s: unknown): s is ISODate {
  if (typeof s !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(s)) return false
  const [y, m, d] = s.split('-').map(Number)
  const dt = new Date(Date.UTC(y, m - 1, d))
  return dt.getUTCFullYear() === y && dt.getUTCMonth() === m - 1 && dt.getUTCDate() === d
}

function parts(d: ISODate): [number, number, number] {
  const [y, m, day] = d.split('-').map(Number)
  return [y, m, day]
}

function fromUTC(dt: Date): ISODate {
  return dt.toISOString().slice(0, 10)
}

export function addDays(d: ISODate, n: number): ISODate {
  const [y, m, day] = parts(d)
  return fromUTC(new Date(Date.UTC(y, m - 1, day + n)))
}

export function addMonths(d: ISODate, n: number): ISODate {
  const [y, m, day] = parts(d)
  const target = new Date(Date.UTC(y, m - 1 + n, 1))
  const lastDay = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0)).getUTCDate()
  target.setUTCDate(Math.min(day, lastDay))
  return fromUTC(target)
}

/** "2026-04-02" → "02-04-2026" */
export function formatDate(d: ISODate | null | undefined): string {
  if (!d) return ''
  const [y, m, day] = d.split('-')
  return `${day}-${m}-${y}`
}

const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "2026-04" → "Apr 2026" */
export function formatMonth(ym: string): string {
  const [y, m] = ym.split('-').map(Number)
  return `${monthNames[m - 1]} ${y}`
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return ''
  return new Intl.DateTimeFormat('en-IN', {
    timeZone: APP_TIME_ZONE,
    day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(new Date(iso))
}

/** Financial year (April–March) identified by its starting calendar year. */
export function fyOf(d: ISODate): number {
  const [y, m] = parts(d)
  return m >= 4 ? y : y - 1
}

/** 2026 → "2026-27" */
export function fyLabel(fy: number): string {
  return `${fy}-${String((fy + 1) % 100).padStart(2, '0')}`
}

/** 2026 → "26-27" (used in voucher numbers) */
export function fyShort(fy: number): string {
  return `${String(fy % 100).padStart(2, '0')}-${String((fy + 1) % 100).padStart(2, '0')}`
}

export function fyRange(fy: number): DateRange {
  return { from: `${fy}-04-01`, to: `${fy + 1}-03-31` }
}

export interface DateRange {
  from: ISODate
  to: ISODate
}

export function monthRange(d: ISODate): DateRange {
  const [y, m] = parts(d)
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate()
  const mm = String(m).padStart(2, '0')
  return { from: `${y}-${mm}-01`, to: `${y}-${mm}-${String(last).padStart(2, '0')}` }
}

/** The 12 "YYYY-MM" months of a financial year, April first. */
export function fyMonths(fy: number): string[] {
  const out: string[] = []
  for (let i = 0; i < 12; i++) {
    const m = ((3 + i) % 12) + 1
    const y = m >= 4 ? fy : fy + 1
    out.push(`${y}-${String(m).padStart(2, '0')}`)
  }
  return out
}

export function inRange(d: ISODate, r: DateRange): boolean {
  return d >= r.from && d <= r.to
}

export type PeriodPreset = 'today' | 'current_month' | 'previous_month' | 'current_fy' | 'previous_fy' | 'custom'

export function presetRange(preset: PeriodPreset, today: ISODate = todayIST(), custom?: DateRange): DateRange {
  switch (preset) {
    case 'today':
      return { from: today, to: today }
    case 'current_month':
      return monthRange(today)
    case 'previous_month':
      return monthRange(addMonths(monthRange(today).from, -1))
    case 'current_fy':
      return fyRange(fyOf(today))
    case 'previous_fy':
      return fyRange(fyOf(today) - 1)
    case 'custom':
      return custom ?? monthRange(today)
  }
}

export const presetLabels: Record<PeriodPreset, string> = {
  today: 'Today',
  current_month: 'Current Month',
  previous_month: 'Previous Month',
  current_fy: 'Current FY',
  previous_fy: 'Previous FY',
  custom: 'Custom Range',
}
