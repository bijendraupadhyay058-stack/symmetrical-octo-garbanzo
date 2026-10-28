import { nowISO } from '../ids'
import { TABLES, type BaseRecord, type DataSnapshot, type TableMap, type TableName } from '../types'
import type { ConflictRecord, LocalDb } from './local-db'

export type AnyRecord = TableMap[TableName]

export interface Change<T extends TableName = TableName> {
  table: T
  record: TableMap[T]
}

export interface PendingItem {
  table: TableName
  record: AnyRecord
}

function emptySnapshot(businessId: string): DataSnapshot {
  return {
    businessId,
    profile: null,
    accounts: [],
    opening_balances: [],
    categories: [],
    clients: [],
    transactions: [],
    fee_bills: [],
    fee_allocations: [],
    recurring_templates: [],
    attachments: [],
    audit_logs: [],
  }
}

/** Strips local-only and server bookkeeping fields before a record leaves the device. */
export function toWire(record: AnyRecord): Record<string, unknown> {
  const { _sync, ...rest } = record as unknown as BaseRecord & Record<string, unknown>
  void _sync
  delete rest.sync_seq
  return rest
}

/**
 * In-memory mirror of the IndexedDB database for one business. Every write goes
 * to IndexedDB first (in a single transaction) and only then updates memory, so
 * a crash can never leave the UI showing data that was not saved.
 */
export class LocalStore {
  private listeners = new Set<() => void>()
  private snap: DataSnapshot
  conflicts: ConflictRecord[] = []

  private constructor(
    readonly db: LocalDb,
    readonly businessId: string,
    readonly options: { syncEnabled: boolean; isDemo: boolean },
  ) {
    this.snap = emptySnapshot(businessId)
  }

  static async open(db: LocalDb, businessId: string, options: { syncEnabled: boolean; isDemo: boolean }) {
    const s = new LocalStore(db, businessId, options)
    await s.reload()
    return s
  }

  async reload() {
    const next = emptySnapshot(this.businessId)
    for (const t of TABLES) {
      const all = (await this.db.getAll(t)) as AnyRecord[]
      const rows = all.filter((r) => r.business_id === this.businessId)
      if (t === 'business_profiles') next.profile = (rows[0] as DataSnapshot['profile']) ?? null
      else (next[t] as AnyRecord[]) = rows
    }
    this.conflicts = (await this.db.getAll('conflicts')) as ConflictRecord[]
    this.snap = next
    this.emit()
  }

  subscribe = (fn: () => void) => {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }

  getSnapshot = (): DataSnapshot => this.snap

  private emit() {
    for (const fn of this.listeners) fn()
  }

  private applyToMemory(table: TableName, record: AnyRecord) {
    if (table === 'business_profiles') {
      this.snap = { ...this.snap, profile: record as DataSnapshot['profile'] }
      return
    }
    const list = this.snap[table] as AnyRecord[]
    const idx = list.findIndex((r) => r.id === record.id)
    const next = idx >= 0 ? [...list.slice(0, idx), record, ...list.slice(idx + 1)] : [...list, record]
    this.snap = { ...this.snap, [table]: next }
  }

  get<T extends TableName>(table: T, id: string): TableMap[T] | undefined {
    if (table === 'business_profiles') return (this.snap.profile?.id === id ? this.snap.profile : undefined) as TableMap[T]
    const list = this.snap[table as Exclude<TableName, 'business_profiles'>] as AnyRecord[]
    return list.find((r) => r.id === id) as TableMap[T] | undefined
  }

  /**
   * Save local edits atomically. Each record is marked pending so the sync
   * engine pushes it; `version` is left untouched (it is the server version
   * the edit was based on, used for conflict detection).
   */
  async save(changes: Change[]): Promise<void> {
    if (!changes.length) return
    const now = nowISO()
    const stores = [...new Set(changes.map((c) => c.table))]
    const tx = this.db.transaction(stores, 'readwrite')
    const prepared: Change[] = changes.map((c) => ({
      table: c.table,
      record: {
        ...c.record,
        business_id: this.businessId,
        updated_at: now,
        _sync: this.options.syncEnabled ? { state: 'pending', changed_at: now } : { state: 'synced', changed_at: now },
      } as AnyRecord,
    }))
    for (const c of prepared) await tx.objectStore(c.table).put(c.record)
    await tx.done
    for (const c of prepared) this.applyToMemory(c.table, c.record)
    this.emit()
  }

  /**
   * Store rows exactly as received from the server (already synced).
   * `expectChangedAt`: only overwrite a pending local record if it is still
   * the exact edit we pushed (a newer local save in the meantime wins).
   */
  async putServerRows(
    table: TableName,
    rows: AnyRecord[],
    opts: { overwritePending?: boolean; expectChangedAt?: string } = {},
  ): Promise<number> {
    if (!rows.length) return 0
    const tx = this.db.transaction(table, 'readwrite')
    const store = tx.objectStore(table)
    const written: AnyRecord[] = []
    for (const row of rows) {
      const local = (await store.get(row.id)) as AnyRecord | undefined
      // Never overwrite an unsynced local edit during a pull; the push step
      // detects version conflicts and preserves both copies.
      if (local?._sync && local._sync.state !== 'synced') {
        if (!opts.overwritePending) continue
        if (opts.expectChangedAt !== undefined && local._sync.changed_at !== opts.expectChangedAt) continue
      }
      const rec = { ...row, _sync: { state: 'synced', changed_at: nowISO() } } as AnyRecord
      await store.put(rec)
      written.push(rec)
    }
    await tx.done
    for (const r of written) if (r.business_id === this.businessId) this.applyToMemory(table, r)
    if (written.length) this.emit()
    return written.length
  }

  async markError(table: TableName, id: string, message: string) {
    const rec = (await this.db.get(table, id)) as AnyRecord | undefined
    if (!rec) return
    const next = { ...rec, _sync: { ...(rec._sync ?? { changed_at: nowISO() }), state: 'error', error: message } } as AnyRecord
    await this.db.put(table, next)
    this.applyToMemory(table, next)
    this.emit()
  }

  /** All unsynced records in push order: parent tables first, then oldest change first. */
  pending(): PendingItem[] {
    const out: PendingItem[] = []
    for (const t of TABLES) {
      const rows: AnyRecord[] = t === 'business_profiles' ? (this.snap.profile ? [this.snap.profile] : []) : (this.snap[t] as AnyRecord[])
      const p = rows.filter((r) => r._sync && r._sync.state !== 'synced')
      p.sort((a, b) => (a._sync!.changed_at < b._sync!.changed_at ? -1 : 1))
      for (const r of p) out.push({ table: t, record: r })
    }
    return out
  }

  pendingCount(): number {
    return this.pending().length
  }

  async addConflict(c: ConflictRecord) {
    await this.db.put('conflicts', c)
    this.conflicts = [...this.conflicts.filter((x) => x.id !== c.id), c]
    this.emit()
  }

  async removeConflict(id: string) {
    await this.db.delete('conflicts', id)
    this.conflicts = this.conflicts.filter((x) => x.id !== id)
    this.emit()
  }

  async getMeta<T>(key: string): Promise<T | undefined> {
    return (await this.db.get('meta', key)) as T | undefined
  }

  async setMeta(key: string, value: unknown) {
    await this.db.put('meta', value, key)
  }

  async putBlob(id: string, blob: Blob, mime_type: string) {
    await this.db.put('blobs', { id, blob, mime_type })
  }

  async getBlob(id: string): Promise<{ blob: Blob; mime_type: string } | undefined> {
    return (await this.db.get('blobs', id)) as { blob: Blob; mime_type: string } | undefined
  }
}
