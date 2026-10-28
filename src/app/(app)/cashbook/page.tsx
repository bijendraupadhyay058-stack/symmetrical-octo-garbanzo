'use client'

import { useMemo, useState } from 'react'
import { Search } from 'lucide-react'
import { useData } from '@/components/app-provider'
import { PageHeader, Segmented, Select } from '@/components/ui'
import { PeriodFilter } from '@/components/period-filter'
import { ExportBar, ReportTable } from '@/components/report-view'
import { TransactionDetail } from '@/components/txn'
import { generateReport } from '@/lib/reports/reports'
import { presetRange, todayIST, type PeriodPreset } from '@/lib/dates'
import type { Transaction } from '@/lib/types'

type Book = 'cash' | 'bank' | 'consolidated'

export default function CashBookPage() {
  const data = useData()
  const [book, setBook] = useState<Book>('cash')
  const [preset, setPreset] = useState<PeriodPreset>('current_month')
  const [range, setRange] = useState(presetRange('current_month'))
  const [account, setAccount] = useState('')
  const [q, setQ] = useState('')
  const [open, setOpen] = useState<Transaction | null>(null)

  const accounts = data.accounts.filter((a) => (book === 'cash' ? a.kind === 'cash' : a.kind !== 'cash'))
  const report = useMemo(() => {
    const id = book === 'consolidated' ? 'receipts-payments' : book === 'cash' ? (preset === 'today' ? 'daily-cashbook' : 'monthly-cashbook') : 'bank-register'
    const r = generateReport(data, id, { range, accountId: account || undefined })
    const needle = q.trim().toLowerCase()
    if (!needle || book === 'consolidated') return r
    // Search narrows the visible rows; balances remain the true running balances.
    return {
      ...r,
      rows: r.rows.filter((row) => row.style !== 'normal' && row.style !== undefined ? true : Object.values(row.cells).some((v) => String(v ?? '').toLowerCase().includes(needle)) || String(row.cells.date ?? '').split('-').reverse().join('-').includes(needle)),
    }
  }, [data, book, preset, range, account, q])

  return (
    <div className="space-y-4">
      <PageHeader title="Cash Book & Bank Book" subtitle="Running balances update automatically for back-dated entries" />
      <div className="no-print space-y-3">
        <Segmented<Book> value={book} onChange={(b) => { setBook(b); setAccount('') }} options={[{ value: 'cash', label: 'Cash Book' }, { value: 'bank', label: 'Bank / UPI Book' }, { value: 'consolidated', label: 'Receipts & Payments' }]} />
        <PeriodFilter preset={preset} range={range} onChange={(p, r) => { setPreset(p); setRange(r) }} />
        {preset === 'today' && (
          <label className="block"><span className="label">Date</span>
            <input className="input" type="date" value={range.to} max="2099-12-31" onChange={(e) => e.target.value && setRange({ from: e.target.value, to: e.target.value })} />
          </label>
        )}
        <div className="grid grid-cols-2 gap-3">
          {book !== 'consolidated' && accounts.length > 1 && (
            <label><span className="label">Account</span>
              <Select value={account} onChange={(e) => setAccount(e.target.value)}>
                <option value="">All {book === 'cash' ? 'cash' : 'bank & UPI'} accounts</option>
                {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </Select>
            </label>
          )}
          {book !== 'consolidated' && (
            <label className={accounts.length > 1 ? '' : 'col-span-2'}><span className="label">Search voucher / date / text</span>
              <div className="relative">
                <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" />
                <input className="input pl-9" value={q} placeholder="CR/26-27/005 or 02-04-2026" onChange={(e) => setQ(e.target.value)} />
              </div>
            </label>
          )}
        </div>
        <ExportBar report={report} />
      </div>
      <ReportTable report={report} onRowClick={(id) => setOpen(data.transactions.find((t) => t.id === id) ?? null)} />
      <p className="text-center text-xs text-muted no-print">As on {todayIST().split('-').reverse().join('-')} · Tap an entry to view, edit or cancel it.</p>
      <TransactionDetail txn={open} onClose={() => setOpen(null)} />
    </div>
  )
}
