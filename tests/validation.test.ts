import { describe, expect, it } from 'vitest'
import { cancelTransaction, newTransactionDraft, restoreTransaction, saveProfile, saveTransaction, setOpeningBalance } from '@/lib/store/repo'
import { findLikelyDuplicate, openingBalanceWarning } from '@/lib/accounting/validation'
import { base } from '@/lib/store/repo'
import { ids, makeStore, opening, post, postOk } from './helpers'

describe('transaction validation', () => {
  it('blocks a cash payment exceeding available cash', async () => {
    const store = await makeStore()
    const i = ids(store)
    await opening(store, i.cash, 1000)
    const r = await post(store, { type: 'expense', date: '2026-04-05', rupees: 1000.01, account: i.cash })
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.errors.amount).toMatch(/Insufficient cash/)
    expect((await post(store, { type: 'expense', date: '2026-04-05', rupees: 1000, account: i.cash })).ok).toBe(true)
  })

  it('blocks a back-dated payment that makes a later day negative', async () => {
    const store = await makeStore()
    const i = ids(store)
    await opening(store, i.cash, 1000)
    await postOk(store, { type: 'income', date: '2026-04-10', rupees: 5000, account: i.cash })
    await postOk(store, { type: 'expense', date: '2026-04-11', rupees: 5500, account: i.cash })
    // On 04-05 there is 1000; paying 800 leaves 200 but then 04-11 would be -300
    const r = await post(store, { type: 'expense', date: '2026-04-05', rupees: 800, account: i.cash })
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.errors.amount).toMatch(/11-04-2026/)
  })

  it('does not apply the cash limit to bank / UPI', async () => {
    const store = await makeStore()
    const i = ids(store)
    expect((await post(store, { type: 'expense', date: '2026-04-05', rupees: 999, account: i.upi, method: 'upi' })).ok).toBe(true)
  })

  it('rejects mismatched payment mode and account', async () => {
    const store = await makeStore()
    const i = ids(store)
    await opening(store, i.cash, 1000)
    const upiToCash = await post(store, { type: 'income', date: '2026-04-05', rupees: 10, account: i.cash, method: 'upi' })
    expect(upiToCash.ok).toBe(false)
    const cashToBank = await post(store, { type: 'income', date: '2026-04-05', rupees: 10, account: i.bank, method: 'cash' })
    expect(cashToBank.ok).toBe(false)
  })

  it('validates required fields and amounts', async () => {
    const store = await makeStore()
    const d = newTransactionDraft(store, 'expense')
    const r = await saveTransaction(store, { ...d, amount_paise: 0 })
    expect(r.ok).toBe(false)
    if (!r.ok) {
      expect(r.errors.amount).toBeTruthy()
      expect(r.errors.category_id).toBeTruthy()
      expect(r.errors.party).toBeTruthy()
    }
  })

  it('refuses dates before the opening balance date and in locked periods', async () => {
    const store = await makeStore()
    const i = ids(store)
    await opening(store, i.cash, 1000, '2026-04-01')
    expect((await post(store, { type: 'income', date: '2026-03-31', rupees: 10, account: i.cash })).ok).toBe(false)
    const p = store.getSnapshot().profile!
    await saveProfile(store, { ...p, settings: { ...p.settings, books_locked_until: '2026-04-30' } })
    const r = await post(store, { type: 'income', date: '2026-04-15', rupees: 10, account: i.cash })
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.errors.txn_date).toMatch(/locked/)
    expect((await post(store, { type: 'income', date: '2026-05-01', rupees: 10, account: i.cash })).ok).toBe(true)
  })

  it('blocks cancelling a receipt that later payments depend on; allows reinstating', async () => {
    const store = await makeStore()
    const i = ids(store)
    await opening(store, i.cash, 0)
    const rec = await postOk(store, { type: 'income', date: '2026-04-02', rupees: 5000, account: i.cash })
    await postOk(store, { type: 'expense', date: '2026-04-03', rupees: 4000, account: i.cash })
    const c = await cancelTransaction(store, rec.id, 'wrong')
    expect(c.ok).toBe(false)
    const other = await postOk(store, { type: 'income', date: '2026-04-04', rupees: 100, account: i.cash })
    expect((await cancelTransaction(store, other.id, '')).ok).toBe(false) // reason required
    expect((await cancelTransaction(store, other.id, 'duplicate')).ok).toBe(true)
    expect((await restoreTransaction(store, other.id)).ok).toBe(true)
  })

  it('editing an amount re-checks cash and keeps the voucher number', async () => {
    const store = await makeStore()
    const i = ids(store)
    await opening(store, i.cash, 1000)
    const t = await postOk(store, { type: 'expense', date: '2026-04-02', rupees: 100, account: i.cash })
    const tooMuch = await saveTransaction(store, { ...t, amount_paise: 200000 })
    expect(tooMuch.ok).toBe(false)
    const ok = await saveTransaction(store, { ...t, amount_paise: 50000 })
    expect(ok.ok && ok.value.voucher_no).toBe(t.voucher_no)
    // switching an expense from cash to bank renumbers into the BP series
    const moved = await saveTransaction(store, { ...t, amount_paise: 50000, account_id: i.bank, payment_method: 'neft_rtgs' })
    expect(moved.ok && moved.value.voucher_no).toBe('BP/26-27/001')
  })

  it('detects likely duplicate submissions', async () => {
    const store = await makeStore()
    const i = ids(store)
    await opening(store, i.cash, 1000)
    const t = await postOk(store, { type: 'income', date: '2026-04-02', rupees: 100, account: i.cash, party: 'Ravi' })
    const again = { ...t, id: base(store.businessId).id }
    expect(findLikelyDuplicate(store.getSnapshot(), again)?.id).toBe(t.id)
    expect(findLikelyDuplicate(store.getSnapshot(), { ...again, amount_paise: 10001 })).toBeNull()
  })

  it('saving the same draft twice never creates two records', async () => {
    const store = await makeStore()
    const i = ids(store)
    await opening(store, i.cash, 1000)
    const a = await postOk(store, { type: 'income', date: '2026-04-02', rupees: 100, account: i.cash, id: 'same-id' })
    const b = await postOk(store, { type: 'income', date: '2026-04-02', rupees: 100, account: i.cash, id: 'same-id' })
    expect(store.getSnapshot().transactions).toHaveLength(1)
    expect(b.voucher_no).toBe(a.voucher_no)
  })

  it('opening balance corrections need a reason, are kept as history, and warn on negative cash', async () => {
    const store = await makeStore()
    const i = ids(store)
    await opening(store, i.cash, 1000)
    await postOk(store, { type: 'expense', date: '2026-04-02', rupees: 900, account: i.cash })
    const noReason = await setOpeningBalance(store, { account_id: i.cash, as_of_date: '2026-04-01', amount_paise: 50000, reason: '' })
    expect(noReason.ok).toBe(false)
    const next = { ...base(store.businessId), account_id: i.cash, as_of_date: '2026-04-01', amount_paise: 50000, reason: 'Physical count' }
    expect(openingBalanceWarning(store.getSnapshot(), next)).toMatch(/-₹400.00/)
    const ok = await setOpeningBalance(store, next)
    expect(ok.ok).toBe(true)
    expect(store.getSnapshot().opening_balances).toHaveLength(2)
    expect(store.getSnapshot().audit_logs.some((a) => a.action === 'opening_balance' && a.summary.includes('corrected'))).toBe(true)
  })
})
