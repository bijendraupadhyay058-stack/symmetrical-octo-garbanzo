'use client'

import { Suspense, useMemo, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { SlidersHorizontal } from 'lucide-react'
import { useApp, useData } from '@/components/app-provider'
import { PageHeader, Select } from '@/components/ui'
import { PeriodFilter } from '@/components/period-filter'
import { ExportBar, ReportTable } from '@/components/report-view'
import { TransactionDetail } from '@/components/txn'
import { generateReport, reportMeta, REPORTS } from '@/lib/reports/reports'
import type { ReportId } from '@/lib/reports/types'
import { fyLabel, fyOf, fyRange, presetRange, todayIST, type PeriodPreset } from '@/lib/dates'
import { PAYMENT_METHODS, type PaymentMethod, type Transaction } from '@/lib/types'

function Inner() {
  const params = useSearchParams()
  const data = useData()
  const { fy, setFy } = useApp()
  const id = (REPORTS.some((r) => r.id === params.get('r')) ? params.get('r') : 'income-register') as ReportId
  const meta = reportMeta(id)
  const [preset, setPreset] = useState<PeriodPreset>('current_fy')
  const [range, setRange] = useState(presetRange('current_fy'))
  const [date, setDate] = useState(todayIST())
  const [clientId, setClientId] = useState(params.get('client') ?? '')
  const [categoryId, setCategoryId] = useState('')
  const [method, setMethod] = useState<PaymentMethod | ''>('')
  const [accountId, setAccountId] = useState('')
  const [showFilters, setShowFilters] = useState(true)
  const [open, setOpen] = useState<Transaction | null>(null)

  const effectiveRange = meta.filters.includes('fy') ? fyRange(fy) : meta.filters.includes('date') ? { from: date, to: date } : range
  const report = useMemo(
    () => generateReport(data, id, { range: effectiveRange, clientId: clientId || undefined, categoryId: categoryId || undefined, paymentMethod: method || undefined, accountId: accountId || undefined }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data, id, effectiveRange.from, effectiveRange.to, clientId, categoryId, method, accountId],
  )
  const fyOptions = useMemo(() => {
    const ys = new Set([fyOf(todayIST()), fy])
    data.transactions.forEach((t) => ys.add(fyOf(t.txn_date)))
    return [...ys].sort((a, b) => b - a)
  }, [data.transactions, fy])
  const catKind = id === 'expense-register' || id === 'expense-category' ? 'expense' : 'income'
  const accounts = data.accounts.filter((a) => (id === 'bank-register' ? a.kind !== 'cash' : a.kind === 'cash'))

  return (
    <div className="space-y-4">
      <PageHeader title={meta.title} subtitle={meta.description} back="/reports"
        actions={<button className={`btn-ghost px-2.5 ${showFilters ? 'bg-elev' : ''}`} aria-expanded={showFilters} aria-label="Filters" onClick={() => setShowFilters((v) => !v)}><SlidersHorizontal className="size-5" /></button>} />
      {showFilters && (
        <div className="no-print card space-y-3 p-4">
          {meta.filters.includes('range') && <PeriodFilter preset={preset} range={range} onChange={(p, r) => { setPreset(p); setRange(r) }} />}
          {meta.filters.includes('date') && (
            <label className="block"><span className="label">Date</span><input className="input" type="date" value={date} onChange={(e) => e.target.value && setDate(e.target.value)} /></label>
          )}
          {meta.filters.includes('fy') && (
            <label className="block"><span className="label">Financial year</span>
              <Select value={fy} onChange={(e) => setFy(Number(e.target.value))}>{fyOptions.map((y) => <option key={y} value={y}>FY {fyLabel(y)}</option>)}</Select>
            </label>
          )}
          <div className="grid grid-cols-2 gap-3">
            {meta.filters.includes('client') && (
              <label className="col-span-2"><span className="label">Client</span>
                <Select value={clientId} onChange={(e) => setClientId(e.target.value)}>
                  <option value="">{id === 'client-statement' ? 'Select client…' : 'All clients'}</option>
                  {[...data.clients].sort((a, b) => a.name.localeCompare(b.name)).map((c) => <option key={c.id} value={c.id}>{c.name} ({c.code})</option>)}
                </Select>
              </label>
            )}
            {meta.filters.includes('category') && (
              <label><span className="label">Category</span>
                <Select value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
                  <option value="">All</option>
                  {data.categories.filter((c) => c.kind === catKind).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </Select>
              </label>
            )}
            {meta.filters.includes('payment') && (
              <label><span className="label">Payment method</span>
                <Select value={method} onChange={(e) => setMethod(e.target.value as PaymentMethod | '')}>
                  <option value="">All</option>
                  {PAYMENT_METHODS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                </Select>
              </label>
            )}
            {meta.filters.includes('account') && accounts.length > 1 && (
              <label><span className="label">Account</span>
                <Select value={accountId} onChange={(e) => setAccountId(e.target.value)}>
                  <option value="">All</option>
                  {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </Select>
              </label>
            )}
          </div>
        </div>
      )}
      <ExportBar report={report} />
      <ReportTable report={report} onRowClick={(rid) => setOpen(data.transactions.find((t) => t.id === rid) ?? null)} />
      <TransactionDetail txn={open} onClose={() => setOpen(null)} />
    </div>
  )
}

export default function ReportViewPage() {
  return (
    <Suspense>
      <Inner />
    </Suspense>
  )
}
