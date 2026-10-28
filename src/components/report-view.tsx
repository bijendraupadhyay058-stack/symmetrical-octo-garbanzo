'use client'

import { useState } from 'react'
import { Download, FileSpreadsheet, Printer, Share2 } from 'lucide-react'
import { useData } from './app-provider'
import { useFeedback } from './feedback'
import { cellText, safeFileName } from '@/lib/export/format'
import { formatINR } from '@/lib/money'
import { downloadBlob, shareFile } from '@/lib/share'
import type { ReportData } from '@/lib/reports/types'

const rowCls: Record<string, string> = {
  heading: 'bg-balance-soft font-bold text-balance',
  subtotal: 'bg-elev font-bold',
  total: 'bg-balance-soft font-bold',
  opening: 'bg-elev font-semibold',
  muted: 'text-muted italic',
  normal: '',
}

export function ExportBar({ report }: { report: ReportData }) {
  const data = useData()
  const { toast } = useFeedback()
  const [busy, setBusy] = useState<string | null>(null)
  const name = safeFileName(`${report.title}_${report.period}`)
  const run = async (kind: string, fn: () => Promise<void>) => {
    setBusy(kind)
    try {
      await fn()
    } catch (e) {
      toast(`Export failed: ${e instanceof Error ? e.message : e}`, 'error')
    } finally {
      setBusy(null)
    }
  }
  const pdf = async () => (await import('@/lib/export/pdf')).reportToPdf(report, data.profile)
  return (
    <div className="no-print grid grid-cols-4 gap-2">
      <button className="btn-outline px-2 text-[13px]" disabled={!!busy} onClick={() => run('pdf', async () => downloadBlob((await pdf()).output('blob'), name + '.pdf'))}>
        <Download className="size-4" /> {busy === 'pdf' ? '…' : 'PDF'}
      </button>
      <button className="btn-outline px-2 text-[13px]" disabled={!!busy} onClick={() => run('xlsx', async () => {
        const { reportToXlsx } = await import('@/lib/export/excel')
        const bytes = await reportToXlsx(report, data.profile)
        downloadBlob(new Blob([bytes as BlobPart], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }), name + '.xlsx')
      })}>
        <FileSpreadsheet className="size-4" /> {busy === 'xlsx' ? '…' : 'Excel'}
      </button>
      <button className="btn-outline px-2 text-[13px]" onClick={() => window.print()}>
        <Printer className="size-4" /> Print
      </button>
      <button className="btn-outline px-2 text-[13px]" disabled={!!busy} onClick={() => run('share', async () => {
        await shareFile((await pdf()).output('blob'), name + '.pdf', `${report.title} – ${report.period}`)
      })}>
        <Share2 className="size-4" /> Share
      </button>
    </div>
  )
}

export function ReportTable({ report, onRowClick }: { report: ReportData; onRowClick?: (ref: string) => void }) {
  const data = useData()
  return (
    <div className="space-y-3">
      <div className="print-only mb-2">
        <div className="text-lg font-bold">{data.profile?.name}</div>
        <div className="text-sm">{data.profile?.address}</div>
      </div>
      <div>
        <h2 className="text-lg font-bold">{report.title}</h2>
        <p className="text-[13px] text-muted">Period: {report.period}</p>
        {report.note && <p className="mt-1.5 rounded-xl bg-elev px-3 py-2 text-[12px] text-muted">{report.note}</p>}
      </div>
      {report.summary && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {report.summary.map((s) => (
            <div key={s.label} className="card px-3 py-2">
              <div className="text-[11px] font-semibold text-muted uppercase">{s.label}</div>
              <div className={`num font-bold ${s.tone === 'income' ? 'text-income' : s.tone === 'expense' ? 'text-expense' : s.tone === 'balance' ? 'text-balance' : ''}`}>
                {s.kind === 'count' ? s.value : formatINR(s.value)}
              </div>
            </div>
          ))}
        </div>
      )}
      {report.rows.length === 0 ? (
        <p className="card p-6 text-center text-sm text-muted">No entries for the selected filters.</p>
      ) : (
        <>
          <MobileRows report={report} onRowClick={onRowClick} />
        <div className="card hidden max-h-[70dvh] overflow-auto sm:block print:block print:max-h-none print:overflow-visible">
          <table className="fin-table">
            <thead>
              <tr>
                {report.columns.map((c) => (
                  <th key={c.key} className={c.type === 'money' || c.type === 'number' ? 'text-right' : ''}>{c.label}{c.type === 'money' ? ' ₹' : ''}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {report.rows.map((r, i) => (
                <tr key={i} className={`${rowCls[r.style ?? 'normal']} ${r.ref && onRowClick ? 'cursor-pointer hover:bg-elev' : ''}`} onClick={() => r.ref && onRowClick?.(r.ref)}>
                  {report.columns.map((c) => {
                    const v = r.cells[c.key]
                    const money = c.type === 'money'
                    const color = money && typeof v === 'number' && (r.style ?? 'normal') === 'normal'
                      ? c.key === 'receipt' || c.key === 'credit' ? 'text-income' : c.key === 'payment' ? 'text-expense' : ''
                      : ''
                    return (
                      <td key={c.key} className={`${money || c.type === 'number' ? 'num text-right whitespace-nowrap' : ''} ${c.type === 'date' ? 'whitespace-nowrap' : ''} ${color} ${money && typeof v === 'number' && v < 0 ? 'text-expense' : ''}`}>
                        {cellText(c, v)}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        </>
      )}
    </div>
  )
}

/** Phone layout: each row becomes a compact card instead of a wide table. */
function MobileRows({ report, onRowClick }: { report: ReportData; onRowClick?: (ref: string) => void }) {
  const textCols = report.columns.filter((c) => c.type === 'text')
  const main = textCols.reduce<ReportData['columns'][number] | undefined>((best, c) => (!best || (c.width ?? 1) > (best.width ?? 1) ? c : best), undefined)
  const meta = report.columns.filter((c) => c !== main && (c.type === 'text' || c.type === 'date' || c.type === 'number'))
  const money = report.columns.filter((c) => c.type === 'money')
  return (
    <div className="card divide-y divide-line overflow-hidden sm:hidden print:hidden">
      {report.rows.map((r, i) => {
        const style = r.style ?? 'normal'
        const metaText = meta.map((c) => cellText(c, r.cells[c.key])).filter(Boolean).join(' · ')
        const values = money.filter((c) => r.cells[c.key] !== null && r.cells[c.key] !== undefined && r.cells[c.key] !== '')
        return (
          <div key={i} className={`px-3.5 py-2.5 ${rowCls[style]} ${r.ref && onRowClick ? 'cursor-pointer active:bg-elev' : ''}`} onClick={() => r.ref && onRowClick?.(r.ref)}>
            {main && <div className={`text-[14px] ${style === 'normal' ? 'font-semibold' : ''}`}>{cellText(main, r.cells[main.key])}</div>}
            {metaText && <div className="text-[12px] text-muted">{metaText}</div>}
            {values.length > 0 && (
              <div className="mt-1 flex flex-wrap justify-end gap-x-4 gap-y-0.5 text-[12.5px]">
                {values.map((c) => {
                  const v = Number(r.cells[c.key])
                  const color = style === 'normal' ? (c.key === 'receipt' || c.key === 'credit' ? 'text-income' : c.key === 'payment' ? 'text-expense' : '') : ''
                  return (
                    <span key={c.key} className="whitespace-nowrap">
                      <span className="text-muted">{c.label} </span>
                      <span className={`num font-semibold ${color} ${v < 0 ? 'text-expense' : ''}`}>{cellText(c, v)}</span>
                    </span>
                  )
                })}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
