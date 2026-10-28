'use client'

import { Suspense, useMemo, useState } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { Ban, FileText, MessageCircle, Pencil, Plus, Search } from 'lucide-react'
import { useData, useStore } from '@/components/app-provider'
import { useFeedback } from '@/components/feedback'
import { Badge, EmptyState, Field, MoneyInput, PageHeader, Select, Sheet, Textarea } from '@/components/ui'
import { useLookups } from '@/components/txn'
import { billPositions, type BillPosition } from '@/lib/accounting/fees'
import { cancelFeeBill, markReminded, newFeeBill, saveFeeBill } from '@/lib/store/repo'
import { formatDate, todayIST } from '@/lib/dates'
import { formatINR } from '@/lib/money'
import { shareText } from '@/lib/share'
import { reminderText } from '@/lib/reminders'
import type { FeeBill } from '@/lib/types'

type StatusFilter = 'open' | 'overdue' | 'paid' | 'cancelled' | 'all'

function BillSheet({ initial, onClose }: { initial: FeeBill; onClose: () => void }) {
  const store = useStore()
  const data = useData()
  const { toast } = useFeedback()
  const [b, setB] = useState(initial)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const set = <K extends keyof FeeBill>(k: K, v: FeeBill[K]) => setB((x) => ({ ...x, [k]: v }))
  const isNew = !data.fee_bills.some((x) => x.id === b.id)
  return (
    <Sheet open onClose={onClose} title={isNew ? 'New fee bill' : `Edit ${b.bill_no}`}
      footer={<button className="btn-primary w-full" disabled={busy} onClick={async () => {
        setBusy(true)
        const r = await saveFeeBill(store, b)
        setBusy(false)
        if (!r.ok) return setErrors(r.errors)
        toast(`Fee bill ${r.value.bill_no} saved`)
        onClose()
      }}>Save fee bill</button>}>
      <div className="space-y-3.5">
        <p className="rounded-xl bg-balance-soft p-3 text-[13px] text-balance">A fee bill records what the client owes. It is <b>not income</b> – income is recorded when you add the receipt and adjust it against this bill.</p>
        {errors.form && <p className="text-sm text-expense">{errors.form}</p>}
        <Field label="Client *" error={errors.client_id}>
          <Select value={b.client_id} onChange={(e) => set('client_id', e.target.value)}>
            <option value="">Select client…</option>
            {[...data.clients].filter((c) => c.is_active || c.id === b.client_id).sort((x, y) => x.name.localeCompare(y.name)).map((c) => <option key={c.id} value={c.id}>{c.name} ({c.code})</option>)}
          </Select>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Bill date"><input className="input" type="date" value={b.bill_date} onChange={(e) => set('bill_date', e.target.value)} /></Field>
          <Field label="Due date" error={errors.due_date}><input className="input" type="date" value={b.due_date ?? ''} onChange={(e) => set('due_date', e.target.value || null)} /></Field>
        </div>
        <Field label="Service" error={errors.service}>
          <Select value={b.category_id ?? ''} onChange={(e) => set('category_id', e.target.value || null)}>
            <option value="">Select…</option>
            {data.categories.filter((c) => c.kind === 'income' && (c.is_active || c.id === b.category_id)).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </Select>
        </Field>
        <Field label="Service details"><input className="input" value={b.service} placeholder="e.g. FY 2025-26 ITR-3" onChange={(e) => set('service', e.target.value)} /></Field>
        <Field label="Fees charged *" error={errors.amount}><MoneyInput value={b.amount_paise} onChange={(p) => set('amount_paise', p)} /></Field>
        <Field label="Notes"><Textarea value={b.narration} onChange={(e) => set('narration', e.target.value)} /></Field>
      </div>
    </Sheet>
  )
}

function BillDetail({ pos, onClose, onEdit }: { pos: BillPosition; onClose: () => void; onEdit: () => void }) {
  const data = useData()
  const store = useStore()
  const lk = useLookups()
  const { confirm, toast } = useFeedback()
  const b = pos.bill
  const client = data.clients.find((c) => c.id === b.client_id)
  const receipts = data.fee_allocations
    .filter((a) => a.fee_bill_id === b.id && a.amount_paise > 0)
    .map((a) => ({ a, t: data.transactions.find((t) => t.id === a.transaction_id) }))
    .filter((x) => x.t)
  return (
    <Sheet open onClose={onClose} title={b.bill_no}
      footer={b.status === 'active' ? (
        <div className="grid grid-cols-2 gap-2">
          {pos.outstanding > 0 && <Link className="btn-income col-span-2" href={`/add/income?client=${b.client_id}`}><Plus className="size-4" /> Record receipt</Link>}
          {pos.outstanding > 0 && (
            <button className="btn-outline" onClick={async () => {
              await shareText(reminderText(data.profile, client, b, pos.outstanding), client?.mobile)
              await markReminded(store, b.id)
            }}><MessageCircle className="size-4" /> Remind</button>
          )}
          <button className="btn-outline" onClick={onEdit}><Pencil className="size-4" /> Edit</button>
          <button className="btn-outline text-expense" onClick={async () => {
            const r = await confirm({ title: `Cancel ${b.bill_no}?`, message: 'The bill stays in the register marked cancelled and no longer counts as outstanding.', danger: true, input: { label: 'Reason', required: true }, confirmLabel: 'Cancel bill' })
            if (!r.ok) return
            const res = await cancelFeeBill(store, b.id, r.value)
            if (!res.ok) toast(Object.values(res.errors)[0], 'error')
            else { toast('Bill cancelled'); onClose() }
          }}><Ban className="size-4" /> Cancel</button>
        </div>
      ) : undefined}>
      <div className="space-y-2 text-sm">
        <div className="flex justify-between"><span className="text-muted">Client</span><Link className="font-semibold text-balance" href={`/clients/view?id=${b.client_id}`}>{client?.name}</Link></div>
        <div className="flex justify-between"><span className="text-muted">Date</span><span>{formatDate(b.bill_date)}</span></div>
        {b.due_date && <div className="flex justify-between"><span className="text-muted">Due</span><span className={pos.overdue ? 'font-semibold text-expense' : ''}>{formatDate(b.due_date)}</span></div>}
        <div className="flex justify-between"><span className="text-muted">Service</span><span className="text-right">{lk.categoryName(b.category_id)} {b.service}</span></div>
        <div className="flex justify-between"><span className="text-muted">Fees charged</span><b className="num">{formatINR(b.amount_paise)}</b></div>
        <div className="flex justify-between"><span className="text-muted">Received</span><b className="num text-income">{formatINR(pos.received)}</b></div>
        <div className="flex justify-between"><span className="text-muted">Balance outstanding</span><b className="num text-expense">{formatINR(Math.max(0, pos.outstanding))}</b></div>
        {b.last_reminded_at && <div className="text-xs text-muted">Last reminded {formatDate(b.last_reminded_at.slice(0, 10))}</div>}
        {b.status === 'cancelled' && <p className="rounded-xl bg-expense-soft p-3 text-expense">Cancelled: {b.cancel_reason}</p>}
        {receipts.length > 0 && (
          <div className="pt-2">
            <div className="label">Receipts adjusted</div>
            {receipts.map(({ a, t }) => (
              <div key={a.id} className={`flex justify-between ${t!.status === 'cancelled' ? 'text-muted line-through' : ''}`}><span>{t!.voucher_no} · {formatDate(t!.txn_date)}</span><span className="num">{formatINR(a.amount_paise)}</span></div>
            ))}
          </div>
        )}
      </div>
    </Sheet>
  )
}

function Inner() {
  const data = useData()
  const store = useStore()
  const lk = useLookups()
  const params = useSearchParams()
  const router = useRouter()
  const [status, setStatus] = useState<StatusFilter>('open')
  const [q, setQ] = useState('')
  const [editing, setEditing] = useState<FeeBill | null>(() => (params.get('new') ? newFeeBill(store, params.get('client') ?? '') : null))
  const [detail, setDetail] = useState<string | null>(null)
  const today = todayIST()
  const all = useMemo(() => billPositions(data, today), [data, today])
  const list = all
    .filter((p) => {
      if (status === 'open' && !(p.status === 'unpaid' || p.status === 'partial')) return false
      if (status === 'overdue' && !p.overdue) return false
      if (status === 'paid' && p.status !== 'paid') return false
      if (status === 'cancelled' && p.status !== 'cancelled') return false
      if (!q) return true
      return `${p.bill.bill_no} ${lk.clientName(p.bill.client_id)} ${p.bill.service} ${lk.categoryName(p.bill.category_id)}`.toLowerCase().includes(q.toLowerCase())
    })
    .sort((a, b) => (a.bill.bill_date < b.bill.bill_date ? 1 : a.bill.bill_date > b.bill.bill_date ? -1 : b.bill.bill_no.localeCompare(a.bill.bill_no)))
  const live = all.filter((p) => p.status !== 'cancelled')
  const charged = live.reduce((s, p) => s + p.bill.amount_paise, 0)
  const received = live.reduce((s, p) => s + p.received, 0)
  const detailPos = all.find((p) => p.bill.id === detail)

  return (
    <div>
      <PageHeader title="Professional Fee Register" subtitle="Fees billed vs fees collected"
        actions={<>
          <Link href="/reports/view?r=fee-register" className="btn-ghost px-2.5" aria-label="Fee register report"><FileText className="size-5" /></Link>
          <button className="btn-primary px-3" onClick={() => setEditing(newFeeBill(store))}><Plus className="size-4" /> Bill</button>
        </>} />
      <div className="mb-3 grid grid-cols-3 gap-2 text-center text-[12px]">
        <div className="card px-2 py-2"><div className="text-muted">Charged</div><b className="num">{formatINR(charged)}</b></div>
        <div className="card px-2 py-2"><div className="text-muted">Received</div><b className="num text-income">{formatINR(received)}</b></div>
        <div className="card px-2 py-2"><div className="text-muted">Outstanding</div><b className="num text-expense">{formatINR(charged - received)}</b></div>
      </div>
      <div className="relative mb-3">
        <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted" />
        <input className="input pl-10" placeholder="Search bill no., client, service…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search bills" />
      </div>
      <div className="-mx-4 mb-3 flex gap-2 overflow-x-auto px-4">
        {(['open', 'overdue', 'paid', 'cancelled', 'all'] as StatusFilter[]).map((s) => (
          <button key={s} className={status === s ? 'chip-active' : 'chip'} onClick={() => setStatus(s)}>{s[0].toUpperCase() + s.slice(1)}</button>
        ))}
      </div>
      {list.length ? (
        <div className="card divide-y divide-line overflow-hidden">
          {list.map((p) => (
            <button key={p.bill.id} className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-elev" onClick={() => setDetail(p.bill.id)}>
              <div className="min-w-0 flex-1">
                <div className="font-semibold">{lk.clientName(p.bill.client_id)}</div>
                <div className="truncate text-xs text-muted">{p.bill.bill_no} · {formatDate(p.bill.bill_date)} · {lk.categoryName(p.bill.category_id)} {p.bill.service}</div>
              </div>
              <div className="text-right">
                <div className="num text-sm font-semibold">{formatINR(p.bill.amount_paise)}</div>
                <Badge tone={p.status === 'paid' ? 'income' : p.status === 'cancelled' ? 'neutral' : p.overdue ? 'expense' : 'warn'}>
                  {p.status === 'paid' ? 'Paid' : p.status === 'cancelled' ? 'Cancelled' : `${p.overdue ? 'Overdue ' : 'Due '}${formatINR(p.outstanding)}`}
                </Badge>
              </div>
            </button>
          ))}
        </div>
      ) : (
        <EmptyState title="No fee bills here" text="Raise fee bills to track what each client owes. Receipts are recorded separately." action={<button className="btn-primary" onClick={() => setEditing(newFeeBill(store))}><Plus className="size-4" /> New fee bill</button>} />
      )}
      {editing && <BillSheet initial={editing} onClose={() => { setEditing(null); if (params.get('new')) router.replace('/fees') }} />}
      {detailPos && <BillDetail pos={detailPos} onClose={() => setDetail(null)} onEdit={() => { setEditing(detailPos.bill); setDetail(null) }} />}
    </div>
  )
}

export default function FeesPage() {
  return (
    <Suspense>
      <Inner />
    </Suspense>
  )
}
