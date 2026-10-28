import type { SupabaseClient } from '@supabase/supabase-js'
import type { TableName } from '../types'
import type { AnyRecord } from '../store/store'
import type { PushResult, Remote } from './engine'

function isNetworkError(err: { code?: string; message?: string } | null): boolean {
  if (!err) return false
  if (!err.code) return true // fetch failure / offline / timeout
  return /^(PGRST0|5)/.test(err.code) // connection errors and 5xx
}

export function supabaseRemote(sb: SupabaseClient): Remote {
  return {
    async push(table: TableName, row: Record<string, unknown>, baseVersion: number): Promise<PushResult> {
      const { data, error } = await sb.rpc('sync_push', { p_table: table, p_row: row, p_base_version: baseVersion })
      if (error) return { status: 'error', message: error.message, retryable: isNetworkError(error) }
      const res = data as { status: 'ok' | 'conflict'; row: AnyRecord }
      return { status: res.status, row: res.row }
    },
    async pull(table, businessId, sinceSeq, limit) {
      const { data, error } = await sb
        .from(table)
        .select('*')
        .eq('business_id', businessId)
        .gt('sync_seq', sinceSeq)
        .order('sync_seq', { ascending: true })
        .limit(limit)
      if (error) throw new Error(error.message)
      return { rows: (data ?? []) as (AnyRecord & { sync_seq: number })[] }
    },
    async uploadAttachment(path, blob, contentType) {
      const { error } = await sb.storage.from('attachments').upload(path, blob, { contentType, upsert: false })
      if (error && !/exists|duplicate/i.test(error.message)) throw new Error(error.message)
    },
    async downloadAttachment(path) {
      const { data, error } = await sb.storage.from('attachments').download(path)
      if (error || !data) throw new Error(error?.message ?? 'Download failed')
      return data
    },
  }
}
