import { nextVoucherNo, parseVoucher, type VoucherPrefix } from '@/lib/accounting/vouchers'
import type { PushResult, Remote } from '@/lib/sync/engine'
import type { AnyRecord } from '@/lib/store/store'
import type { TableName } from '@/lib/types'

/** In-memory server mirroring the semantics of public.sync_push (see migrations). */
export class FakeServer {
  tables = new Map<string, Map<string, Record<string, unknown>>>()
  seq = 0
  online = true
  pushes = 0
  files = new Map<string, Blob>()

  table(t: string) {
    let m = this.tables.get(t)
    if (!m) this.tables.set(t, (m = new Map()))
    return m
  }

  remote(): Remote {
    return {
      push: async (table: TableName, row, baseVersion): Promise<PushResult> => {
        if (!this.online) return { status: 'error', message: 'Failed to fetch', retryable: true }
        this.pushes++
        const t = this.table(table)
        const existing = t.get(row.id as string)
        const data = { ...row }
        if (table === 'transactions') {
          const clash = [...t.values()].some((r) => r.voucher_no === data.voucher_no && r.id !== data.id)
          if (clash) {
            const p = parseVoucher(String(data.voucher_no))!
            data.voucher_no = nextVoucherNo([...t.values()].map((r) => String(r.voucher_no)), p.prefix as VoucherPrefix, String(data.txn_date))
          }
        }
        if (!existing) {
          const rec = { ...data, version: 1, sync_seq: ++this.seq }
          t.set(rec.id as string, rec)
          return { status: 'ok', row: structuredClone(rec) as unknown as AnyRecord }
        }
        const same = Object.keys(row).every((k) => k === 'version' || k === 'updated_at' || JSON.stringify(existing[k]) === JSON.stringify(row[k]))
        if (same) return { status: 'ok', row: structuredClone(existing) as unknown as AnyRecord }
        if ((existing.version as number) !== Math.max(baseVersion, 1)) return { status: 'conflict', row: structuredClone(existing) as unknown as AnyRecord }
        const rec = { ...existing, ...data, version: (existing.version as number) + 1, sync_seq: ++this.seq }
        t.set(rec.id as string, rec)
        return { status: 'ok', row: structuredClone(rec) as unknown as AnyRecord }
      },
      pull: async (table, businessId, since, limit) => {
        if (!this.online) throw new Error('Failed to fetch')
        const rows = [...this.table(table).values()]
          .filter((r) => r.business_id === businessId && (r.sync_seq as number) > since)
          .sort((a, b) => (a.sync_seq as number) - (b.sync_seq as number))
          .slice(0, limit)
        return { rows: structuredClone(rows) as never }
      },
      uploadAttachment: async (path, blob) => {
        this.files.set(path, blob)
      },
      downloadAttachment: async (path) => this.files.get(path)!,
    }
  }
}
