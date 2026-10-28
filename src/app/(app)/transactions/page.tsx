'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import { ArrowDownUp, Download, ListFilter, Plus, Search } from 'lucide-react'
import { useData } from '@/components/app-provider'
import { EmptyState, PageHeader, Select } from '@/components/ui'
import { TransactionDetail, TxnRow, useLookups, useTxnActions } from '@/components/txn'
import { PeriodFilter } from '@/components/period-filter'
import { presetRange, type PeriodPreset, formatDate } from '@/lib/dates'
import { compareTxns, particularsFor } from '@/lib/accounting/ledger'
import { formatINR } from '@/lib/money'
import { PAYMENT_METHODS, paymentMethodLabel, type Transaction } from '@/lib/types'
import { downloadBlob } from '@/lib/share'

type SortKey = 'date_desc' | 'date_asc' | 'amount_desc' | 'amount_asc' | 'voucher'

export default function TransactionsPage() {
  const data = useData()
  const lk = useLookups()
  const actions = useTxnActions()
  const [q, setQ] = useState('')
  const [type, setType] = useState<'all' | Transaction['type']>('all')
  const [method, setMethod] = useState('')
  const [account, setAccount] = useState('')
  const [status, setStatus] = useState<'active' | 'cancelled' | 'all'>('active')
  const [sort, setSort] = useState<SortKey>('date_desc')
  const [preset, setPreset] = useState<PeriodPreset>('current_fy')
  const [range, setRange] = useState(presetRange('current_fy'))
  const [showFilters, setShowFilters] = useState(false)
  const [open, setOpen] = useState<Transaction | null>(null)
  const [limit, setLimit] = useState(100)

  const list = useMemo(() => {
    const needle = q.trim().toLowerCase()
    const out = data.transactions.filter((t) => {
      if (t.txn_date < range.from || t.txn_date > range.to) return false
      if (type !== 'all' && t.type !== type) return false
      if (method && t.payment_method !== method) return false
      if (account && t.account_id !== account && t.to_account_id !== account) return false
      if (status !== 'all' && t.status !== status) return false
      if (!needle) return true
      const hay = [t.voucher_no, particularsFor(t, lk), t.party, t.narration, t.reference_no, t.service, lk.clientName(t.client_id), formatDate(t.txn_date), (t.amount_paise / 100).toString()].join(' ').toLowerCase()
      return hay.includes(needle)
    })
    const s = [...out]
    switch (sort) {
      case 'date_desc': s.sort((a, b) => -compareTxns(a, b)); break
      case 'date_asc': s.sort(compareTxns); break
      case 'amount_desc': s.sort((a, b) => b.amount_paise - a.amount_paise); break
      case 'amount_asc': s.sort((a, b) => a.amount_paise - b.amount_paise); break
      case 'voucher': s.sort((a, b) => a.voucher_no.localeCompare(b.voucher_no, 'en', { numeric: true })); break
    }
    return s
  }, [data.transactions, q, type, method, account, status, sort, range, lk])

  const totals = useMemo(() => {
    const act = list.filter((t) => t.status === 'active')
    return {
      income: act.filter((t) => t.type === 'income').reduce((s, t) => s + t.amount_paise, 0),
      expense: act.filter((t) => t.type === 'expense').reduce((s, t) => s + t.amount_paise, 0),
    }
  }, [list])

  const exportAll = async () => {
    const { rowsToXlsx } = await import('@/lib/export/excel')
    const all = [...data.transactions].sort(compareTxns)
    const rows = all.map((t) => [
      formatDate(t.txn_date), t.voucher_no, t.type, t.status, lk.clientName(t.client_id), t.party, lk.categoryName(t.type === 'contra' ? null : t.category_id),
      t.service, paymentMethodLabel(t.payment_method), lk.accountName(t.account_id), lk.accountName(t.to_account_id), t.reference_no, t.narration,
      t.type === 'income' ? t.amount_paise / 100 : null, t.type === 'expense' ? t.amount_paise / 100 : null, t.type === 'contra' ? t.amount_paise / 100 : null, t.cancel_reason, t.id,
    ])
    const bytes = await rowsToXlsx('Transactions', ['Date', 'Voucher', 'Type', 'Status', 'Client', 'Party / Firm', 'Category', 'Service', 'Mode', 'Account', 'To Account', 'Reference', 'Narration', 'Receipt', 'Payment', 'Contra', 'Cancel Reason', 'Transaction ID'], rows, [13, 14, 15])
    downloadBlob(new Blob([bytes as BlobPart]), `All_Transactions_${data.profile?.name ?? ''}.xlsx`.replace(/\s+/g, '_'))
  }

  return (
    <div>
      <PageHeader
        title="Transactions"
        subtitle={`${list.length} entries`}
        actions={
          <>
            <button className="btn-ghost px-2.5" onClick={exportAll} aria-label="Export all transactions to Excel" title="Export all transactions"><Download className="size-5" /></button>
            <button className={`btn-ghost px-2.5 ${showFilters ? 'bg-elev' : ''}`} onClick={() => setShowFilters((v) => !v)} aria-expanded={showFilters} aria-label="Filters"><ListFilter className="size-5" /></button>
          </>
        }
      />
      <div className="relative mb-3">
        <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted" />
        <input className="input pl-10" placeholder="Search voucher, client, narration, amount…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search transactions" />
      </div>
      <div className="-mx-4 mb-3 flex gap-2 overflow-x-auto px-4">
        {(['all', 'income', 'expense', 'contra'] as const).map((t) => (
          <button key={t} className={type === t ? 'chip-active' : 'chip'} onClick={() => setType(t)}>
            {t === 'all' ? 'All' : t === 'income' ? 'Income' : t === 'expense' ? 'Expenses' : 'Contra'}
          </button>
        ))}
      </div>
      {showFilters && (
        <div className="card mb-3 space-y-3 p-4">
          <PeriodFilter preset={preset} range={range} onChange={(p, r) => { setPreset(p); setRange(r) }} />
          <div className="grid grid-cols-2 gap-3">
            <label><span className="label">Payment method</span>
              <Select value={method} onChange={(e) => setMethod(e.target.value)}><option value="">All</option>{PAYMENT_METHODS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}</Select>
            </label>
            <label><span className="label">Account</span>
              <Select value={account} onChange={(e) => setAccount(e.target.value)}><option value="">All</option>{data.accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select>
            </label>
            <label><span className="label">Status</span>
              <Select value={status} onChange={(e) => setStatus(e.target.value as typeof status)}><option value="active">Active</option><option value="cancelled">Cancelled</option><option value="all">All</option></Select>
            </label>
            <label><span className="label"><ArrowDownUp className="inline size-3" /> Sort by</span>
              <Select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
                <option value="date_desc">Newest first</option><option value="date_asc">Oldest first</option>
                <option value="amount_desc">Amount: high to low</option><option value="amount_asc">Amount: low to high</option><option value="voucher">Voucher number</option>
              </Select>
            </label>
          </div>
        </div>
      )}
      <div className="mb-3 grid grid-cols-2 gap-2 text-[13px]">
        <div className="card px-3 py-2"><span className="text-muted">Income</span> <b className="num text-income">{formatINR(totals.income)}</b></div>
        <div className="card px-3 py-2"><span className="text-muted">Expenses</span> <b className="num text-expense">{formatINR(totals.expense)}</b></div>
      </div>
      {list.length ? (
        <div className="card overflow-hidden">
          {list.slice(0, limit).map((t) => (
            <TxnRow key={t.id} t={t} lk={lk} onOpen={() => setOpen(t)} onCancel={() => actions.cancel(t)} />
          ))}
          {list.length > limit && <button className="btn-ghost w-full" onClick={() => setLimit((l) => l + 200)}>Show more ({list.length - limit})</button>}
        </div>
      ) : (
        <EmptyState title="No transactions found" text="Try a different period or filter." action={<Link href="/add" className="btn-primary"><Plus className="size-4" /> Add entry</Link>} />
      )}
      <p className="mt-3 text-center text-xs text-muted">Tip: swipe a row left to edit or cancel.</p>
      <Link href="/add" className="no-print fixed right-4 bottom-[calc(88px+env(safe-area-inset-bottom))] z-30 flex size-14 items-center justify-center rounded-full bg-primary text-primary-fg shadow-xl lg:bottom-6" aria-label="Add transaction">
        <Plus className="size-7" />
      </Link>
      <TransactionDetail txn={open} onClose={() => setOpen(null)} />
    </div>
  )
}
