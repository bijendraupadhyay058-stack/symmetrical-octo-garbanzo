'use client'

import Link from 'next/link'
import { ArrowDownLeft, ArrowLeftRight, ArrowUpRight, FileText, RefreshCw } from 'lucide-react'
import { useData } from '@/components/app-provider'
import { PageHeader } from '@/components/ui'
import { formatINR } from '@/lib/money'
import { formatDate, todayIST } from '@/lib/dates'

export default function AddPage() {
  const data = useData()
  const today = todayIST()
  const templates = data.recurring_templates.filter((t) => t.is_active).sort((a, b) => (a.next_due_date < b.next_due_date ? -1 : 1))
  const tiles = [
    { href: '/add/income', title: 'Income / Receipt', text: 'Professional fees received', icon: ArrowDownLeft, cls: 'bg-income-soft text-income' },
    { href: '/add/expense', title: 'Expense / Payment', text: 'Office & business expenses', icon: ArrowUpRight, cls: 'bg-expense-soft text-expense' },
    { href: '/add/contra', title: 'Contra', text: 'Cash deposit / withdrawal', icon: ArrowLeftRight, cls: 'bg-balance-soft text-balance' },
    { href: '/fees?new=1', title: 'Fee Bill', text: 'Raise a fee demand (not income)', icon: FileText, cls: 'bg-elev text-fg' },
  ]
  return (
    <div>
      <PageHeader title="Add Entry" subtitle="Choose what you want to record" />
      <div className="grid grid-cols-2 gap-3">
        {tiles.map((t) => (
          <Link key={t.href} href={t.href} className="card flex flex-col gap-3 p-4 active:scale-[0.98]">
            <span className={`flex size-12 items-center justify-center rounded-2xl ${t.cls}`}><t.icon className="size-6" /></span>
            <div>
              <div className="font-bold">{t.title}</div>
              <div className="text-xs text-muted">{t.text}</div>
            </div>
          </Link>
        ))}
      </div>
      {templates.length > 0 && (
        <div className="mt-6">
          <h2 className="mb-2 flex items-center gap-2 font-bold"><RefreshCw className="size-4" /> Recurring expenses</h2>
          <div className="card divide-y divide-line">
            {templates.map((t) => (
              <Link key={t.id} href={`/add/expense?template=${t.id}`} className="flex items-center gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="font-semibold">{t.name}</div>
                  <div className={`text-xs ${t.next_due_date <= today ? 'font-semibold text-expense' : 'text-muted'}`}>
                    {t.next_due_date <= today ? 'Due' : 'Next due'} {formatDate(t.next_due_date)}
                  </div>
                </div>
                <span className="num font-semibold">{formatINR(t.amount_paise)}</span>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
