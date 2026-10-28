import { formatDate } from '../dates'
import { formatAmount } from '../money'
import type { CellValue, ReportColumn } from '../reports/types'

/** Text form of a cell, identical in the screen view, PDF and print. */
export function cellText(col: ReportColumn, v: CellValue): string {
  if (v === null || v === undefined || v === '') return ''
  if (col.type === 'money') return formatAmount(Number(v))
  if (col.type === 'date') return formatDate(String(v))
  return String(v)
}

export function safeFileName(s: string): string {
  return s.replace(/[^a-z0-9\-_.]+/gi, '_').replace(/_+/g, '_').replace(/^_|_$/g, '').slice(0, 80)
}
