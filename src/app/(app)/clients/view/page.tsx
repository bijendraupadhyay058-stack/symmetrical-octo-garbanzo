'use client'

import { Suspense, useMemo, useState } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { Eye, FileText, Mail, MessageCircle, Pencil, Phone, Plus } from 'lucide-react'
import { useApp, useData } from '@/components/app-provider'
import { useFeedback } from '@/components/feedback'
import { Amount, Badge, PageHeader, StatCard } from '@/components/ui'
import { ClientSheet, maskPan } from '@/components/client-form'
import { TransactionDetail, TxnRow, useLookups } from '@/components/txn'
import { billPositions, clientPositions } from '@/lib/accounting/fees'
import { compareTxns } from '@/lib/accounting/ledger'
import { fyLabel, fyOf, fyRange, formatDate, formatMonth, todayIST } from '@/lib/dates'
import { formatINR } from '@/lib/money'
import { generateReport } from '@/lib/reports/reports'
import { downloadBlob, shareText } from '@/lib/share'
import { safeFileName } from '@/lib/export/format'
import { getSupabase } from '@/lib/supabase/client'
import { verifyBiometric, biometricEnabled, verifyLocalPassword } from '@/lib/security/local-auth'
import type { Transaction } from '@/lib/types'

function Inner() {
  const id = useSearchParams().get('id') ?? ''
  const data = useData()
  const lk = useLookups()
  const { lockScope, user, mode } = useApp()
  const { toast, confirm } = useFeedback()
  const [editing, setEditing] = useState(false)
  const [open, setOpen] = useState<Transaction | null>(null)
  const [panVisible, setPanVisible] = useState(false)
  const client = data.clients.find((c) => c.id === id)
  const pos = useMemo(() => clientPositions(data).get(id), [data, id])
  const bills = useMemo(() => billPositions(data, todayIST()).filter((b) => b.bill.client_id === id), [data, id])
  const receipts = useMemo(() => data.transactions.filter((t) => t.client_id === id && t.type === 'income').sort((a, b) => -compareTxns(a, b)), [data.transactions, id])
  const fyNow = fyOf(todayIST())
  const fyTotal = receipts.filter((t) => t.status === 'active' && fyOf(t.txn_date) === fyNow).reduce((s, t) => s + t.amount_paise, 0)
  const monthly = useMemo(() => {
    const m = new Map<string, number>()
    for (const t of receipts) if (t.status === 'active') m.set(t.txn_date.slice(0, 7), (m.get(t.txn_date.slice(0, 7)) ?? 0) + t.amount_paise)
    return [...m.entries()].sort((a, b) => (a[0] < b[0] ? 1 : -1)).slice(0, 12)
  }, [receipts])
  const yearly = useMemo(() => {
    const m = new Map<number, number>()
    for (const t of receipts) if (t.status === 'active') m.set(fyOf(t.txn_date), (m.get(fyOf(t.txn_date)) ?? 0) + t.amount_paise)
    return [...m.entries()].sort((a, b) => b[0] - a[0])
  }, [receipts])

  if (!client) return <p className="card p-6 text-center text-muted">Client not found. <Link className="text-balance underline" href="/clients">Back</Link></p>

  const revealPan = async () => {
    if (panVisible) return setPanVisible(false)
    // PAN is sensitive: require the user to re-authenticate before showing it.
    if (biometricEnabled(lockScope) && (await verifyBiometric(lockScope))) return setPanVisible(true)
    const r = await confirm({ title: 'Confirm it’s you', message: 'Enter your password to view the full PAN.', input: { label: 'Password', required: true }, confirmLabel: 'Show PAN' })
    if (!r.ok) return
    let ok = await verifyLocalPassword(lockScope, r.value)
    if (!ok && mode === 'cloud' && user && navigator.onLine) ok = !(await getSupabase()!.auth.signInWithPassword({ email: user.email, password: r.value })).error
    if (ok) setPanVisible(true)
    else toast('Incorrect password', 'error')
  }

  const statement = async () => {
    const report = generateReport(data, 'client-statement', { range: { from: '2000-04-01', to: fyRange(fyNow).to }, clientId: id })
    const { reportToPdf } = await import('@/lib/export/pdf')
    downloadBlob((await reportToPdf(report, data.profile)).output('blob'), safeFileName(`Statement_${client.name}`) + '.pdf')
  }

  const remind = async () => {
    const os = bills.filter((b) => b.outstanding > 0)
    if (!os.length) return toast('No outstanding bills for this client', 'info')
    const lines = os.map((b) => `${b.bill.bill_no} dt ${formatDate(b.bill.bill_date)}: ${formatINR(b.outstanding)}`).join('\n')
    const text = `Dear ${client.name},\nThis is a gentle reminder that the following professional fees are outstanding:\n${lines}\nTotal: ${formatINR(pos?.outstanding ?? 0)}\nKindly arrange the payment. Thank you – ${data.profile?.name ?? ''}`
    await shareText(text, client.mobile)
  }

  return (
    <div className="space-y-4">
      <PageHeader title={client.name} subtitle={`${client.code}${client.firm_name ? ' · ' + client.firm_name : ''}${client.is_active ? '' : ' · Inactive'}`} back="/clients"
        actions={<button className="btn-ghost px-2.5" onClick={() => setEditing(true)} aria-label="Edit client"><Pencil className="size-5" /></button>} />

      <div className="card space-y-2 p-4 text-sm">
        {client.mobile && <div className="flex items-center gap-2"><Phone className="size-4 text-muted" /> <a className="text-balance" href={`tel:${client.mobile}`}>{client.mobile}</a></div>}
        {client.email && <div className="flex items-center gap-2"><Mail className="size-4 text-muted" /> <a className="text-balance" href={`mailto:${client.email}`}>{client.email}</a></div>}
        {client.gstin && <div><span className="text-muted">GSTIN:</span> {client.gstin}</div>}
        {client.pan && (
          <div className="flex items-center gap-2"><span className="text-muted">PAN:</span> <span className="num">{panVisible ? client.pan : maskPan(client.pan)}</span>
            <button className="text-balance" onClick={revealPan} aria-label={panVisible ? 'Hide PAN' : 'Show PAN'}><Eye className="size-4" /></button></div>
        )}
        {client.service_type && <div><span className="text-muted">Services:</span> {client.service_type}</div>}
        {client.notes && <div className="text-muted">{client.notes}</div>}
      </div>

      <div className="grid grid-cols-2 gap-3">
        <StatCard label="Total fees received" value={pos?.totalReceived ?? 0} tone="income" />
        <StatCard label={`Received FY ${fyLabel(fyNow)}`} value={fyTotal} tone="income" />
        <StatCard label="Outstanding fees" value={pos?.outstanding ?? 0} tone="expense" sub={`Billed ${formatINR(pos?.billed ?? 0)}`} />
        <StatCard label="On account (unadjusted)" value={pos?.unadjusted ?? 0} tone="balance" />
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Link href={`/add/income?client=${client.id}`} className="btn-income text-sm"><Plus className="size-4" /> Receipt</Link>
        <Link href={`/fees?new=1&client=${client.id}`} className="btn-outline text-sm"><FileText className="size-4" /> Fee bill</Link>
        <button className="btn-outline text-sm" onClick={statement}><FileText className="size-4" /> Statement</button>
        <button className="btn-outline text-sm" onClick={remind}><MessageCircle className="size-4" /> Remind</button>
      </div>

      {bills.length > 0 && (
        <section className="card p-4">
          <h2 className="mb-2 font-bold">Fee bills</h2>
          <ul className="divide-y divide-line">
            {bills.sort((a, b) => (a.bill.bill_date < b.bill.bill_date ? 1 : -1)).map((b) => (
              <li key={b.bill.id} className="flex items-center gap-3 py-2.5 text-sm">
                <div className="min-w-0 flex-1">
                  <div className="font-semibold">{b.bill.bill_no} · {formatDate(b.bill.bill_date)}</div>
                  <div className="truncate text-xs text-muted">{lk.categoryName(b.bill.category_id)} {b.bill.service}</div>
                </div>
                <div className="text-right">
                  <div className="num">{formatINR(b.bill.amount_paise)}</div>
                  <Badge tone={b.status === 'paid' ? 'income' : b.status === 'cancelled' ? 'neutral' : b.overdue ? 'expense' : 'warn'}>
                    {b.status === 'paid' ? 'Paid' : b.status === 'cancelled' ? 'Cancelled' : `Due ${formatINR(b.outstanding)}`}
                  </Badge>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {monthly.length > 0 && (
        <section className="card p-4">
          <h2 className="mb-2 font-bold">Collections</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <div className="label">Monthly (last 12)</div>
              <ul className="space-y-1 text-sm">{monthly.map(([m, v]) => <li key={m} className="flex justify-between"><span>{formatMonth(m)}</span><Amount paise={v} tone="income" /></li>)}</ul>
            </div>
            <div>
              <div className="label">Financial year</div>
              <ul className="space-y-1 text-sm">{yearly.map(([y, v]) => <li key={y} className="flex justify-between"><span>FY {fyLabel(y)}</span><Amount paise={v} tone="income" /></li>)}</ul>
            </div>
          </div>
        </section>
      )}

      <section className="card overflow-hidden">
        <h2 className="px-4 pt-4 pb-1 font-bold">Payment history</h2>
        {receipts.length ? receipts.map((t) => <TxnRow key={t.id} t={t} lk={lk} onOpen={() => setOpen(t)} />) : <p className="px-4 pb-4 text-sm text-muted">No receipts yet.</p>}
      </section>

      {editing && <ClientSheet open onClose={() => setEditing(false)} initial={client} />}
      <TransactionDetail txn={open} onClose={() => setOpen(null)} />
    </div>
  )
}

export default function ClientViewPage() {
  return (
    <Suspense>
      <Inner />
    </Suspense>
  )
}
