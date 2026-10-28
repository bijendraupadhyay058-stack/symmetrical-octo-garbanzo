import { describe, expect, it } from 'vitest'
import { createBackup, parseBackup, restoreBackup } from '@/lib/backup'
import { seedDemo } from '@/lib/demo'
import { buildLedger } from '@/lib/accounting/ledger'
import { makeStore } from './helpers'

describe('backup & restore', () => {
  it('round-trips into an empty device of the same business', async () => {
    const src = await makeStore({ seed: false })
    await seedDemo(src, '2026-10-28')
    const file = JSON.stringify(await createBackup(src))
    const parsed = await parseBackup(file)
    expect(parsed.ok).toBe(true)
    const dst = await makeStore({ seed: false, businessId: src.businessId, sync: true })
    if (!parsed.ok) return
    const res = await restoreBackup(dst, parsed.backup)
    expect(res.added.transactions).toBe(6)
    expect(dst.getSnapshot().transactions).toHaveLength(6)
    // re-running restore adds nothing and changes nothing
    const again = await restoreBackup(dst, parsed.backup)
    expect(again.added.transactions ?? 0).toBe(0)
    expect(again.skipped.transactions).toBe(6)
    const cash = (s: typeof src) => s.getSnapshot().accounts.find((a) => a.kind === 'cash')!.id
    const r = { from: '2026-04-01', to: '2027-03-31' }
    expect(buildLedger(dst.getSnapshot(), [cash(dst)], r).closing).toBe(buildLedger(src.getSnapshot(), [cash(src)], r).closing)
    expect(dst.pendingCount()).toBeGreaterThan(0) // restored data will be uploaded
  })

  it('rejects damaged or foreign files', async () => {
    const src = await makeStore({ seed: false })
    await seedDemo(src, '2026-10-28')
    const b = await createBackup(src)
    ;(b.tables.transactions![0] as { amount_paise: number }).amount_paise = 1
    expect((await parseBackup(JSON.stringify(b))).ok).toBe(false)
    expect((await parseBackup('{"hello":1}')).ok).toBe(false)
    expect((await parseBackup('not json')).ok).toBe(false)
  })

  it('restores another business by re-keying, without touching existing records', async () => {
    const src = await makeStore({ seed: false })
    await seedDemo(src, '2026-10-28')
    const dst = await makeStore()
    const before = dst.getSnapshot().categories.length
    const parsed = await parseBackup(JSON.stringify(await createBackup(src)))
    if (!parsed.ok) throw new Error(parsed.error)
    await restoreBackup(dst, parsed.backup)
    const s = dst.getSnapshot()
    expect(s.categories.length).toBe(before) // matched by name, no duplicates
    expect(s.transactions).toHaveLength(6)
    expect(s.transactions.every((t) => t.business_id === dst.businessId)).toBe(true)
    expect(s.transactions.some((t) => src.getSnapshot().transactions.some((x) => x.id === t.id))).toBe(false)
    expect(s.profile!.name).toBe('Test Practice')
  })
})
