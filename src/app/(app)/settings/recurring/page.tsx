'use client'

import { useState } from 'react'
import Link from 'next/link'
import { Plus } from 'lucide-react'
import { useData, useStore } from '@/components/app-provider'
import { useFeedback } from '@/components/feedback'
import { Badge, EmptyState, Field, MoneyInput, PageHeader, Select, Sheet } from '@/components/ui'
import { newTemplate, saveTemplate } from '@/lib/store/repo'
import { formatDate, todayIST } from '@/lib/dates'
import { formatINR } from '@/lib/money'
import { accountKindsForMethod, PAYMENT_METHODS, type PaymentMethod, type RecurringTemplate } from '@/lib/types'

export default function RecurringPage() {
  const data = useData()
  const store = useStore()
  const { toast } = useFeedback()
  const [edit, setEdit] = useState<RecurringTemplate | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const today = todayIST()
  const accounts = edit ? data.accounts.filter((a) => a.is_active && accountKindsForMethod(edit.payment_method).includes(a.kind)) : []
  return (
    <div>
      <PageHeader title="Recurring Expenses" subtitle="Templates are never posted automatically – you confirm each one" back="/settings"
        actions={<button className="btn-primary px-3" onClick={() => { setErrors({}); setEdit(newTemplate(store)) }}><Plus className="size-4" /> New</button>} />
      {data.recurring_templates.length ? (
        <div className="card divide-y divide-line overflow-hidden">
          {data.recurring_templates.map((t) => (
            <div key={t.id} className="flex items-center gap-3 px-4 py-3">
              <button className="min-w-0 flex-1 text-left" onClick={() => { setErrors({}); setEdit(t) }}>
                <div className="font-semibold">{t.name} {!t.is_active && <Badge>Paused</Badge>}</div>
                <div className="text-xs text-muted">Monthly on day {t.day_of_month} · next {formatDate(t.next_due_date)} · {formatINR(t.amount_paise)}</div>
              </button>
              {t.is_active && <Link href={`/add/expense?template=${t.id}`} className={t.next_due_date <= today ? 'btn-expense px-3 text-sm' : 'btn-outline px-3 text-sm'}>Post</Link>}
            </div>
          ))}
        </div>
      ) : (
        <EmptyState title="No recurring expenses" text="Create templates for rent, salary, internet and other regular payments." />
      )}
      {edit && (
        <Sheet open onClose={() => setEdit(null)} title={edit.name || 'Recurring expense'}
          footer={<button className="btn-primary w-full" onClick={async () => {
            const r = await saveTemplate(store, edit)
            if (!r.ok) return setErrors(r.errors)
            toast('Template saved')
            setEdit(null)
          }}>Save template</button>}>
          <div className="space-y-3.5">
            <Field label="Template name *" error={errors.name}><input className="input" value={edit.name} placeholder="Office Rent" onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
            <Field label="Paid to"><input className="input" value={edit.party} onChange={(e) => setEdit({ ...edit, party: e.target.value })} /></Field>
            <Field label="Category *" error={errors.category_id}>
              <Select value={edit.category_id ?? ''} onChange={(e) => setEdit({ ...edit, category_id: e.target.value || null })}>
                <option value="">Select…</option>
                {data.categories.filter((c) => c.kind === 'expense' && c.is_active).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </Select>
            </Field>
            <Field label="Amount *" error={errors.amount}><MoneyInput value={edit.amount_paise} onChange={(p) => setEdit({ ...edit, amount_paise: p })} /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Payment method">
                <Select value={edit.payment_method} onChange={(e) => {
                  const m = e.target.value as PaymentMethod
                  const acc = data.accounts.find((a) => a.is_active && accountKindsForMethod(m).includes(a.kind))
                  setEdit({ ...edit, payment_method: m, account_id: acc?.id ?? '' })
                }}>{PAYMENT_METHODS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}</Select>
              </Field>
              <Field label="Account" error={errors.account_id}>
                <Select value={edit.account_id} onChange={(e) => setEdit({ ...edit, account_id: e.target.value })}>
                  <option value="">Select…</option>{accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </Select>
              </Field>
              <Field label="Day of month" error={errors.day_of_month}><input className="input" type="number" min={1} max={31} value={edit.day_of_month} onChange={(e) => setEdit({ ...edit, day_of_month: Number(e.target.value) })} /></Field>
              <Field label="Next due date"><input className="input" type="date" value={edit.next_due_date} onChange={(e) => setEdit({ ...edit, next_due_date: e.target.value })} /></Field>
            </div>
            <Field label="Narration"><input className="input" value={edit.narration} onChange={(e) => setEdit({ ...edit, narration: e.target.value })} /></Field>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="size-5" checked={edit.is_active} onChange={(e) => setEdit({ ...edit, is_active: e.target.checked })} /> Active</label>
          </div>
        </Sheet>
      )}
    </div>
  )
}
