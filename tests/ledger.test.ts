import { describe, expect, it } from 'vitest'
import { buildLedger, balanceAsOf } from '@/lib/accounting/ledger'
import { computeDashboard } from '@/lib/accounting/dashboard'
import { ids, makeStore, opening, postOk } from './helpers'

describe('Cash Book', () => {
  it('reproduces the specification example with running balance', async () => {
    const store = await makeStore()
    const i = ids(store)
    await opening(store, i.cash, 10000)
    await postOk(store, { type: 'income', date: '2026-04-02', rupees: 5000, account: i.cash })
    await postOk(store, { type: 'expense', date: '2026-04-03', rupees: 1500, account: i.cash })
    const l = buildLedger(store.getSnapshot(), [i.cash], { from: '2026-04-01', to: '2026-04-30' })
    expect(l.opening).toBe(1000000)
    expect(l.rows.map((r) => [r.voucher_no, r.receipt, r.payment, r.balance])).toEqual([
      ['Opening', 1000000, 0, 1000000],
      ['CR/26-27/001', 500000, 0, 1500000],
      ['CP/26-27/001', 0, 150000, 1350000],
      ['', 0, 0, 1350000],
    ])
    // Opening + Receipts − Payments = Closing
    expect(l.opening + l.totalReceipts - l.totalPayments).toBe(l.closing)
    expect(l.closing).toBe(1350000)
  })

  it('back-dated entries update every later running balance and period opening', async () => {
    const store = await makeStore()
    const i = ids(store)
    await opening(store, i.cash, 10000)
    await postOk(store, { type: 'income', date: '2026-04-10', rupees: 1000, account: i.cash })
    await postOk(store, { type: 'expense', date: '2026-05-02', rupees: 500, account: i.cash })
    // back-dated receipt in April entered later
    await postOk(store, { type: 'income', date: '2026-04-05', rupees: 2000, account: i.cash })
    const may = buildLedger(store.getSnapshot(), [i.cash], { from: '2026-05-01', to: '2026-05-31' })
    expect(may.opening).toBe(1300000)
    expect(may.closing).toBe(1250000)
    const apr = buildLedger(store.getSnapshot(), [i.cash], { from: '2026-04-01', to: '2026-04-30' })
    expect(apr.rows.filter((r) => r.kind === 'entry').map((r) => r.balance)).toEqual([1200000, 1300000])
  })

  it('keeps cash and bank/UPI separate; contra is not income or expense', async () => {
    const store = await makeStore()
    const i = ids(store)
    await opening(store, i.cash, 1000)
    await opening(store, i.bank, 50000)
    await postOk(store, { type: 'income', date: '2026-04-02', rupees: 1500, account: i.upi, method: 'upi' })
    await postOk(store, { type: 'income', date: '2026-04-02', rupees: 8000, account: i.bank, method: 'bank_transfer' })
    await postOk(store, { type: 'contra', date: '2026-04-03', rupees: 2000, account: i.bank, to: i.cash })
    const s = store.getSnapshot()
    expect(balanceAsOf(s, [i.cash], '2026-04-30')).toBe(300000) // 1000 + 2000 withdrawn
    expect(balanceAsOf(s, [i.bank], '2026-04-30')).toBe(5600000)
    expect(balanceAsOf(s, [i.upi], '2026-04-30')).toBe(150000)
    const dash = computeDashboard(s, '2026-04-03', 2026)
    expect(dash.monthIncome).toBe(950000) // contra not counted
    expect(dash.monthExpense).toBe(0)
    expect(dash.monthIncomeCash).toBe(0) // UPI/bank receipts never touch cash
    expect(dash.todayOpeningCash).toBe(100000)
    expect(dash.todayContraCashIn).toBe(200000)
    expect(dash.todayClosingCash).toBe(300000)
  })

  it('cancelled entries are excluded from balances but kept', async () => {
    const store = await makeStore()
    const i = ids(store)
    await opening(store, i.cash, 100)
    const t = await postOk(store, { type: 'income', date: '2026-04-02', rupees: 50, account: i.cash })
    const { cancelTransaction } = await import('@/lib/store/repo')
    const r = await cancelTransaction(store, t.id, 'Entered twice')
    expect(r.ok).toBe(true)
    const s = store.getSnapshot()
    expect(s.transactions).toHaveLength(1)
    expect(s.transactions[0].status).toBe('cancelled')
    expect(balanceAsOf(s, [i.cash], '2026-04-30')).toBe(10000)
  })
})
