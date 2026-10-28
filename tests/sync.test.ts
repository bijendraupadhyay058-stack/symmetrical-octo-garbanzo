import { describe, expect, it } from 'vitest'
import { SyncEngine } from '@/lib/sync/engine'
import { saveTransaction } from '@/lib/store/repo'
import { balanceAsOf } from '@/lib/accounting/ledger'
import { FakeServer } from './fake-remote'
import { ids, makeStore, opening, postOk } from './helpers'

async function twoDevices() {
  const server = new FakeServer()
  const phone = await makeStore({ sync: true })
  const phoneSync = new SyncEngine(phone, server.remote())
  await phoneSync.sync()
  const laptop = await makeStore({ sync: true, businessId: phone.businessId, seed: false })
  const laptopSync = new SyncEngine(laptop, server.remote())
  await laptopSync.sync()
  return { server, phone, phoneSync, laptop, laptopSync }
}

describe('offline capture and synchronisation', () => {
  it('captures offline, shows pending, and syncs exactly once on reconnect', async () => {
    const { server, phone, phoneSync, laptop, laptopSync } = await twoDevices()
    expect(laptop.getSnapshot().accounts).toHaveLength(3)
    const i = ids(phone)
    server.online = false
    await opening(phone, i.cash, 1000)
    await postOk(phone, { type: 'income', date: '2026-04-02', rupees: 500, account: i.cash })
    await phoneSync.sync()
    expect(phoneSync.status.state).toBe('error')
    expect(phoneSync.status.pending).toBe(4) // opening + txn + 2 audit logs
    server.online = true
    await phoneSync.sync()
    expect(phoneSync.status.pending).toBe(0)
    await phoneSync.sync() // nothing pushed twice
    expect(server.table('transactions').size).toBe(1)
    await laptopSync.sync()
    expect(balanceAsOf(laptop.getSnapshot(), [i.cash], '2026-04-30')).toBe(150000)
  })

  it('a lost server reply followed by a retry does not duplicate', async () => {
    const { server, phone, phoneSync } = await twoDevices()
    const i = ids(phone)
    await opening(phone, i.bank, 0)
    const t = await postOk(phone, { type: 'income', date: '2026-04-02', rupees: 500, account: i.bank })
    // Simulate: server stored it but the phone never saw the reply
    const remote = server.remote()
    const { toWire } = await import('@/lib/store/store')
    await remote.push('transactions', toWire(phone.get('transactions', t.id)!), 0)
    await phoneSync.sync()
    expect(server.table('transactions').size).toBe(1)
    expect(phone.get('transactions', t.id)!.version).toBe(1)
    expect(phone.get('transactions', t.id)!._sync?.state).toBe('synced')
  })

  it('concurrent edits on two devices produce a conflict, never a silent overwrite', async () => {
    const { phone, phoneSync, laptop, laptopSync } = await twoDevices()
    const i = ids(phone)
    await opening(phone, i.bank, 0)
    const t = await postOk(phone, { type: 'income', date: '2026-04-02', rupees: 500, account: i.bank })
    await phoneSync.sync()
    await laptopSync.sync()
    const onPhone = phone.get('transactions', t.id)!
    const onLaptop = laptop.get('transactions', t.id)!
    expect((await saveTransaction(phone, { ...onPhone, narration: 'phone edit' })).ok).toBe(true)
    expect((await saveTransaction(laptop, { ...onLaptop, narration: 'laptop edit' })).ok).toBe(true)
    await phoneSync.sync()
    await laptopSync.sync()
    // Laptop: server copy applied, its own copy preserved as a conflict
    expect(laptop.get('transactions', t.id)!.narration).toBe('phone edit')
    expect(laptop.conflicts).toHaveLength(1)
    expect((laptop.conflicts[0].local as { narration: string }).narration).toBe('laptop edit')
    expect(laptop.getSnapshot().audit_logs.some((a) => a.action === 'conflict')).toBe(true)
    // User chooses to keep the laptop version
    await laptopSync.keepMine(laptop.conflicts[0].id)
    await laptopSync.sync()
    await phoneSync.sync()
    expect(phone.get('transactions', t.id)!.narration).toBe('laptop edit')
    expect(laptop.conflicts).toHaveLength(0)
  })

  it('voucher numbers picked offline on two devices are made unique by the server', async () => {
    const { server, phone, phoneSync, laptop, laptopSync } = await twoDevices()
    const i = ids(phone)
    await opening(phone, i.bank, 0)
    await phoneSync.sync()
    await laptopSync.sync()
    server.online = false
    const a = await postOk(phone, { type: 'income', date: '2026-04-02', rupees: 100, account: i.bank })
    const b = await postOk(laptop, { type: 'income', date: '2026-04-02', rupees: 200, account: i.bank })
    expect(a.voucher_no).toBe(b.voucher_no)
    server.online = true
    await phoneSync.sync()
    await laptopSync.sync()
    await phoneSync.sync()
    const vouchers = phone.getSnapshot().transactions.map((t) => t.voucher_no).sort()
    expect(vouchers).toEqual(['BR/26-27/001', 'BR/26-27/002'])
    expect(laptop.getSnapshot().transactions.map((t) => t.voucher_no).sort()).toEqual(vouchers)
  })

  it('a pull never overwrites an unsynced local edit', async () => {
    const { phone, phoneSync, laptop, laptopSync, server } = await twoDevices()
    const i = ids(phone)
    await opening(phone, i.bank, 0)
    const t = await postOk(phone, { type: 'income', date: '2026-04-02', rupees: 500, account: i.bank })
    await phoneSync.sync()
    await laptopSync.sync()
    server.online = false
    await saveTransaction(laptop, { ...laptop.get('transactions', t.id)!, narration: 'offline edit' })
    server.online = true
    await saveTransaction(phone, { ...phone.get('transactions', t.id)!, narration: 'phone edit' })
    await phoneSync.sync()
    // simulate pull-only on laptop
    await laptop.putServerRows('transactions', [server.table('transactions').get(t.id) as never])
    expect(laptop.get('transactions', t.id)!.narration).toBe('offline edit')
  })
})
