import { openLocalDb } from '@/lib/store/local-db'
import { LocalStore } from '@/lib/store/store'
import { defaultBusinessRecords, newTransactionDraft, saveTransaction, setOpeningBalance } from '@/lib/store/repo'
import { uuid } from '@/lib/ids'
import type { AllocationDraft } from '@/lib/accounting/validation'
import type { PaymentMethod, Transaction } from '@/lib/types'

export async function makeStore(opts: { sync?: boolean; businessId?: string; seed?: boolean } = {}) {
  const db = await openLocalDb('test-' + uuid())
  const businessId = opts.businessId ?? uuid()
  const store = await LocalStore.open(db, businessId, { syncEnabled: opts.sync ?? false, isDemo: false })
  if (opts.seed !== false) await store.save(defaultBusinessRecords(businessId, 'Test Practice', null))
  return store
}

export function ids(store: LocalStore) {
  const s = store.getSnapshot()
  return {
    cash: s.accounts.find((a) => a.kind === 'cash')!.id,
    bank: s.accounts.find((a) => a.kind === 'bank')!.id,
    upi: s.accounts.find((a) => a.kind === 'upi')!.id,
    cat: (name: string) => s.categories.find((c) => c.name === name)!.id,
  }
}

export async function opening(store: LocalStore, account: string, rupees: number, date = '2026-04-01') {
  const r = await setOpeningBalance(store, { account_id: account, as_of_date: date, amount_paise: rupees * 100, reason: 'test' })
  if (!r.ok) throw new Error(JSON.stringify(r.errors))
  return r.value
}

export async function post(
  store: LocalStore,
  e: {
    type: 'income' | 'expense' | 'contra'
    date: string
    rupees: number
    account: string
    to?: string
    method?: PaymentMethod
    category?: string
    client?: string | null
    party?: string
    allocations?: AllocationDraft[]
    id?: string
  },
) {
  const i = ids(store)
  const d = newTransactionDraft(store, e.type)
  const draft: Transaction = {
    ...d,
    id: e.id ?? d.id,
    txn_date: e.date,
    amount_paise: Math.round(e.rupees * 100),
    account_id: e.account,
    to_account_id: e.to ?? null,
    payment_method: e.method ?? (e.type === 'contra' ? 'other' : e.account === i.cash ? 'cash' : 'bank_transfer'),
    category_id: e.type === 'contra' ? null : i.cat(e.category ?? (e.type === 'income' ? 'GST Return Filing Fees' : 'Other Office Expenses')),
    client_id: e.client ?? null,
    party: e.party ?? (e.type === 'contra' ? '' : 'Someone'),
  }
  return saveTransaction(store, draft, e.allocations ?? [])
}

export async function postOk(store: LocalStore, e: Parameters<typeof post>[1]) {
  const r = await post(store, e)
  if (!r.ok) throw new Error(JSON.stringify(r.errors))
  return r.value
}
