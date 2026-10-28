'use client'

import { useMemo, useState } from 'react'
import dynamic from 'next/dynamic'
import Link from 'next/link'
import { AlertCircle, ArrowDownLeft, ArrowUpRight, Bell, CalendarDays, ChevronRight, Landmark, Wallet } from 'lucide-react'
import { useApp, useData } from '@/components/app-provider'
import { EmptyState, StatCard, Spinner } from '@/components/ui'
import { TransactionDetail, TxnRow, useLookups } from '@/components/txn'
import { computeDashboard } from '@/lib/accounting/dashboard'
import { formatDate, fyLabel, fyOf, todayIST } from '@/lib/dates'
import { formatINR } from '@/lib/money'
import { billPositions } from '@/lib/accounting/fees'
import type { Transaction } from '@/lib/types'

const loading = () => <div className="flex h-[200px] items-center justify-center"><Spinner className="text-muted" /></div>
const IncomeExpenseChart = dynamic(() => import('@/components/charts').then((m) => m.IncomeExpenseChart), { ssr: false, loading })
const CollectionChart = dynamic(() => import('@/components/charts').then((m) => m.CollectionChart), { ssr: false, loading })
const CategoryDonut = dynamic(() => import('@/components/charts').then((m) => m.CategoryDonut), { ssr: false, loading })

export default function Dashboard() {
  const data = useData()
  const lk = useLookups()
  const { fy, setFy } = useApp()
  const today = todayIST()
  const [asOn, setAsOn] = useState(today)
  const [open, setOpen] = useState<Transaction | null>(null)
  const d = useMemo(() => computeDashboard(data, asOn, fy), [data, asOn, fy])
  const fyOptions = useMemo(() => {
    const years = new Set<number>([fyOf(today), fy])
    for (const t of data.transactions) years.add(fyOf(t.txn_date))
    return [...years].sort((a, b) => b - a)
  }, [data.transactions, fy, today])
  const overdue = useMemo(() => billPositions(data, today).filter((b) => b.overdue).length, [data, today])
  const dueTemplates = data.recurring_templates.filter((t) => t.is_active && t.next_due_date <= today).length
  const hasOpening = data.opening_balances.length > 0
  const firstName = data.profile?.name ?? ''

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <div className="w-full sm:w-auto sm:flex-1">
          <h1 className="text-xl font-bold">Dashboard</h1>
          <p className="truncate text-[13px] text-muted">{firstName}</p>
        </div>
        <label className="chip">
          <CalendarDays className="size-4" aria-hidden />
          <span className="sr-only">As on date</span>
          <input type="date" value={asOn} max="2099-12-31" onChange={(e) => e.target.value && setAsOn(e.target.value)} className="bg-transparent text-[13px] outline-none" />
        </label>
        <label className="chip">
          <span className="sr-only">Financial year</span>
          FY
          <select value={fy} onChange={(e) => setFy(Number(e.target.value))} className="bg-transparent text-[13px] font-semibold outline-none">
            {fyOptions.map((y) => <option key={y} value={y}>{fyLabel(y)}</option>)}
          </select>
        </label>
      </div>

      {!hasOpening && (
        <Link href="/settings/accounts" className="card flex items-center gap-3 border-balance/30 bg-balance-soft p-4 text-balance">
          <AlertCircle className="size-5 shrink-0" />
          <span className="flex-1 text-sm font-medium">Start by entering the opening cash and bank balances.</span>
          <ChevronRight className="size-4" />
        </Link>
      )}

      <div className="grid grid-cols-2 gap-3">
        <Link href="/add/income" className="btn-income min-h-14 text-base"><ArrowDownLeft className="size-5" /> Add Income</Link>
        <Link href="/add/expense" className="btn-expense min-h-14 text-base"><ArrowUpRight className="size-5" /> Add Expense</Link>
      </div>

      <section aria-label={`Cash position on ${formatDate(asOn)}`}>
        <h2 className="mb-2 flex items-center gap-2 text-sm font-bold text-muted"><Wallet className="size-4" /> CASH IN HAND · {asOn === today ? 'TODAY' : formatDate(asOn)}</h2>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard label="Opening Cash Balance" value={d.todayOpeningCash} tone="balance" />
          <StatCard label={asOn === today ? "Today's Cash Income" : 'Cash Income'} value={d.todayCashIncome} tone="income" sub={d.todayContraCashIn ? `+ ${formatINR(d.todayContraCashIn)} from bank` : undefined} />
          <StatCard label={asOn === today ? "Today's Cash Expenses" : 'Cash Expenses'} value={d.todayCashExpense} tone="expense" sub={d.todayContraCashOut ? `+ ${formatINR(d.todayContraCashOut)} to bank` : undefined} />
          <StatCard label={asOn === today ? "Today's Closing Cash" : 'Closing Cash'} value={d.todayClosingCash} tone="balance" />
        </div>
      </section>

      <section aria-label="This month">
        <h2 className="mb-2 text-sm font-bold text-muted">THIS MONTH (ALL MODES)</h2>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard label="This Month's Income" value={d.monthIncome} tone="income" sub={`Cash ${formatINR(d.monthIncomeCash)} · Bank/UPI ${formatINR(d.monthIncome - d.monthIncomeCash)}`} />
          <StatCard label="This Month's Expenses" value={d.monthExpense} tone="expense" sub={`Cash ${formatINR(d.monthExpenseCash)} · Bank/UPI ${formatINR(d.monthExpense - d.monthExpenseCash)}`} />
          <StatCard label="Net Cash Movement" value={d.monthNet} tone={d.monthNet < 0 ? 'expense' : 'balance'} sub="Income − Expenses" />
          <StatCard label="Bank & UPI Balance" value={d.bankBalance} tone="balance" icon={<Landmark className="size-3.5" />} />
          <Link href="/fees" className="contents"><StatCard label="Outstanding Professional Fees" value={d.outstandingFees} tone="expense" sub={overdue ? `${overdue} bill(s) overdue` : 'From fee register'} /></Link>
          <Link href="/transactions" className="contents"><StatCard label="Total Transactions" value={String(d.totalTransactions)} tone="neutral" sub="Active entries" /></Link>
        </div>
      </section>

      {(overdue > 0 || dueTemplates > 0) && (
        <Link href="/reminders" className="card flex items-center gap-3 p-4">
          <Bell className="size-5 text-expense" />
          <span className="flex-1 text-sm font-medium">
            {[overdue && `${overdue} overdue fee bill(s)`, dueTemplates && `${dueTemplates} recurring expense(s) due`].filter(Boolean).join(' · ')}
          </span>
          <ChevronRight className="size-4 text-muted" />
        </Link>
      )}

      <section className="card p-4">
        <div className="mb-1 flex items-center justify-between">
          <h2 className="font-bold">Recent Transactions</h2>
          <Link href="/transactions" className="text-sm font-semibold text-balance">View all</Link>
        </div>
        {d.recent.length ? (
          <div className="-mx-4">{d.recent.map((t) => <TxnRow key={t.id} t={t} lk={lk} onOpen={() => setOpen(t)} />)}</div>
        ) : (
          <EmptyState title="No transactions yet" text="Record your first receipt or expense using the buttons above." />
        )}
      </section>

      <section className="card p-4">
        <h2 className="font-bold">Income vs Expenses</h2>
        <p className="mb-2 text-xs text-muted">Month-wise, FY {fyLabel(fy)} (all payment modes)</p>
        <IncomeExpenseChart data={d.monthly} />
      </section>
      <section className="card p-4">
        <h2 className="font-bold">Monthly Collection</h2>
        <p className="mb-2 text-xs text-muted">Fees received by mode, FY {fyLabel(fy)}</p>
        <CollectionChart data={d.monthly} />
      </section>
      <section className="card p-4">
        <h2 className="font-bold">Expenses by Category</h2>
        <p className="mb-2 text-xs text-muted">FY {fyLabel(fy)}</p>
        {d.expenseByCategory.length ? <CategoryDonut data={d.expenseByCategory} /> : <p className="py-6 text-center text-sm text-muted">No expenses recorded in this year.</p>}
      </section>

      <TransactionDetail txn={open} onClose={() => setOpen(null)} />
    </div>
  )
}
