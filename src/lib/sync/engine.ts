import { uuid, nowISO } from '../ids'
import { TABLES, type TableName } from '../types'
import { auditRecord } from '../store/repo'
import { toWire, type AnyRecord, type LocalStore } from '../store/store'

export type PushResult =
  | { status: 'ok'; row: AnyRecord }
  | { status: 'conflict'; row: AnyRecord }
  | { status: 'error'; message: string; retryable: boolean }

export interface Remote {
  push(table: TableName, row: Record<string, unknown>, baseVersion: number): Promise<PushResult>
  pull(table: TableName, businessId: string, sinceSeq: number, limit: number): Promise<{ rows: (AnyRecord & { sync_seq: number })[] }>
  uploadAttachment(path: string, blob: Blob, contentType: string): Promise<void>
  downloadAttachment(path: string): Promise<Blob>
}

export interface SyncStatus {
  state: 'idle' | 'syncing' | 'offline' | 'error' | 'disabled'
  pending: number
  errors: number
  conflicts: number
  lastSyncAt: string | null
  lastError: string | null
}

const PULL_LIMIT = 500
const PULL_OVERLAP = 50

/**
 * Push-then-pull synchronisation.
 *
 * Guarantees:
 *  - Records carry client-generated UUIDs, so retrying a push after a network
 *    failure updates the same row instead of inserting a duplicate.
 *  - Updates carry the server version they were based on. If the server row
 *    moved on (edited on another device), the server refuses the write and
 *    returns its copy; we keep BOTH copies (server copy applied, local copy
 *    saved as a conflict + audit entry) for the user to resolve. Nothing is
 *    silently overwritten.
 *  - Pulls never overwrite records that still have unsynced local edits.
 */
export class SyncEngine {
  private running: Promise<void> | null = null
  private listeners = new Set<() => void>()
  status: SyncStatus

  constructor(private store: LocalStore, private remote: Remote | null) {
    this.status = {
      state: remote ? 'idle' : 'disabled',
      pending: store.pendingCount(),
      errors: 0,
      conflicts: store.conflicts.length,
      lastSyncAt: null,
      lastError: null,
    }
    store.subscribe(() => this.refreshCounts())
    void store.getMeta<string>('last_sync_at').then((v) => {
      if (v) this.update({ lastSyncAt: v })
    })
  }

  subscribe = (fn: () => void) => {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }

  getStatus = () => this.status

  private update(patch: Partial<SyncStatus>) {
    this.status = { ...this.status, ...patch }
    for (const fn of this.listeners) fn()
  }

  private refreshCounts() {
    const pending = this.store.pending()
    const errors = pending.filter((p) => p.record._sync?.state === 'error').length
    if (pending.length !== this.status.pending || errors !== this.status.errors || this.store.conflicts.length !== this.status.conflicts) {
      this.update({ pending: pending.length, errors, conflicts: this.store.conflicts.length })
    }
  }

  isOnline(): boolean {
    return typeof navigator === 'undefined' ? true : navigator.onLine !== false
  }

  /** Runs one sync cycle; concurrent calls share the same run. */
  sync(): Promise<void> {
    if (!this.remote) return Promise.resolve()
    if (this.running) return this.running
    this.running = this.run().finally(() => {
      this.running = null
    })
    return this.running
  }

  private async run() {
    if (!this.isOnline()) {
      this.update({ state: 'offline' })
      return
    }
    this.update({ state: 'syncing', lastError: null })
    try {
      const pushError = await this.pushAll()
      await this.pullAll()
      await this.uploadAttachments()
      const at = nowISO()
      await this.store.setMeta('last_sync_at', at)
      this.refreshCounts()
      this.update({ state: pushError ? 'error' : 'idle', lastSyncAt: at, lastError: pushError })
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      this.update({ state: this.isOnline() ? 'error' : 'offline', lastError: msg })
    }
  }

  private async pushAll(): Promise<string | null> {
    const remote = this.remote!
    let firstError: string | null = null
    for (const item of this.store.pending()) {
      // Re-read: an earlier push in this loop may have changed it.
      const current = this.store.get(item.table, item.record.id)
      if (!current || current._sync?.state === 'synced') continue
      const result = await remote.push(item.table, toWire(current), current.version)
      if (result.status === 'ok') {
        await this.acceptServerRow(item.table, current, result.row)
      } else if (result.status === 'conflict') {
        await this.recordConflict(item.table, current, result.row)
      } else {
        if (!result.retryable) await this.store.markError(item.table, current.id, result.message)
        firstError ??= result.message
        if (result.retryable) throw new Error(result.message)
      }
    }
    return firstError
  }

  /** Apply the server's copy, unless the user edited the record again while the push was in flight. */
  private async acceptServerRow(table: TableName, sent: AnyRecord, row: AnyRecord) {
    const written = await this.store.putServerRows(table, [row], { overwritePending: true, expectChangedAt: sent._sync?.changed_at })
    if (written) return
    // A newer local edit exists: keep it pending, rebased on the new server version.
    const latest = this.store.get(table, sent.id)
    if (latest) await this.store.save([{ table, record: { ...latest, version: row.version } as AnyRecord }])
  }

  private async recordConflict(table: TableName, sent: AnyRecord, server: AnyRecord) {
    // Preserve the user's LATEST copy, including any edit saved while the push was in flight.
    const local = this.store.get(table, sent.id) ?? sent
    await this.store.addConflict({
      id: uuid(),
      table,
      record_id: local.id,
      local: toWire(local),
      server: server as unknown as Record<string, unknown>,
      detected_at: nowISO(),
    })
    // If yet another edit lands meanwhile it stays pending and is reported as its own conflict on the next push.
    await this.store.putServerRows(table, [server], { overwritePending: true, expectChangedAt: local._sync?.changed_at })
    await this.store.save([
      {
        table: 'audit_logs',
        record: auditRecord(
          this.store.businessId,
          table,
          local.id,
          'conflict',
          'Sync conflict: this record was changed on another device. Server copy kept; your copy saved for review.',
          local,
          server,
        ),
      },
    ])
  }

  private async pullAll() {
    const remote = this.remote!
    for (const table of TABLES) {
      const key = `cursor:${table}`
      let since = (await this.store.getMeta<number>(key)) ?? 0
      // Re-read a small window on the first page: a write that committed late
      // with a lower sequence number than one we already saw is not missed.
      let from = Math.max(0, since - PULL_OVERLAP)
      for (;;) {
        const { rows } = await remote.pull(table, this.store.businessId, from, PULL_LIMIT)
        if (!rows.length) break
        await this.store.putServerRows(table, rows)
        since = Math.max(since, ...rows.map((r) => Number(r.sync_seq)))
        await this.store.setMeta(key, since)
        if (rows.length < PULL_LIMIT) break
        from = since
      }
    }
  }

  private async uploadAttachments() {
    const remote = this.remote!
    for (const a of this.store.getSnapshot().attachments) {
      if (a.storage_path || a._sync?.state !== 'synced') continue
      const blob = await this.store.getBlob(a.id)
      if (!blob) continue
      const path = `${a.business_id}/${a.transaction_id}/${a.id}`
      await remote.uploadAttachment(path, blob.blob, blob.mime_type)
      await this.store.save([{ table: 'attachments', record: { ...a, storage_path: path } }])
    }
    if (this.store.pendingCount()) await this.pushAll()
  }

  /** Resolve a conflict by re-applying the local copy on top of the server version. */
  async keepMine(conflictId: string) {
    const c = this.store.conflicts.find((x) => x.id === conflictId)
    if (!c) return
    const server = this.store.get(c.table, c.record_id)
    const merged = { ...c.local, version: server?.version ?? (c.server as { version: number }).version } as unknown as AnyRecord
    await this.store.save([{ table: c.table, record: merged }])
    await this.store.removeConflict(conflictId)
    void this.sync()
  }

  async keepServer(conflictId: string) {
    await this.store.removeConflict(conflictId)
  }
}
