'use client'

import { useMemo } from 'react'
import Link from 'next/link'
import { Bell, MessageCircle, RefreshCw } from 'lucide-react'
import { useData, useStore } from '@/components/app-provider'
import { Badge, EmptyState, PageHeader } from '@/components/ui'
import { billPositions } from '@/lib/accounting/fees'
import { formatDate, todayIST, addDays } from '@/lib/dates'
import { formatINR } from '@/lib/money'
import { markReminded } from '@/lib/store/repo'
import { shareText } from '@/lib/share'
import { reminderText } from '@/lib/reminders'

export default function RemindersPage() {
  const data = useData()
  const store = useStore()
  const today = todayIST()
  const bills = useMemo(
    () => billPositions(data, today).filter((p) => p.outstanding > 0 && p.status !== 'cancelled').sort((a, b) => (a.bill.due_date ?? a.bill.bill_date) < (b.bill.due_date ?? b.bill.bill_date) ? -1 : 1),
    [data, today],
  )
  const templates = data.recurring_templates.filter((t) => t.is_active && t.next_due_date <= addDays(today, 7)).sort((a, b) => (a.next_due_date < b.next_due_date ? -1 : 1))
  return (
    <div className="space-y-5">
      <PageHeader title="Reminders" subtitle="Client payment follow-ups and upcoming recurring expenses" />
      <section>
        <h2 className="mb-2 flex items-center gap-2 font-bold"><Bell className="size-4" /> Client payment reminders</h2>
        {bills.length ? (
          <div className="card divide-y divide-line overflow-hidden">
            {bills.map((p) => {
              const client = data.clients.find((c) => c.id === p.bill.client_id)
              return (
                <div key={p.bill.id} className="flex items-center gap-3 px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <div className="font-semibold">{client?.name}</div>
                    <div className="text-xs text-muted">{p.bill.bill_no} · {p.bill.due_date ? `due ${formatDate(p.bill.due_date)}` : `billed ${formatDate(p.bill.bill_date)}`}{p.bill.last_reminded_at ? ` · reminded ${formatDate(p.bill.last_reminded_at.slice(0, 10))}` : ''}</div>
                    <div className="mt-1 flex items-center gap-2"><span className="num text-sm font-bold text-expense">{formatINR(p.outstanding)}</span>{p.overdue && <Badge tone="expense">Overdue</Badge>}</div>
                  </div>
                  <button className="btn-outline px-3 text-sm" disabled={!client?.mobile && !('share' in navigator)}
                    onClick={async () => { await shareText(reminderText(data.profile, client, p.bill, p.outstanding), client?.mobile); await markReminded(store, p.bill.id) }}>
                    <MessageCircle className="size-4 text-income" /> WhatsApp
                  </button>
                </div>
              )
            })}
          </div>
        ) : (
          <EmptyState title="No outstanding fees" text="All fee bills are fully received." />
        )}
        <p className="mt-2 text-xs text-muted">Reminder text can be changed in Settings → Business Profile.</p>
      </section>
      <section>
        <h2 className="mb-2 flex items-center gap-2 font-bold"><RefreshCw className="size-4" /> Recurring expenses due (next 7 days)</h2>
        {templates.length ? (
          <div className="card divide-y divide-line overflow-hidden">
            {templates.map((t) => (
              <Link key={t.id} href={`/add/expense?template=${t.id}`} className="flex items-center gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="font-semibold">{t.name}</div>
                  <div className={`text-xs ${t.next_due_date <= today ? 'font-semibold text-expense' : 'text-muted'}`}>Due {formatDate(t.next_due_date)} · tap to post</div>
                </div>
                <span className="num font-semibold">{formatINR(t.amount_paise)}</span>
              </Link>
            ))}
          </div>
        ) : (
          <p className="card p-4 text-sm text-muted">Nothing due. Manage templates in <Link className="text-balance underline" href="/settings/recurring">Recurring Expenses</Link>.</p>
        )}
      </section>
    </div>
  )
}
