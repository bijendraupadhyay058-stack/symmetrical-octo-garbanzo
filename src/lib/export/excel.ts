import type { BusinessProfile } from '../types'
import type { ReportData, RowStyle } from '../reports/types'
import { formatDateTime } from '../dates'

/** Indian grouping (12,34,567.89) in Excel. */
export const INR_NUMFMT = '[>=10000000]##\\,##\\,##\\,##0.00;[>=100000]##\\,##\\,##0.00;##,##0.00'


function excelDate(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d))
}

/**
 * Builds an .xlsx with real numeric cells (rupees with 2 decimals) and real
 * dates, so totals can be re-checked in Excel. Money is converted from integer
 * paise only at this final step.
 */
export async function reportToXlsx(report: ReportData, profile: BusinessProfile | null): Promise<Uint8Array> {
  const ExcelJS = (await import('exceljs')).default
  const wb = new ExcelJS.Workbook()
  wb.creator = 'FIN TAX PRO – CashBook'
  wb.created = new Date()
  const ws = wb.addWorksheet(report.title.slice(0, 31).replace(/[\\/*?:[\]]/g, '-'), {
    pageSetup: { orientation: report.columns.length > 6 ? 'landscape' : 'portrait', fitToPage: true, fitToWidth: 1, fitToHeight: 0, paperSize: 9 },
    views: [{ state: 'frozen', ySplit: 0 }],
  })
  const n = report.columns.length
  const line = (text: string, opts: { bold?: boolean; size?: number; color?: string; italic?: boolean } = {}) => {
    const row = ws.addRow([text])
    ws.mergeCells(row.number, 1, row.number, n)
    row.getCell(1).font = { bold: opts.bold, size: opts.size ?? 11, italic: opts.italic, color: opts.color ? { argb: opts.color } : undefined }
    row.getCell(1).alignment = { wrapText: true, vertical: 'top' }
  }
  line(profile?.name || 'FIN TAX PRO', { bold: true, size: 14, color: 'FF0B2545' })
  if (profile?.address) line(profile.address, { size: 9 })
  line(report.title, { bold: true, size: 12 })
  line(`Period: ${report.period}`, { size: 10 })
  if (report.note) {
    line(report.note, { italic: true, size: 9, color: 'FF555555' })
    ws.getRow(ws.rowCount).height = 30
  }
  ws.addRow([])

  const header = ws.addRow(report.columns.map((c) => (c.type === 'money' ? `${c.label} (₹)` : c.label)))
  header.eachCell((cell) => {
    cell.font = { bold: true, color: { argb: 'FFFFFFFF' } }
    cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF0B2545' } }
    cell.alignment = { vertical: 'middle', wrapText: true }
    cell.border = { bottom: { style: 'thin' } }
  })
  ws.views = [{ state: 'frozen', ySplit: header.number }]

  const fills: Partial<Record<RowStyle, string>> = { heading: 'FFE8EEF6', subtotal: 'FFF1F4F8', total: 'FFDCE6F2', opening: 'FFF7F9FC' }
  for (const r of report.rows) {
    const values = report.columns.map((c) => {
      const v = r.cells[c.key]
      if (v === null || v === undefined || v === '') return null
      if (c.type === 'money') return Number(v) / 100
      if (c.type === 'date') return excelDate(String(v))
      if (c.type === 'number') return Number(v)
      return String(v)
    })
    const row = ws.addRow(values)
    report.columns.forEach((c, i) => {
      const cell = row.getCell(i + 1)
      if (c.type === 'money') { cell.numFmt = INR_NUMFMT; cell.alignment = { horizontal: 'right' } }
      if (c.type === 'date') cell.numFmt = 'dd-mm-yyyy'
      const style = r.style ?? 'normal'
      if (style !== 'normal' && style !== 'muted') cell.font = { bold: true }
      if (style === 'muted') cell.font = { color: { argb: 'FF888888' }, italic: true }
      const fill = fills[style]
      if (fill) cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: fill } }
    })
  }
  report.columns.forEach((c, i) => {
    ws.getColumn(i + 1).width = c.type === 'money' ? 16 : c.type === 'date' ? 12 : Math.max(10, Math.round((c.width ?? 1.2) * 14))
  })
  ws.addRow([])
  line(`Generated on ${formatDateTime(new Date().toISOString())} by FIN TAX PRO – CashBook`, { size: 8, color: 'FF888888' })
  const buf = await wb.xlsx.writeBuffer()
  return new Uint8Array(buf as ArrayBuffer)
}

/** Flat export of every transaction (for "Export All Transactions"). */
export async function rowsToXlsx(sheet: string, headers: string[], rows: (string | number | null)[][], moneyCols: number[] = []): Promise<Uint8Array> {
  const ExcelJS = (await import('exceljs')).default
  const wb = new ExcelJS.Workbook()
  const ws = wb.addWorksheet(sheet)
  const h = ws.addRow(headers)
  h.font = { bold: true }
  for (const r of rows) {
    const row = ws.addRow(r)
    for (const c of moneyCols) row.getCell(c + 1).numFmt = INR_NUMFMT
  }
  headers.forEach((_, i) => (ws.getColumn(i + 1).width = 16))
  ws.views = [{ state: 'frozen', ySplit: 1 }]
  const buf = await wb.xlsx.writeBuffer()
  return new Uint8Array(buf as ArrayBuffer)
}
