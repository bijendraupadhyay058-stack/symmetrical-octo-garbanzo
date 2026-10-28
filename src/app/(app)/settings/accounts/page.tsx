'use client'

import { useState } from 'react'
import { Landmark, Plus, Smartphone, Wallet } from 'lucide-react'
import { useData, useStore } from '@/components/app-provider'
import { useFeedback } from '@/components/feedback'
import { Amount, Badge, Field, MoneyInput, PageHeader, Select, Sheet } from '@/components/ui'
import { balanceAsOf, effectiveOpening } from '@/lib/accounting/ledger'
import { openingBalanceWarning } from '@/lib/accounting/validation'
import { base, newAccount, saveAccount, setOpeningBalance } from '@/lib/store/repo'
import { formatDate, fyRange, fyOf, todayIST } from '@/lib/dates'
import type { Account, AccountKind } from '@/lib/types'

const kindIcon = { cash: Wallet, bank: Landmark, upi: Smartphone }
const kindLabel = { cash: 'Cash', bank: 'Bank', upi: 'UPI' }

export default function AccountsPage() {
  const data = useData()
  const store = useStore()
  const { toast, confirm } = useFeedback()
  const [edit, setEdit] = useState<Account | null>(null)
  const [ob, setOb] = useState<{ account: Account; date: string; amount: number; reason: string } | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const today = todayIST()

  const saveOb = async () => {
    if (!ob) return
    const existing = effectiveOpening(data.opening_balances, ob.account.id).record
    const warning = openingBalanceWarning(data, { ...base(store.businessId), account_id: ob.account.id, as_of_date: ob.date, amount_paise: ob.amount, reason: ob.reason })
    if (existing || warning) {
      const r = await confirm({
        title: existing ? 'Correct opening balance?' : 'Confirm opening balance',
        message: <>{existing && <>This changes every running balance from {formatDate(ob.date)} onwards. The earlier value is kept in the audit history. </>}{warning && <b className="text-expense">{warning}</b>}</>,
        danger: !!warning,
        confirmLabel: 'Yes, I authorise this',
      })
      if (!r.ok) return
    }
    const res = await setOpeningBalance(store, { account_id: ob.account.id, as_of_date: ob.date, amount_paise: ob.amount, reason: ob.reason })
    if (!res.ok) return setErrors(res.errors)
    toast('Opening balance saved')
    setOb(null)
  }

  return (
    <div>
      <PageHeader title="Accounts & Opening Balances" subtitle="Cash affects only the Cash Book; Bank and UPI have their own books" back="/settings" />
      <div className="space-y-3">
        {[...data.accounts].sort((a, b) => a.sort_order - b.sort_order).map((a) => {
          const Icon = kindIcon[a.kind]
          const o = effectiveOpening(data.opening_balances, a.id)
          return (
            <div key={a.id} className={`card p-4 ${a.is_active ? '' : 'opacity-60'}`}>
              <div className="flex items-center gap-3">
                <span className="flex size-10 items-center justify-center rounded-xl bg-balance-soft text-balance"><Icon className="size-5" /></span>
                <div className="min-w-0 flex-1">
                  <div className="font-semibold">{a.name} {!a.is_active && <Badge>Inactive</Badge>}</div>
                  <div className="text-xs text-muted">{kindLabel[a.kind]}{a.details ? ' · ' + a.details : ''}</div>
                </div>
                <div className="text-right">
                  <div className="text-[11px] text-muted">Balance today</div>
                  <Amount paise={balanceAsOf(data, [a.id], today)} tone="auto" className="font-bold" />
                </div>
              </div>
              <div className="mt-3 flex items-center justify-between rounded-xl bg-elev px-3 py-2 text-sm">
                <span className="text-muted">Opening {o.record ? `as on ${formatDate(o.as_of_date)}` : '(not set)'}</span>
                <Amount paise={o.amount} className="font-semibold" />
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <button className="btn-outline text-sm" onClick={() => { setErrors({}); setOb({ account: a, date: o.as_of_date ?? fyRange(fyOf(today)).from, amount: o.amount, reason: '' }) }}>
                  {o.record ? 'Correct opening' : 'Set opening'}
                </button>
                <button className="btn-outline text-sm" onClick={() => { setErrors({}); setEdit(a) }}>Edit account</button>
              </div>
            </div>
          )
        })}
        <div className="grid grid-cols-3 gap-2">
          {(['cash', 'bank', 'upi'] as AccountKind[]).map((k) => (
            <button key={k} className="btn-outline text-sm" onClick={() => { setErrors({}); setEdit(newAccount(store, k)) }}><Plus className="size-4" /> {kindLabel[k]}</button>
          ))}
        </div>
        <p className="text-xs text-muted">Opening balances of later financial years are carried forward automatically from the previous year&apos;s closing, so back-dated corrections always flow through.</p>
      </div>

      {ob && (
        <Sheet open onClose={() => setOb(null)} title={`Opening balance – ${ob.account.name}`} footer={<button className="btn-primary w-full" onClick={saveOb}>Save opening balance</button>}>
          <div className="space-y-3.5">
            <Field label="As on date" error={errors.as_of_date} hint="Usually the day you start using CashBook (or 1 April)">
              <input className="input" type="date" value={ob.date} onChange={(e) => setOb({ ...ob, date: e.target.value })} />
            </Field>
            <Field label="Opening balance" error={errors.amount}><MoneyInput value={ob.amount} onChange={(p) => setOb({ ...ob, amount: p })} /></Field>
            {effectiveOpening(data.opening_balances, ob.account.id).record && (
              <Field label="Reason for correction *" error={errors.reason}><input className="input" value={ob.reason} onChange={(e) => setOb({ ...ob, reason: e.target.value })} placeholder="e.g. physical cash count" /></Field>
            )}
          </div>
        </Sheet>
      )}

      {edit && (
        <Sheet open onClose={() => setEdit(null)} title={data.accounts.some((a) => a.id === edit.id) ? 'Edit account' : 'New account'}
          footer={<button className="btn-primary w-full" onClick={async () => {
            const r = await saveAccount(store, edit)
            if (!r.ok) return setErrors(r.errors)
            toast('Account saved')
            setEdit(null)
          }}>Save account</button>}>
          <div className="space-y-3.5">
            <Field label="Account name" error={errors.name}><input className="input" value={edit.name} placeholder="e.g. HDFC Current A/c" onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
            <Field label="Type" error={errors.kind}>
              <Select value={edit.kind} onChange={(e) => setEdit({ ...edit, kind: e.target.value as AccountKind })}>
                <option value="cash">Cash</option><option value="bank">Bank</option><option value="upi">UPI / Wallet</option>
              </Select>
            </Field>
            <Field label="Details (optional)"><input className="input" value={edit.details} placeholder="A/c no. last 4 digits, UPI ID…" onChange={(e) => setEdit({ ...edit, details: e.target.value })} /></Field>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="size-5" checked={edit.is_active} onChange={(e) => setEdit({ ...edit, is_active: e.target.checked })} /> Active</label>
          </div>
        </Sheet>
      )}
    </div>
  )
}
