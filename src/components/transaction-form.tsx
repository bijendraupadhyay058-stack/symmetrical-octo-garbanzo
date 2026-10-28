'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { Camera, CheckCircle2, Paperclip, Plus, Search, Share2, X } from 'lucide-react'
import { useData, useStore } from './app-provider'
import { useFeedback } from './feedback'
import { ClientSheet } from './client-form'
import { Field, MoneyInput, PageHeader, Select, Sheet, Textarea } from './ui'
import { useLookups, useTxnActions } from './txn'
import { addAttachment, newTransactionDraft, saveTransaction } from '@/lib/store/repo'
import { nextVoucherNo, voucherMatches, voucherPrefix } from '@/lib/accounting/vouchers'
import { billOutstanding, suggestAllocations } from '@/lib/accounting/fees'
import { balanceAsOf, effectiveOpening } from '@/lib/accounting/ledger'
import { findLikelyDuplicate, type AllocationDraft } from '@/lib/accounting/validation'
import { formatDate, todayIST } from '@/lib/dates'
import { formatINR } from '@/lib/money'
import { compressImage } from '@/lib/share'
import { accountKindsForMethod, PAYMENT_METHODS, type PaymentMethod, type Transaction, type TxnType } from '@/lib/types'

const TITLES: Record<TxnType, string> = { income: 'Add Cash Income', expense: 'Add Business Expense', contra: 'Contra Entry (Cash ⇄ Bank)' }

export function TransactionForm({ type, editId, templateId, clientId }: { type: TxnType; editId?: string | null; templateId?: string | null; clientId?: string | null }) {
  const store = useStore()
  const data = useData()
  const lk = useLookups()
  const router = useRouter()
  const { toast, confirm } = useFeedback()
  const actions = useTxnActions()
  const existing = editId ? data.transactions.find((t) => t.id === editId) : undefined

  const [draft, setDraft] = useState<Transaction>(() => {
    if (existing) return { ...existing }
    const d = newTransactionDraft(store, type)
    const tpl = templateId ? data.recurring_templates.find((t) => t.id === templateId) : undefined
    if (tpl && type === 'expense') {
      return { ...d, party: tpl.party, category_id: tpl.category_id, amount_paise: tpl.amount_paise, payment_method: tpl.payment_method, account_id: tpl.account_id, narration: tpl.narration, recurring_template_id: tpl.id, txn_date: tpl.next_due_date <= todayIST() ? tpl.next_due_date : todayIST() }
    }
    const preClient = type === 'income' && clientId ? data.clients.find((c) => c.id === clientId) : undefined
    return preClient ? { ...d, client_id: preClient.id, party: preClient.firm_name } : d
  })
  const [allocs, setAllocs] = useState<AllocationDraft[]>(() =>
    existing ? data.fee_allocations.filter((a) => a.transaction_id === existing.id && a.amount_paise > 0).map((a) => ({ fee_bill_id: a.fee_bill_id, amount_paise: a.amount_paise })) : [],
  )
  const [allocTouched, setAllocTouched] = useState(!!existing)
  const [files, setFiles] = useState<File[]>([])
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [clientSheet, setClientSheet] = useState(false)
  const [clientQuery, setClientQuery] = useState('')
  const [pickClient, setPickClient] = useState(false)
  const [saved, setSaved] = useState<Transaction | null>(null)
  const savingRef = useRef(false)

  const set = <K extends keyof Transaction>(k: K, v: Transaction[K]) => {
    setDraft((d) => ({ ...d, [k]: v }))
    setErrors((e) => ({ ...e, [k === 'amount_paise' ? 'amount' : k]: '' }))
  }

  const activeAccounts = data.accounts.filter((a) => a.is_active || a.id === draft.account_id || a.id === draft.to_account_id)
  const allowedAccounts = type === 'contra' ? activeAccounts : activeAccounts.filter((a) => accountKindsForMethod(draft.payment_method).includes(a.kind))
  const categories = data.categories.filter((c) => c.kind === type && (c.is_active || c.id === draft.category_id)).sort((a, b) => a.sort_order - b.sort_order)
  const client = data.clients.find((c) => c.id === draft.client_id)

  // Keep the account consistent with the payment method.
  const setMethod = (m: PaymentMethod) => {
    const kinds = accountKindsForMethod(m)
    const cur = data.accounts.find((a) => a.id === draft.account_id)
    let account = draft.account_id
    if (!cur || !kinds.includes(cur.kind)) {
      const pick = activeAccounts.find((a) => a.kind === kinds[0]) ?? activeAccounts.find((a) => kinds.includes(a.kind))
      account = pick?.id ?? ''
    }
    setDraft((d) => ({ ...d, payment_method: m, account_id: account }))
  }

  // Suggest adjusting the receipt against the client's oldest open bills.
  const openBills = useMemo(
    () => (client ? data.fee_bills.filter((b) => b.client_id === client.id && b.status === 'active' && (billOutstanding(data, b.id, draft.id) > 0 || allocs.some((a) => a.fee_bill_id === b.id))) : []),
    [client, data, draft.id, allocs],
  )
  useEffect(() => {
    if (type !== 'income' || allocTouched || !draft.client_id) return
    setAllocs(suggestAllocations(data, draft.client_id, draft.amount_paise, draft.id))
  }, [type, draft.client_id, draft.amount_paise, draft.id, allocTouched, data])

  const voucherPreview = useMemo(() => {
    const kind = data.accounts.find((a) => a.id === draft.account_id)?.kind
    const prefix = voucherPrefix(type, kind)
    if (existing && voucherMatches(existing.voucher_no, prefix, draft.txn_date)) return existing.voucher_no
    return nextVoucherNo(data.transactions.map((t) => t.voucher_no), prefix, draft.txn_date)
  }, [data, draft.account_id, draft.txn_date, existing, type])

  const cashAvailable = useMemo(() => {
    const acc = data.accounts.find((a) => a.id === draft.account_id)
    if (!acc || acc.kind !== 'cash' || (type !== 'expense' && type !== 'contra')) return null
    const others = { ...data, transactions: data.transactions.filter((t) => t.id !== draft.id) }
    return balanceAsOf(others, [acc.id], draft.txn_date)
  }, [data, draft.account_id, draft.txn_date, draft.id, type])

  const payees = useMemo(() => [...new Set(data.transactions.filter((t) => t.type === 'expense' && t.party).map((t) => t.party))].slice(0, 200), [data.transactions])
  const noOpening = !effectiveOpening(data.opening_balances, draft.account_id).record

  const submit = async () => {
    if (savingRef.current) return // duplicate-tap protection
    savingRef.current = true
    setSaving(true)
    try {
      const dup = !existing && findLikelyDuplicate(data, draft)
      if (dup) {
        const r = await confirm({
          title: 'Possible duplicate',
          message: `${dup.voucher_no} on ${formatDate(dup.txn_date)} has the same amount (${formatINR(dup.amount_paise)}), party and account. Save this entry anyway?`,
          confirmLabel: 'Save anyway',
        })
        if (!r.ok) return
      }
      const res = await saveTransaction(store, draft, type === 'income' ? allocs : [])
      if (!res.ok) {
        setErrors(res.errors)
        toast(res.errors.form ?? Object.values(res.errors).find(Boolean) ?? 'Please check the highlighted fields', 'error')
        return
      }
      for (const f of files) {
        const blob = f.type.startsWith('image/') ? await compressImage(f) : f
        const a = await addAttachment(store, res.value.id, blob, f.name)
        if (!a.ok) toast(`${f.name}: ${Object.values(a.errors)[0]}`, 'error')
      }
      setFiles([])
      toast(`${existing ? 'Updated' : 'Saved'} ${res.value.voucher_no} · ${formatINR(res.value.amount_paise)}`)
      if (existing) router.back()
      else setSaved(res.value)
    } finally {
      savingRef.current = false
      setSaving(false)
    }
  }

  const addAnother = () => {
    const d = newTransactionDraft(store, type)
    setDraft({ ...d, txn_date: draft.txn_date, payment_method: draft.payment_method, account_id: draft.account_id })
    setAllocs([])
    setAllocTouched(false)
    setSaved(null)
    setErrors({})
    window.scrollTo({ top: 0 })
  }

  const filteredClients = data.clients
    .filter((c) => c.is_active && (!clientQuery || `${c.name} ${c.firm_name} ${c.mobile} ${c.code}`.toLowerCase().includes(clientQuery.toLowerCase())))
    .sort((a, b) => a.name.localeCompare(b.name))
    .slice(0, 50)

  const accent = type === 'income' ? 'btn-income' : type === 'expense' ? 'btn-expense' : 'btn-primary'
  if (editId && !existing) {
    return <p className="card p-6 text-center text-muted">Entry not found. <Link className="text-balance underline" href="/transactions">Back to transactions</Link></p>
  }
  if (existing?.status === 'cancelled') {
    return <p className="card p-6 text-center text-muted">Cancelled entries cannot be edited. Reinstate it first from the transaction details.</p>
  }

  return (
    <div>
      <PageHeader title={existing ? `Edit ${existing.voucher_no}` : TITLES[type]} subtitle={existing ? 'Changes are recorded in the audit history' : undefined} back="/add" />
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <div className="card space-y-4 p-4">
          <div className="grid grid-cols-2 gap-3">
            <Field label={type === 'expense' ? 'Transaction date' : 'Date'} error={errors.txn_date}>
              <input className="input" type="date" value={draft.txn_date} max="2099-12-31" onChange={(e) => set('txn_date', e.target.value)} required />
            </Field>
            <Field label={type === 'income' ? 'Receipt voucher no.' : type === 'expense' ? 'Expense voucher no.' : 'Voucher no.'} hint="Auto-generated">
              <input className="input num bg-elev font-semibold" value={voucherPreview} readOnly tabIndex={-1} />
            </Field>
          </div>

          {type === 'income' && (
            <>
              <Field label="Client" error={errors.client_id}>
                <button type="button" className="input flex items-center justify-between text-left" onClick={() => setPickClient(true)}>
                  <span className={client ? '' : 'text-muted'}>{client ? `${client.name} (${client.code})` : 'Select client (or leave blank for walk-in)'}</span>
                  <Search className="size-4 text-muted" />
                </button>
              </Field>
              <Field label={client ? 'Business / Firm name (optional)' : 'Received from (name)'} error={!client ? errors.party : undefined}>
                <input className="input" value={draft.party} placeholder={client?.firm_name || ''} onChange={(e) => set('party', e.target.value)} />
              </Field>
            </>
          )}

          {type === 'expense' && (
            <Field label="Paid to *" error={errors.party}>
              <input className="input" list="payees" value={draft.party} onChange={(e) => set('party', e.target.value)} required />
              <datalist id="payees">{payees.map((p) => <option key={p} value={p} />)}</datalist>
            </Field>
          )}

          {type !== 'contra' && (
            <Field label={type === 'income' ? 'Service provided *' : 'Expense category *'} error={errors.category_id}>
              <Select value={draft.category_id ?? ''} onChange={(e) => set('category_id', e.target.value || null)} required>
                <option value="">Select…</option>
                {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </Select>
            </Field>
          )}
          {type === 'income' && (
            <Field label="Service details (optional)">
              <input className="input" value={draft.service} placeholder="e.g. GSTR-3B for September" onChange={(e) => set('service', e.target.value)} />
            </Field>
          )}

          <Field label={type === 'income' ? 'Amount received *' : type === 'expense' ? 'Amount paid *' : 'Amount transferred *'} error={errors.amount}
            hint={cashAvailable !== null ? `Cash available on ${formatDate(draft.txn_date)}: ${formatINR(cashAvailable)}` : undefined}>
            <MoneyInput value={draft.amount_paise} onChange={(p) => set('amount_paise', p)} ariaLabel="Amount" />
          </Field>
        </div>

        <div className="card space-y-4 p-4">
          {type !== 'contra' ? (
            <>
              <div>
                <span className="label">Payment method</span>
                <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Payment method">
                  {PAYMENT_METHODS.map((m) => (
                    <button type="button" key={m.value} role="radio" aria-checked={draft.payment_method === m.value} onClick={() => setMethod(m.value)} className={draft.payment_method === m.value ? 'chip-active' : 'chip'}>
                      {m.label}
                    </button>
                  ))}
                </div>
                <p className="mt-1.5 text-xs text-muted">
                  {draft.payment_method === 'cash' ? 'Posts to the Cash Book.' : 'Posts to the Bank / UPI book – does not change cash in hand.'}
                </p>
              </div>
              {allowedAccounts.length !== 1 || errors.account_id ? (
                <Field label="Account" error={errors.account_id}>
                  <Select value={draft.account_id} onChange={(e) => set('account_id', e.target.value)}>
                    <option value="">Select account…</option>
                    {allowedAccounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                  </Select>
                </Field>
              ) : (
                <p className="text-sm">Account: <b>{allowedAccounts[0].name}</b></p>
              )}
            </>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <Field label="From account" error={errors.account_id}>
                <Select value={draft.account_id} onChange={(e) => set('account_id', e.target.value)}>
                  {activeAccounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </Select>
              </Field>
              <Field label="To account" error={errors.to_account_id}>
                <Select value={draft.to_account_id ?? ''} onChange={(e) => set('to_account_id', e.target.value)}>
                  {activeAccounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </Select>
              </Field>
              <p className="col-span-2 text-xs text-muted">A contra entry moves money between your own accounts (e.g. cash deposited into bank). It is not income or expense.</p>
            </div>
          )}
          {noOpening && draft.account_id && (
            <p className="rounded-xl bg-balance-soft p-3 text-[13px] text-balance">
              Tip: set the opening balance of <b>{lk.accountName(draft.account_id)}</b> in <Link href="/settings/accounts" className="underline">Accounts</Link> for accurate balances.
            </p>
          )}
          <Field label={type === 'expense' ? 'Expense narration' : 'Description / Narration'}>
            <Textarea value={draft.narration} onChange={(e) => set('narration', e.target.value)} />
          </Field>
          <Field label="Reference number (optional)" hint="UPI ref / cheque no. / bill no.">
            <input className="input" value={draft.reference_no} onChange={(e) => set('reference_no', e.target.value)} />
          </Field>
          {type !== 'contra' && (
            <div>
              <span className="label">{type === 'income' ? 'Receipt / attachment (optional)' : 'Bill photo / attachment'}</span>
              <div className="flex flex-wrap gap-2">
                <label className="chip cursor-pointer"><Camera className="size-4" /> Camera<input type="file" accept="image/*" capture="environment" className="hidden" onChange={(e) => e.target.files && setFiles((f) => [...f, ...Array.from(e.target.files!)])} /></label>
                <label className="chip cursor-pointer"><Paperclip className="size-4" /> File<input type="file" accept="image/jpeg,image/png,image/webp,application/pdf" multiple className="hidden" onChange={(e) => e.target.files && setFiles((f) => [...f, ...Array.from(e.target.files!)])} /></label>
              </div>
              {files.map((f, i) => (
                <div key={i} className="mt-2 flex items-center gap-2 rounded-xl bg-elev px-3 py-2 text-sm">
                  <Paperclip className="size-4 text-muted" /> <span className="flex-1 truncate">{f.name}</span>
                  <button type="button" onClick={() => setFiles((x) => x.filter((_, j) => j !== i))} aria-label={`Remove ${f.name}`}><X className="size-4" /></button>
                </div>
              ))}
              {existing && data.attachments.some((a) => a.transaction_id === existing.id) && (
                <p className="mt-2 text-xs text-muted">{data.attachments.filter((a) => a.transaction_id === existing.id).length} file(s) already attached.</p>
              )}
            </div>
          )}
        </div>

        {type === 'income' && client && openBills.length > 0 && (
          <div className="card space-y-3 p-4">
            <div>
              <div className="font-semibold">Adjust against fee bills</div>
              <p className="text-xs text-muted">Reduces the client&apos;s outstanding. The receipt is counted as income only once.</p>
            </div>
            {openBills.map((b) => {
              const a = allocs.find((x) => x.fee_bill_id === b.id)
              const os = billOutstanding(data, b.id, draft.id)
              return (
                <div key={b.id} className="flex items-center gap-3">
                  <input type="checkbox" className="size-5" checked={!!a} aria-label={`Adjust ${b.bill_no}`}
                    onChange={(e) => {
                      setAllocTouched(true)
                      setAllocs((cur) => e.target.checked
                        ? [...cur, { fee_bill_id: b.id, amount_paise: Math.min(os, Math.max(0, draft.amount_paise - cur.reduce((s, x) => s + x.amount_paise, 0))) }]
                        : cur.filter((x) => x.fee_bill_id !== b.id))
                    }} />
                  <div className="min-w-0 flex-1 text-sm">
                    <div className="font-semibold">{b.bill_no} · {formatDate(b.bill_date)}</div>
                    <div className="truncate text-xs text-muted">{lk.categoryName(b.category_id)} {b.service} · Due {formatINR(os)}</div>
                  </div>
                  {a && (
                    <div className="w-32">
                      <MoneyInput value={a.amount_paise} ariaLabel={`Amount for ${b.bill_no}`} onChange={(p) => { setAllocTouched(true); setAllocs((cur) => cur.map((x) => (x.fee_bill_id === b.id ? { ...x, amount_paise: p } : x))) }} />
                    </div>
                  )}
                </div>
              )
            })}
            {errors.allocations && <p role="alert" className="text-sm font-medium text-expense">{errors.allocations}</p>}
          </div>
        )}

        <button type="submit" className={`${accent} sticky bottom-[calc(80px+env(safe-area-inset-bottom))] w-full text-base shadow-lg lg:bottom-4`} disabled={saving}>
          {saving ? 'Saving…' : existing ? 'Save changes' : type === 'income' ? 'Save receipt' : type === 'expense' ? 'Save expense' : 'Save contra entry'}
        </button>
      </form>

      <Sheet open={pickClient} onClose={() => setPickClient(false)} title="Select client">
        <div className="space-y-3">
          <input className="input" placeholder="Search name, firm, mobile…" value={clientQuery} onChange={(e) => setClientQuery(e.target.value)} autoFocus />
          <button type="button" className="btn-outline w-full" onClick={() => { setPickClient(false); setClientSheet(true) }}><Plus className="size-4" /> New client{clientQuery ? ` “${clientQuery}”` : ''}</button>
          {draft.client_id && (
            <button type="button" className="btn-ghost w-full" onClick={() => { set('client_id', null); setAllocs([]); setPickClient(false) }}>No client (walk-in)</button>
          )}
          <ul className="divide-y divide-line">
            {filteredClients.map((c) => (
              <li key={c.id}>
                <button type="button" className="w-full py-3 text-left" onClick={() => { setDraft((d) => ({ ...d, client_id: c.id, party: d.party || c.firm_name })); setAllocTouched(false); setPickClient(false) }}>
                  <div className="font-semibold">{c.name} <span className="text-xs text-muted">{c.code}</span></div>
                  <div className="text-xs text-muted">{[c.firm_name, c.mobile].filter(Boolean).join(' · ')}</div>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </Sheet>
      {clientSheet && (
        <ClientSheet open onClose={() => setClientSheet(false)} defaultName={clientQuery} onSaved={(c) => setDraft((d) => ({ ...d, client_id: c.id, party: c.firm_name }))} />
      )}

      <Sheet open={!!saved} onClose={() => router.push('/transactions')} title="Saved">
        {saved && (
          <div className="space-y-4 text-center">
            <CheckCircle2 className={`mx-auto size-14 ${type === 'expense' ? 'text-expense' : 'text-income'}`} />
            <div>
              <div className="text-lg font-bold">{saved.voucher_no}</div>
              <div className="num text-2xl font-bold">{formatINR(saved.amount_paise)}</div>
              <div className="text-sm text-muted">{formatDate(saved.txn_date)} · {lk.accountName(saved.account_id)}</div>
            </div>
            <div className="grid gap-2">
              {saved.type === 'income' && <button className="btn-outline" onClick={() => actions.share(saved)}><Share2 className="size-4" /> Share receipt on WhatsApp</button>}
              <button className={accent} onClick={addAnother}><Plus className="size-4" /> Add another</button>
              <button className="btn-ghost" onClick={() => router.push('/dashboard')}>Done</button>
            </div>
          </div>
        )}
      </Sheet>
    </div>
  )
}
