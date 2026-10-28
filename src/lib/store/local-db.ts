import { openDB, type IDBPDatabase } from 'idb'
import { TABLES, type TableName } from '../types'

export const EXTRA_STORES = ['blobs', 'conflicts', 'meta', 'snapshots'] as const
export type ExtraStore = (typeof EXTRA_STORES)[number]
export type StoreName = TableName | ExtraStore

export interface ConflictRecord {
  id: string
  table: TableName
  record_id: string
  local: Record<string, unknown>
  server: Record<string, unknown>
  detected_at: string
}

export interface BlobRecord {
  id: string
  blob: Blob
  mime_type: string
}

export interface SnapshotRecord {
  id: string
  created_at: string
  label: string
  data: string
}

const DB_VERSION = 1

export type LocalDb = IDBPDatabase<unknown>

export async function openLocalDb(name: string): Promise<LocalDb> {
  return openDB(name, DB_VERSION, {
    upgrade(db) {
      for (const t of TABLES) {
        if (!db.objectStoreNames.contains(t)) db.createObjectStore(t, { keyPath: 'id' })
      }
      if (!db.objectStoreNames.contains('blobs')) db.createObjectStore('blobs', { keyPath: 'id' })
      if (!db.objectStoreNames.contains('conflicts')) db.createObjectStore('conflicts', { keyPath: 'id' })
      if (!db.objectStoreNames.contains('meta')) db.createObjectStore('meta')
      if (!db.objectStoreNames.contains('snapshots')) db.createObjectStore('snapshots', { keyPath: 'id' })
    },
    blocked() {
      // Another tab holds an older version open; it will be asked to close.
    },
  })
}

export async function deleteLocalDb(name: string): Promise<void> {
  const { deleteDB } = await import('idb')
  await deleteDB(name)
}

/** Ask the browser not to evict our data under storage pressure. */
export async function requestPersistentStorage(): Promise<boolean> {
  try {
    if (typeof navigator !== 'undefined' && navigator.storage?.persist) {
      if (await navigator.storage.persisted()) return true
      return await navigator.storage.persist()
    }
  } catch {
    /* not supported */
  }
  return false
}
