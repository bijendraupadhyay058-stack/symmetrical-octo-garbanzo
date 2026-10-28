import type { DateRange } from '../dates'
import type { PaymentMethod } from '../types'

export type CellValue = string | number | null

export interface ReportColumn {
  key: string
  label: string
  type: 'text' | 'money' | 'date' | 'number'
  /** Relative width hint for PDF output. */
  width?: number
}

export type RowStyle = 'normal' | 'heading' | 'subtotal' | 'total' | 'opening' | 'muted'

export interface ReportRow {
  cells: Record<string, CellValue>
  style?: RowStyle
  /** Transaction id, so the UI can open the entry. */
  ref?: string
}

export interface ReportSummaryItem {
  label: string
  /** paise */
  value: number
  tone?: 'income' | 'expense' | 'balance' | 'neutral'
  /** 'count' values are plain numbers, not paise. */
  kind?: 'money' | 'count'
}

export interface ReportData {
  id: ReportId
  title: string
  /** e.g. "01-04-2026 to 31-03-2027" */
  period: string
  /** Basis disclaimer, e.g. cash-basis vs accrual. */
  note?: string
  columns: ReportColumn[]
  rows: ReportRow[]
  summary?: ReportSummaryItem[]
}

export interface ReportFilters {
  range: DateRange
  clientId?: string
  categoryId?: string
  paymentMethod?: PaymentMethod
  accountId?: string
}

export type ReportId =
  | 'daily-cashbook'
  | 'monthly-cashbook'
  | 'bank-register'
  | 'income-register'
  | 'expense-register'
  | 'monthly-summary'
  | 'client-income'
  | 'service-income'
  | 'expense-category'
  | 'fy-summary'
  | 'client-outstanding'
  | 'receipts-payments'
  | 'voucher-register'
  | 'client-statement'
  | 'fee-register'
