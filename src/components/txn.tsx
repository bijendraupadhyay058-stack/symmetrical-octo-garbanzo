'use client'

import { useMemo, useRef, useState, type ReactNode } from 'react'
import Link from 'next/link'
import { ArrowDownLeft, ArrowLeftRight, ArrowUpRight, Ban, Paperclip, Pencil, RotateCcw, Share2, Download, FileText } from 'lucide-react'
import { useApp, useData, useStore } from './app-provider'
import { useFeedback } from './feedback'
import { Amount, Badge, Sheet } from './ui'
import { buildLookups, particularsFor, type Lookups } from '@/lib/accounting/ledger'
import { formatDate, formatDateTime } from '@/lib/dates'
import { formatINR } from '@/lib/money'
import { paymentMethodLabel, type Attachment, type DataSnapshot, type Transaction } from '@/lib/types'
import { cancelTransaction, restoreTransaction } from '@/lib/store/repo'
import { voucherPdf } from '@/lib/export/pdf'
import { downloadBlob, shareFile } from '@/lib/share'
import { getSupabase } from '@/lib/supabase/client'

export function useLookups(): Lookups {
  const d = useData()
  return useMemo(() => buildLookups(d), [d])
}

export function txnTone(t: Transaction): 'income' | 'expense' | 'balance' {
  return t.type === 'income' ? 'income' : t.type === 'expense' ? 'expense' : 'balance'
}

export function TxnIcon({ t }: { t: Transaction }) {
  const cls = t.type === 'income' ? 'bg-income-soft text-income' : t.type === 'expense' ? 'bg-expense-soft text-expense' : 'bg-balance-soft text-balance'
  const Icon = t.type === 'income' ? ArrowDownLeft : t.type === 'expense' ? ArrowUpRight : ArrowLeftRight
  return (
    <span className={`flex size-10 shrink-0 items-center justify-center rounded-xl ${cls}`}>
      <Icon className="size-5" aria-hidden />
    </span>
  )
}

/** A transaction row; swipe left to reveal Edit / Cancel on touch screens. */
export function TxnRow({ t, lk, onOpen, onCancel }: { t: Transaction; lk: Lookups; onOpen: () => void; onCancel?: () => void }) {
  const [dx, setDx] = useState(0)
  const start = useRef<{ x: number; y: number; base: number } | null>(null)
  const acc = lk.account(t.account_id)
  const cancelled = t.status === 'cancelled'
  const pending = t._sync && t._sync.state !== 'synced'
  return (
    <div className="relative overflow-hidden border-b border-line last:border-b-0">
      {!cancelled && (
        <div className="absolute inset-y-0 right-0 flex">
          <Link href={`/add/${t.type}?id=${t.id}`} className="flex w-20 flex-col items-center justify-center gap-0.5 bg-navy-700 text-xs font-semibold text-white">
            <Pencil className="size-4" /> Edit
          </Link>
          {onCancel && (
            <button onClick={onCancel} className="flex w-20 flex-col items-center justify-center gap-0.5 bg-expense text-xs font-semibold text-white">
              <Ban className="size-4" /> Cancel
            </button>
          )}
        </div>
      )}
      <button
        className="relative flex w-full items-center gap-3 bg-surface px-3.5 py-3 text-left transition-transform active:bg-elev"
        style={{ transform: `translateX(${dx}px)`, transitionDuration: start.current ? '0ms' : '180ms' }}
        onTouchStart={(e) => (start.current = { x: e.touches[0].clientX, y: e.touches[0].clientY, base: dx })}
        onTouchMove={(e) => {
          if (!start.current || cancelled) return
          const ddx = e.touches[0].clientX - start.current.x
          const ddy = e.touches[0].clientY - start.current.y
          if (Math.abs(ddy) > Math.abs(ddx)) return
          setDx(Math.max(onCancel ? -160 : -80, Math.min(0, start.current.base + ddx)))
        }}
        onTouchEnd={() => {
          start.current = null
          setDx((v) => (v < -50 ? (onCancel ? -160 : -80) : 0))
        }}
        onClick={() => (dx ? setDx(0) : onOpen())}
      >
        <TxnIcon t={t} />
        <div className="min-w-0 flex-1">
          <div className={`truncate text-[15px] font-semibold ${cancelled ? 'text-muted line-through' : ''}`}>{particularsFor(t, lk)}</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12px] text-muted">
            <span>{formatDate(t.txn_date)}</span>
            <span>{t.voucher_no}</span>
            <span>{t.type === 'contra' ? 'Contra' : `${paymentMethodLabel(t.payment_method)}${acc && acc.kind !== 'cash' ? ' · ' + acc.name : ''}`}</span>
            {cancelled && <Badge tone="expense">Cancelled</Badge>}
            {pending && <Badge tone="warn">Not synced</Badge>}
          </div>
        </div>
        <Amount paise={t.amount_paise} tone={cancelled ? undefined : txnTone(t)} sign={t.type !== 'contra'} className={`text-[15px] font-bold ${cancelled ? 'text-muted line-through' : ''}`} />
      </button>
    </div>
  )
}

export function useTxnActions() {
  const store = useStore()
  const { confirm, toast } = useFeedback()
  const data = useData()
  const lk = useLookups()

  const cancel = async (t: Transaction) => {
    const r = await confirm({
      title: `Cancel ${t.voucher_no}?`,
      message: (
        <>
          The entry stays in the books and audit trail as <b>cancelled</b> and is removed from all balances and totals. {formatINR(t.amount_paise)} dated {formatDate(t.txn_date)}.
        </>
      ),
      danger: true,
      confirmLabel: 'Cancel entry',
      input: { label: 'Reason for cancellation', placeholder: 'e.g. duplicate entry', required: true },
    })
    if (!r.ok) return false
    const res = await cancelTransaction(store, t.id, r.value)
    if (!res.ok) {
      toast(Object.values(res.errors)[0], 'error')
      return false
    }
    toast(`${t.voucher_no} cancelled`)
    return true
  }

  const restore = async (t: Transaction) => {
    const res = await restoreTransaction(store, t.id)
    if (!res.ok) toast(Object.values(res.errors)[0], 'error')
    else toast(`${t.voucher_no} reinstated`)
  }

  const receiptPdf = async (t: Transaction) => {
    const client = data.clients.find((c) => c.id === t.client_id)
    const bills = data.fee_allocations
      .filter((a) => a.transaction_id === t.id && a.amount_paise > 0)
      .map((a) => data.fee_bills.find((b) => b.id === a.fee_bill_id)?.bill_no)
      .filter(Boolean) as string[]
    const doc = await voucherPdf(t, data.profile, {
      partyName: t.type === 'income' ? client?.name || t.party || 'Walk-in client' : t.party,
      partyFirm: t.type === 'income' ? client?.firm_name || (client ? t.party : '') : undefined,
      category: lk.categoryName(t.category_id),
      account: lk.accountName(t.account_id),
      toAccount: lk.accountName(t.to_account_id),
      billNos: bills,
    })
    return { blob: doc.output('blob'), name: `${t.voucher_no.replace(/\//g, '-')}.pdf`, client }
  }

  const share = async (t: Transaction) => {
    try {
      const { blob, name, client } = await receiptPdf(t)
      const text =
        t.type === 'income'
          ? `Receipt ${t.voucher_no}: Received ${formatINR(t.amount_paise)} on ${formatDate(t.txn_date)} towards ${lk.categoryName(t.category_id)}. Thank you – ${data.profile?.name ?? ''}`
          : `Voucher ${t.voucher_no}: ${formatINR(t.amount_paise)} on ${formatDate(t.txn_date)}`
      const out = await shareFile(blob, name, text, client?.mobile)
      if (out === 'downloaded') toast('Receipt PDF downloaded – attach it in WhatsApp', 'info')
    } catch (e) {
      toast('Could not create receipt: ' + (e instanceof Error ? e.message : e), 'error')
    }
  }

  const download = async (t: Transaction) => {
    const { blob, name } = await receiptPdf(t)
    downloadBlob(blob, name)
  }

  return { cancel, restore, share, download }
}

function AttachmentLink({ a }: { a: Attachment }) {
  const store = useStore()
  const { toast } = useFeedback()
  const open = async () => {
    const local = await store.getBlob(a.id)
    let blob = local?.blob
    if (!blob && a.storage_path) {
      const sb = getSupabase()
      const { data, error } = (await sb?.storage.from('attachments').createSignedUrl(a.storage_path, 120)) ?? { data: null, error: null }
      if (data?.signedUrl) return window.open(data.signedUrl, '_blank', 'noopener')
      return toast(error?.message ?? 'File is not available offline', 'error')
    }
    if (!blob) return toast('File is not available on this device', 'error')
    const url = URL.createObjectURL(blob)
    window.open(url, '_blank', 'noopener')
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  }
  return (
    <button onClick={open} className="flex w-full items-center gap-2 rounded-xl border border-line px-3 py-2.5 text-left text-sm hover:bg-elev">
      <Paperclip className="size-4 shrink-0 text-muted" />
      <span className="min-w-0 flex-1 truncate">{a.file_name}</span>
      <span className="text-xs text-muted">{Math.ceil(a.size_bytes / 1024)} KB</span>
    </button>
  )
}

function Row({ k, v }: { k: string; v: ReactNode }) {
  if (v === '' || v === null || v === undefined) return null
  return (
    <div className="flex gap-3 border-b border-line py-2 text-sm last:border-b-0">
      <span className="w-32 shrink-0 text-muted">{k}</span>
      <span className="min-w-0 flex-1 font-medium break-words">{v}</span>
    </div>
  )
}

export function TransactionDetail({ txn, onClose }: { txn: Transaction | null; onClose: () => void }) {
  const data = useData()
  const lk = useLookups()
  const { mode } = useApp()
  const actions = useTxnActions()
  if (!txn) return null
  const t = data.transactions.find((x) => x.id === txn.id) ?? txn
  const client = data.clients.find((c) => c.id === t.client_id)
  const allocs = data.fee_allocations.filter((a) => a.transaction_id === t.id && a.amount_paise > 0)
  const atts = data.attachments.filter((a) => a.transaction_id === t.id)
  const history = data.audit_logs.filter((a) => a.entity_id === t.id && a.source === 'app').sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
  const cancelled = t.status === 'cancelled'
  return (
    <Sheet
      open
      onClose={onClose}
      title={t.voucher_no}
      footer={
        <div className="grid grid-cols-2 gap-2">
          {!cancelled ? (
            <>
              <button className="btn-outline" onClick={() => actions.share(t)}><Share2 className="size-4" /> Share</button>
              <Link href={`/add/${t.type}?id=${t.id}`} className="btn-primary"><Pencil className="size-4" /> Edit</Link>
              <button className="btn-outline" onClick={() => actions.download(t)}><Download className="size-4" /> PDF</button>
              <button className="btn-outline text-expense" onClick={async () => (await actions.cancel(t)) && onClose()}><Ban className="size-4" /> Cancel entry</button>
            </>
          ) : (
            <>
              <button className="btn-outline" onClick={() => actions.download(t)}><FileText className="size-4" /> PDF</button>
              <button className="btn-outline" onClick={() => actions.restore(t)}><RotateCcw className="size-4" /> Reinstate</button>
            </>
          )}
        </div>
      }
    >
      <div className="mb-3 flex items-center gap-3">
        <TxnIcon t={t} />
        <div className="flex-1">
          <div className="text-sm text-muted">{t.type === 'income' ? 'Receipt' : t.type === 'expense' ? 'Payment' : 'Contra transfer'}</div>
          <Amount paise={t.amount_paise} tone={cancelled ? undefined : txnTone(t)} className="text-2xl font-bold" />
        </div>
        {cancelled && <Badge tone="expense">Cancelled</Badge>}
      </div>
      {cancelled && <p className="mb-3 rounded-xl bg-expense-soft p-3 text-sm text-expense">Reason: {t.cancel_reason}</p>}
      <div>
        <Row k="Date" v={formatDate(t.txn_date)} />
        {t.type === 'income' && <Row k="Client" v={client ? <Link className="text-balance underline" href={`/clients/view?id=${client.id}`}>{client.name} ({client.code})</Link> : t.party} />}
        {t.type === 'income' && client && <Row k="Firm" v={t.party || client.firm_name} />}
        {t.type === 'expense' && <Row k="Paid to" v={t.party} />}
        {t.type !== 'contra' && <Row k={t.type === 'income' ? 'Service' : 'Category'} v={lk.categoryName(t.category_id) + (t.service ? ` – ${t.service}` : '')} />}
        {t.type === 'contra' ? (
          <>
            <Row k="From" v={lk.accountName(t.account_id)} />
            <Row k="To" v={lk.accountName(t.to_account_id)} />
          </>
        ) : (
          <Row k="Mode / Account" v={`${paymentMethodLabel(t.payment_method)} · ${lk.accountName(t.account_id)}`} />
        )}
        <Row k="Reference" v={t.reference_no} />
        <Row k="Narration" v={t.narration} />
        {allocs.length > 0 && (
          <Row k="Against bills" v={allocs.map((a) => `${data.fee_bills.find((b) => b.id === a.fee_bill_id)?.bill_no} (${formatINR(a.amount_paise)})`).join(', ')} />
        )}
        {mode === 'cloud' && <Row k="Sync" v={t._sync?.state === 'synced' ? 'Uploaded' : t._sync?.state === 'error' ? `Error: ${t._sync.error}` : 'Waiting to upload'} />}
      </div>
      {atts.length > 0 && (
        <div className="mt-4 space-y-2">
          <div className="label">Attachments</div>
          {atts.map((a) => <AttachmentLink key={a.id} a={a} />)}
        </div>
      )}
      {history.length > 0 && (
        <details className="mt-4">
          <summary className="cursor-pointer text-sm font-semibold text-balance">Edit history ({history.length})</summary>
          <ul className="mt-2 space-y-1.5 text-[13px]">
            {history.map((h) => (
              <li key={h.id} className="rounded-lg bg-elev px-3 py-2">
                <div className="font-medium">{h.summary}</div>
                <div className="text-xs text-muted">{formatDateTime(h.created_at)}</div>
              </li>
            ))}
          </ul>
        </details>
      )}
    </Sheet>
  )
}

export function snapshotTxn(d: DataSnapshot, id: string | null): Transaction | null {
  return id ? d.transactions.find((t) => t.id === id) ?? null : null
}
