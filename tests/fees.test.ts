import { describe, expect, it } from 'vitest'
import { billPositions, clientPositions, suggestAllocations } from '@/lib/accounting/fees'
import { cancelFeeBill, cancelTransaction, newClient, newFeeBill, saveClient, saveFeeBill } from '@/lib/store/repo'
import { computeDashboard } from '@/lib/accounting/dashboard'
import { ids, makeStore, opening, post, postOk } from './helpers'

async function setup() {
  const store = await makeStore()
  const i = ids(store)
  await opening(store, i.cash, 0)
  const c = await saveClient(store, { ...newClient(store, 'Sharma Traders'), mobile: '9876543210' })
  if (!c.ok) throw new Error('client')
  const b = await saveFeeBill(store, { ...newFeeBill(store, c.value.id), bill_date: '2026-04-01', category_id: i.cat('GST Return Filing Fees'), amount_paise: 400000 })
  if (!b.ok) throw new Error(JSON.stringify(b.errors))
  return { store, i, client: c.value, bill: b.value }
}

describe('professional fee register', () => {
  it('billing is not income; receipts reduce outstanding', async () => {
    const { store, i, client, bill } = await setup()
    expect(bill.bill_no).toBe('FB/26-27/001')
    let dash = computeDashboard(store.getSnapshot(), '2026-04-02', 2026)
    expect(dash.monthIncome).toBe(0)
    expect(dash.outstandingFees).toBe(400000)
    await postOk(store, { type: 'income', date: '2026-04-02', rupees: 2500, account: i.cash, client: client.id, allocations: [{ fee_bill_id: bill.id, amount_paise: 250000 }] })
    dash = computeDashboard(store.getSnapshot(), '2026-04-02', 2026)
    expect(dash.monthIncome).toBe(250000)
    expect(dash.outstandingFees).toBe(150000)
    const [pos] = billPositions(store.getSnapshot())
    expect(pos.status).toBe('partial')
    const cp = clientPositions(store.getSnapshot()).get(client.id)!
    expect(cp).toMatchObject({ billed: 400000, allocated: 250000, outstanding: 150000, totalReceived: 250000, unadjusted: 0 })
  })

  it('cannot over-allocate a bill or allocate more than received', async () => {
    const { store, i, client, bill } = await setup()
    const r1 = await post(store, { type: 'income', date: '2026-04-02', rupees: 5000, account: i.cash, client: client.id, allocations: [{ fee_bill_id: bill.id, amount_paise: 500000 }] })
    expect(r1.ok).toBe(false)
    const r2 = await post(store, { type: 'income', date: '2026-04-02', rupees: 1000, account: i.cash, client: client.id, allocations: [{ fee_bill_id: bill.id, amount_paise: 200000 }] })
    expect(r2.ok).toBe(false)
  })

  it('cancelling a receipt restores the outstanding; bills with receipts cannot be cancelled', async () => {
    const { store, i, client, bill } = await setup()
    const t = await postOk(store, { type: 'income', date: '2026-04-02', rupees: 4000, account: i.cash, client: client.id, allocations: [{ fee_bill_id: bill.id, amount_paise: 400000 }] })
    expect(billPositions(store.getSnapshot())[0].status).toBe('paid')
    expect((await cancelFeeBill(store, bill.id, 'x')).ok).toBe(false)
    await cancelTransaction(store, t.id, 'bounced')
    expect(billPositions(store.getSnapshot())[0].outstanding).toBe(400000)
    expect((await cancelFeeBill(store, bill.id, 'waived')).ok).toBe(true)
    expect(computeDashboard(store.getSnapshot(), '2026-04-02', 2026).outstandingFees).toBe(0)
  })

  it('suggests oldest-first allocation and tracks unadjusted receipts', async () => {
    const { store, i, client, bill } = await setup()
    const b2 = await saveFeeBill(store, { ...newFeeBill(store, client.id), bill_date: '2026-04-05', service: 'TDS', amount_paise: 100000 })
    if (!b2.ok) throw new Error()
    const s = suggestAllocations(store.getSnapshot(), client.id, 450000)
    expect(s).toEqual([{ fee_bill_id: bill.id, amount_paise: 400000 }, { fee_bill_id: b2.value.id, amount_paise: 50000 }])
    await postOk(store, { type: 'income', date: '2026-04-06', rupees: 6000, account: i.cash, client: client.id, allocations: s })
    const cp = clientPositions(store.getSnapshot()).get(client.id)!
    expect(cp.outstanding).toBe(50000)
    expect(cp.unadjusted).toBe(150000)
  })
})
