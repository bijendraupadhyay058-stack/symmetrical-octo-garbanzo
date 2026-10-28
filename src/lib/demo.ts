import { addDays, todayIST } from './dates'
import {
  defaultBusinessRecords,
  newClient,
  newFeeBill,
  newTransactionDraft,
  saveClient,
  saveFeeBill,
  saveTransaction,
  setOpeningBalance,
  newTemplate,
  saveTemplate,
} from './store/repo'
import type { LocalStore } from './store/store'
import type { PaymentMethod } from './types'

export const DEMO_DB_NAME = 'fintaxpro-demo'
export const DEMO_BUSINESS_ID = '00000000-0000-4000-8000-00000000d3e0'

/**
 * Sample data lives in its own on-device database (never synced, never mixed
 * with real books). Every entry is posted through the same validated code
 * path as real entries so the demo shows genuine ledger behaviour.
 */
export async function seedDemo(store: LocalStore, today = todayIST()) {
  if (store.getSnapshot().profile) return
  await store.save(defaultBusinessRecords(store.businessId, 'SAMPLE DATA – Demo Practice', null))
  const snap = () => store.getSnapshot()
  const acc = (kind: 'cash' | 'bank' | 'upi') => snap().accounts.find((a) => a.kind === kind)!.id
  const cat = (name: string) => snap().categories.find((c) => c.name === name)!.id
  const start = addDays(today, -10)

  await setOpeningBalance(store, { account_id: acc('cash'), as_of_date: start, amount_paise: 10_000_00, reason: '' })
  await setOpeningBalance(store, { account_id: acc('bank'), as_of_date: start, amount_paise: 50_000_00, reason: '' })
  await setOpeningBalance(store, { account_id: acc('upi'), as_of_date: start, amount_paise: 0, reason: '' })

  const mk = async (name: string, firm: string, mobile: string, service: string) => {
    const r = await saveClient(store, { ...newClient(store, name), firm_name: firm, mobile, service_type: service })
    if (!r.ok) throw new Error(JSON.stringify(r.errors))
    return r.value.id
  }
  const sharma = await mk('Rakesh Sharma', 'Sharma Traders', '9876543210', 'GST Returns')
  const gupta = await mk('Neha Gupta', '', '9811122233', 'Income Tax Return')
  const verma = await mk('Verma Enterprises', 'Verma Enterprises Pvt Ltd', '9898989898', 'Accounting')

  const bill = await saveFeeBill(store, { ...newFeeBill(store, sharma), bill_date: addDays(today, -9), due_date: addDays(today, -2), category_id: cat('GST Return Filing Fees'), service: 'GSTR-1 & GSTR-3B (Quarter)', amount_paise: 4_000_00 })
  const vBill = await saveFeeBill(store, { ...newFeeBill(store, verma), bill_date: addDays(today, -8), due_date: addDays(today, 20), category_id: cat('Accounting Fees'), service: 'Monthly accounting', amount_paise: 8_000_00 })
  const gBill = await saveFeeBill(store, { ...newFeeBill(store, gupta), bill_date: addDays(today, -7), due_date: addDays(today, 7), category_id: cat('Income Tax Return Filing Fees'), service: 'ITR-2', amount_paise: 2_500_00 })

  type Entry = { type: 'income' | 'expense'; days: number; amount: number; method: PaymentMethod; account: 'cash' | 'bank' | 'upi'; category: string; client?: string; party?: string; narration: string; allocate?: string }
  const entries: Entry[] = [
    { type: 'income', days: -6, amount: 2_500_00, method: 'cash', account: 'cash', category: 'GST Return Filing Fees', client: sharma, narration: 'GST return filing fees received in cash', allocate: bill.ok ? bill.value.id : undefined },
    { type: 'income', days: -5, amount: 1_500_00, method: 'upi', account: 'upi', category: 'Income Tax Return Filing Fees', client: gupta, narration: 'ITR filing fees via UPI (part payment)', allocate: gBill.ok ? gBill.value.id : undefined },
    { type: 'income', days: -4, amount: 8_000_00, method: 'bank_transfer', account: 'bank', category: 'Accounting Fees', client: verma, narration: 'Accounting fees received by bank transfer', allocate: vBill.ok ? vBill.value.id : undefined },
    { type: 'expense', days: -3, amount: 750_00, method: 'cash', account: 'cash', category: 'Printing and Stationery', party: 'City Stationers', narration: 'Office stationery' },
    { type: 'expense', days: -2, amount: 999_00, method: 'upi', account: 'upi', category: 'Internet and Mobile Recharge', party: 'Airtel Broadband', narration: 'Internet bill' },
    { type: 'expense', days: -1, amount: 350_00, method: 'cash', account: 'cash', category: 'Travelling Expenses', party: 'Auto fare', narration: 'Travel to client office' },
  ]
  for (const e of entries) {
    const d = newTransactionDraft(store, e.type)
    const r = await saveTransaction(
      store,
      {
        ...d,
        txn_date: addDays(today, e.days),
        amount_paise: e.amount,
        payment_method: e.method,
        account_id: acc(e.account),
        category_id: cat(e.category),
        client_id: e.client ?? null,
        party: e.party ?? '',
        narration: e.narration,
        reference_no: e.method === 'cash' ? '' : 'DEMO' + Math.abs(e.days),
      },
      e.allocate ? [{ fee_bill_id: e.allocate, amount_paise: e.amount }] : [],
    )
    if (!r.ok) throw new Error('Demo entry failed: ' + JSON.stringify(r.errors))
  }

  const tpl = newTemplate(store)
  await saveTemplate(store, {
    ...tpl,
    name: 'Office Rent',
    party: 'Landlord – Mr. Mehta',
    category_id: cat('Office Rent'),
    amount_paise: 6_000_00,
    payment_method: 'neft_rtgs',
    account_id: acc('bank'),
    narration: 'Monthly office rent',
    day_of_month: 5,
    next_due_date: addDays(today, 3),
  })
}

/** Expected effect of the demo dataset, shown on the Demo screen and asserted in tests. */
export const DEMO_EXPECTED = {
  cash: { opening: 10_000_00, receipts: 2_500_00, payments: 750_00 + 350_00, closing: 11_400_00 },
  bank: { opening: 50_000_00, receipts: 8_000_00, payments: 0, closing: 58_000_00 },
  upi: { opening: 0, receipts: 1_500_00, payments: 999_00, closing: 501_00 },
  totalIncome: 12_000_00,
  totalExpense: 2_099_00,
  // Bills 4,000 + 8,000 + 2,500 less receipts adjusted 2,500 + 8,000 + 1,500
  outstanding: 2_500_00,
}
