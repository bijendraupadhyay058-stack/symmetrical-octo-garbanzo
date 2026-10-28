'use client'

import { AlertTriangle, CheckCircle2, CloudOff, RefreshCw } from 'lucide-react'
import { useApp, useData, useStore, useSyncStatus } from '@/components/app-provider'
import { useFeedback } from '@/components/feedback'
import { Badge, PageHeader } from '@/components/ui'
import { formatDateTime } from '@/lib/dates'
import { formatINR } from '@/lib/money'

export default function SyncPage() {
  const { mode, engine } = useApp()
  const store = useStore()
  useData()
  const st = useSyncStatus()
  const { confirm, toast } = useFeedback()
  const pending = store.pending()
  const describe = (r: Record<string, unknown>) =>
    [r.voucher_no, r.bill_no, r.name, r.summary, typeof r.amount_paise === 'number' ? formatINR(r.amount_paise) : null, r.narration].filter(Boolean).join(' · ')

  if (mode !== 'cloud') {
    return (
      <div>
        <PageHeader title="Sync Status" />
        <p className="card p-5 text-sm text-muted">{mode === 'demo' ? 'The demo workspace is never synced.' : 'This installation stores data on this device only. Use Backup & Restore to keep copies.'}</p>
      </div>
    )
  }
  return (
    <div className="space-y-4">
      <PageHeader title="Sync Status" subtitle={st.lastSyncAt ? `Last synced ${formatDateTime(st.lastSyncAt)}` : 'Not synced yet'} />
      <div className="card flex items-center gap-3 p-4">
        {st.state === 'offline' ? <CloudOff className="size-6 text-muted" /> : st.errors || st.conflicts ? <AlertTriangle className="size-6 text-expense" /> : st.pending ? <RefreshCw className="size-6 text-balance" /> : <CheckCircle2 className="size-6 text-income" />}
        <div className="flex-1 text-sm">
          <div className="font-semibold">
            {st.state === 'offline' ? 'You are offline – entries are saved on this device' : st.state === 'syncing' ? 'Syncing…' : st.pending ? `${st.pending} change(s) waiting to upload` : 'Everything is uploaded'}
          </div>
          {st.lastError && <div className="text-expense">{st.lastError}</div>}
        </div>
        <button className="btn-outline px-3" disabled={st.state === 'syncing'} onClick={() => engine?.sync()}><RefreshCw className={`size-4 ${st.state === 'syncing' ? 'animate-spin' : ''}`} /> Sync</button>
      </div>

      {store.conflicts.length > 0 && (
        <section className="space-y-2">
          <h2 className="font-bold">Changed on another device ({store.conflicts.length})</h2>
          <p className="text-sm text-muted">The same record was edited on two devices. The other device&apos;s version is currently in your books; your version was kept here. Choose which to keep.</p>
          {store.conflicts.map((c) => (
            <div key={c.id} className="card space-y-2 p-4 text-sm">
              <div className="text-xs text-muted">{c.table.replace('_', ' ')} · detected {formatDateTime(c.detected_at)}</div>
              <div><Badge tone="balance">In books (other device)</Badge> <div className="mt-1">{describe(c.server)}</div></div>
              <div><Badge tone="warn">Your version</Badge> <div className="mt-1">{describe(c.local)}</div></div>
              <div className="grid grid-cols-2 gap-2 pt-1">
                <button className="btn-outline text-sm" onClick={async () => {
                  const r = await confirm({ title: 'Keep the other device’s version?', message: 'Your version stays in the audit history.', confirmLabel: 'Keep it' })
                  if (r.ok) { await engine?.keepServer(c.id); toast('Resolved') }
                }}>Keep other</button>
                <button className="btn-primary text-sm" onClick={async () => { await engine?.keepMine(c.id); toast('Your version will be uploaded') }}>Use mine</button>
              </div>
            </div>
          ))}
        </section>
      )}

      {pending.length > 0 && (
        <section>
          <h2 className="mb-2 font-bold">Waiting to upload ({pending.length})</h2>
          <div className="card divide-y divide-line overflow-hidden">
            {pending.slice(0, 100).map(({ table, record }) => (
              <div key={table + record.id} className="px-4 py-2.5 text-sm">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{table.replace('_', ' ')}</span>
                  {record._sync?.state === 'error' ? <Badge tone="expense">Rejected</Badge> : <Badge tone="warn">Pending</Badge>}
                </div>
                <div className="truncate text-xs text-muted">{describe(record as unknown as Record<string, unknown>)}</div>
                {record._sync?.error && <div className="text-xs text-expense">{record._sync.error} – edit the entry to correct it; it will be retried automatically.</div>}
              </div>
            ))}
          </div>
        </section>
      )}
      <p className="text-xs text-muted">Entries are never lost: anything not yet uploaded stays on this device, including after closing the app or signing out.</p>
    </div>
  )
}
