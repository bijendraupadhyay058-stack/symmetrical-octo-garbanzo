import { compareTxns } from './accounting/ledger'
import { nextVoucherNo, parseVoucher, type VoucherPrefix } from './accounting/vouchers'
import { nowISO, uuid } from './ids'
import { auditRecord } from './store/repo'
import type { AnyRecord, Change, LocalStore } from './store/store'
import { TABLES, type DataSnapshot, type TableName } from './types'

export const BACKUP_APP = 'fintaxpro-cashbook'
export const BACKUP_FORMAT = 1

export interface BackupFile {
  app: typeof BACKUP_APP
  format: number
  exported_at: string
  business_id: string
  business_name: string
  counts: Record<string, number>
  tables: Partial<Record<TableName, Record<string, unknown>[]>>
  blobs?: Record<string, { mime_type: string; base64: string }>
  checksum: string
}

async function sha256(text: string): Promise<string> {
  const data = new TextEncoder().encode(text)
  const hash = await crypto.subtle.digest('SHA-256', data)
  return [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, '0')).join('')
}

function rowsOf(snap: DataSnapshot, t: TableName): AnyRecord[] {
  if (t === 'business_profiles') return snap.profile ? [snap.profile] : []
  return snap[t] as AnyRecord[]
}

function clean(r: AnyRecord): Record<string, unknown> {
  const { _sync, ...rest } = r as AnyRecord & Record<string, unknown>
  void _sync
  delete rest.sync_seq
  return rest
}

async function blobToBase64(b: Blob): Promise<string> {
  const buf = new Uint8Array(await b.arrayBuffer())
  let s = ''
  for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode(...buf.subarray(i, i + 0x8000))
  return btoa(s)
}

function base64ToBlob(b64: string, type: string): Blob {
  const bin = atob(b64)
  const arr = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i)
  return new Blob([arr], { type })
}

export async function createBackup(store: LocalStore, opts: { includeFiles?: boolean } = {}): Promise<BackupFile> {
  const snap = store.getSnapshot()
  const tables: BackupFile['tables'] = {}
  const counts: Record<string, number> = {}
  for (const t of TABLES) {
    const rows = rowsOf(snap, t).map(clean)
    tables[t] = rows
    counts[t] = rows.length
  }
  let blobs: BackupFile['blobs']
  if (opts.includeFiles) {
    blobs = {}
    for (const a of snap.attachments) {
      const b = await store.getBlob(a.id)
      if (b) blobs[a.id] = { mime_type: b.mime_type, base64: await blobToBase64(b.blob) }
    }
  }
  const checksum = await sha256(JSON.stringify(tables))
  return {
    app: BACKUP_APP,
    format: BACKUP_FORMAT,
    exported_at: nowISO(),
    business_id: store.businessId,
    business_name: snap.profile?.name ?? '',
    counts,
    tables,
    blobs,
    checksum,
  }
}

export async function parseBackup(text: string): Promise<{ ok: true; backup: BackupFile } | { ok: false; error: string }> {
  let data: BackupFile
  try {
    data = JSON.parse(text)
  } catch {
    return { ok: false, error: 'The file is not a valid backup (unreadable JSON).' }
  }
  if (data?.app !== BACKUP_APP || typeof data.format !== 'number') return { ok: false, error: 'This is not a FIN TAX PRO CashBook backup file.' }
  if (data.format > BACKUP_FORMAT) return { ok: false, error: 'This backup was made by a newer version of the app. Please update the app first.' }
  if (!data.tables || typeof data.tables !== 'object') return { ok: false, error: 'Backup has no data.' }
  const sum = await sha256(JSON.stringify(data.tables))
  if (sum !== data.checksum) return { ok: false, error: 'Backup file is damaged or was modified (checksum mismatch). Restore refused.' }
  for (const t of Object.keys(data.tables)) {
    if (!TABLES.includes(t as TableName)) return { ok: false, error: `Unknown table "${t}" in backup.` }
    if (!Array.isArray(data.tables[t as TableName])) return { ok: false, error: `Invalid data for ${t}.` }
  }
  return { ok: true, backup: data }
}

export interface RestoreSummary {
  added: Record<string, number>
  skipped: Record<string, number>
  renumbered: number
}

const REF_FIELDS = ['account_id', 'to_account_id', 'category_id', 'client_id', 'fee_bill_id', 'transaction_id', 'recurring_template_id', 'entity_id']
const TYPE_ORDER = { income: 0, contra: 1, expense: 2 } as const

/**
 * Merge-restore: records already on this device are never overwritten or
 * deleted; only missing records are added (and then synced). Restoring a
 * backup of a different business re-keys every record and maps accounts and
 * categories by name, so nothing collides with existing data.
 */
export async function restoreBackup(store: LocalStore, backup: BackupFile): Promise<RestoreSummary> {
  const snap = store.getSnapshot()
  const sameBusiness = backup.business_id === store.businessId
  const idMap = new Map<string, string>()
  const summary: RestoreSummary = { added: {}, skipped: {}, renumbered: 0 }
  const existingIds = new Set<string>()
  for (const t of TABLES) for (const r of rowsOf(snap, t)) existingIds.add(r.id)

  if (!sameBusiness) {
    for (const a of backup.tables.accounts ?? []) {
      const match = snap.accounts.find((x) => x.kind === a.kind && x.name.toLowerCase() === String(a.name).toLowerCase())
      idMap.set(String(a.id), match?.id ?? uuid())
    }
    for (const c of backup.tables.categories ?? []) {
      const match = snap.categories.find((x) => x.kind === c.kind && x.name.toLowerCase() === String(c.name).toLowerCase())
      idMap.set(String(c.id), match?.id ?? uuid())
    }
    for (const t of TABLES) {
      for (const r of backup.tables[t] ?? []) if (!idMap.has(String(r.id))) idMap.set(String(r.id), uuid())
    }
  }
  const remap = (r: Record<string, unknown>): Record<string, unknown> => {
    if (sameBusiness) return r
    const out: Record<string, unknown> = { ...r, id: idMap.get(String(r.id)), business_id: store.businessId, version: 0 }
    for (const f of REF_FIELDS) if (typeof out[f] === 'string' && idMap.has(out[f] as string)) out[f] = idMap.get(out[f] as string)
    return out
  }

  const usedVouchers = new Set(snap.transactions.map((t) => t.voucher_no))
  const changes: Change[] = []
  for (const t of TABLES) {
    if (t === 'business_profiles' && (!sameBusiness || snap.profile)) {
      summary.skipped[t] = (backup.tables[t] ?? []).length
      continue
    }
    let rows = (backup.tables[t] ?? []).map(remap)
    if (t === 'transactions') {
      rows = (rows as unknown as DataSnapshot['transactions']).sort(
        (a, b) => (a.txn_date !== b.txn_date ? compareTxns(a, b) : TYPE_ORDER[a.type] - TYPE_ORDER[b.type] || compareTxns(a, b)),
      ) as unknown as Record<string, unknown>[]
    }
    for (const r of rows) {
      const id = String(r.id)
      if (existingIds.has(id)) {
        summary.skipped[t] = (summary.skipped[t] ?? 0) + 1
        continue
      }
      // Never let a restored voucher number duplicate one already in use.
      if (t === 'transactions') {
        const v = String(r.voucher_no)
        if (usedVouchers.has(v)) {
          const p = parseVoucher(v)
          r.voucher_no = nextVoucherNo(usedVouchers, (p?.prefix ?? 'CR') as VoucherPrefix, String(r.txn_date))
          summary.renumbered++
        }
        usedVouchers.add(String(r.voucher_no))
      }
      if (sameBusiness) r.version = 0
      changes.push({ table: t, record: r as unknown as AnyRecord })
      summary.added[t] = (summary.added[t] ?? 0) + 1
      existingIds.add(id)
    }
  }
  if (backup.blobs) {
    for (const [oldId, b] of Object.entries(backup.blobs)) {
      const newId = sameBusiness ? oldId : idMap.get(oldId)
      if (newId) await store.putBlob(newId, base64ToBlob(b.base64, b.mime_type), b.mime_type)
    }
  }
  // Attachments whose files were not in the backup keep their cloud path only when restoring the same business.
  for (const c of changes) {
    if (c.table === 'attachments' && !sameBusiness) (c.record as DataSnapshot['attachments'][number]).storage_path = null
  }
  const total = Object.values(summary.added).reduce((s, n) => s + n, 0)
  changes.push({
    table: 'audit_logs',
    record: auditRecord(store.businessId, 'business_profiles', store.businessId, 'import',
      `Restored backup of "${backup.business_name}" dated ${backup.exported_at.slice(0, 10)}: ${total} records added`, null, { counts: summary.added }),
  })
  // Save in chunks so very large backups do not hit IndexedDB transaction limits.
  for (let i = 0; i < changes.length; i += 400) await store.save(changes.slice(i, i + 400))
  return summary
}

/** Weekly automatic on-device snapshot (keeps the latest four). */
export async function autoSnapshot(store: LocalStore, now = new Date()): Promise<boolean> {
  const last = await store.getMeta<string>('last_auto_snapshot')
  if (last && now.getTime() - new Date(last).getTime() < 7 * 86400_000) return false
  if (!store.getSnapshot().transactions.length) return false
  const backup = await createBackup(store)
  const id = uuid()
  await store.db.put('snapshots', { id, created_at: now.toISOString(), label: 'Automatic weekly backup', data: JSON.stringify(backup) })
  const all = ((await store.db.getAll('snapshots')) as { id: string; created_at: string }[]).sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
  for (const old of all.slice(4)) await store.db.delete('snapshots', old.id)
  await store.setMeta('last_auto_snapshot', now.toISOString())
  return true
}
