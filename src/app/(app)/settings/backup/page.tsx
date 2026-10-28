'use client'

import { useEffect, useState } from 'react'
import { DatabaseBackup, Download, FileSpreadsheet, Upload } from 'lucide-react'
import { useApp, useData, useStore } from '@/components/app-provider'
import { useFeedback } from '@/components/feedback'
import { PageHeader } from '@/components/ui'
import { createBackup, parseBackup, restoreBackup } from '@/lib/backup'
import { downloadBlob } from '@/lib/share'
import { formatDateTime, todayIST } from '@/lib/dates'
import { safeFileName } from '@/lib/export/format'
import type { SnapshotRecord } from '@/lib/store/local-db'

export default function BackupPage() {
  const store = useStore()
  const data = useData()
  const { mode } = useApp()
  const { toast, confirm } = useFeedback()
  const [busy, setBusy] = useState(false)
  const [withFiles, setWithFiles] = useState(true)
  const [snaps, setSnaps] = useState<SnapshotRecord[]>([])
  const [lastBackup, setLastBackup] = useState<string | null>(null)

  useEffect(() => {
    void store.db.getAll('snapshots').then((s) => setSnaps((s as SnapshotRecord[]).sort((a, b) => (a.created_at < b.created_at ? 1 : -1))))
    void store.getMeta<string>('last_manual_backup').then((v) => setLastBackup(v ?? null))
  }, [store])

  const download = async () => {
    setBusy(true)
    try {
      const b = await createBackup(store, { includeFiles: withFiles })
      const name = safeFileName(`FinTaxPro_CashBook_Backup_${data.profile?.name ?? ''}_${todayIST()}`) + '.json'
      downloadBlob(new Blob([JSON.stringify(b)], { type: 'application/json' }), name)
      await store.setMeta('last_manual_backup', b.exported_at)
      setLastBackup(b.exported_at)
      toast('Backup downloaded. Keep it somewhere safe (e.g. Google Drive).')
    } finally {
      setBusy(false)
    }
  }

  const restore = async (text: string) => {
    const parsed = await parseBackup(text)
    if (!parsed.ok) return toast(parsed.error, 'error')
    const b = parsed.backup
    const counts = Object.entries(b.counts).filter(([, n]) => n).map(([t, n]) => `${n} ${t.replace(/_/g, ' ')}`).join(', ')
    const r = await confirm({
      title: 'Restore this backup?',
      message: <>Backup of <b>{b.business_name}</b> taken {formatDateTime(b.exported_at)} ({counts}).<br /><br />Records already on this device are <b>kept unchanged</b>; only missing records are added{mode === 'cloud' ? ' and then uploaded' : ''}. Nothing is deleted.</>,
      confirmLabel: 'Restore',
    })
    if (!r.ok) return
    setBusy(true)
    try {
      const res = await restoreBackup(store, b)
      const added = Object.values(res.added).reduce((s, n) => s + n, 0)
      toast(`Restore complete: ${added} records added${res.renumbered ? `, ${res.renumbered} voucher(s) renumbered` : ''}.`)
    } catch (e) {
      toast('Restore failed: ' + (e instanceof Error ? e.message : e), 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Backup & Restore" subtitle={mode === 'cloud' ? 'Your data is also synced to the secure cloud database' : 'Data is stored on this device – back up regularly'} back="/settings" />
      <section className="card space-y-3 p-4">
        <h2 className="flex items-center gap-2 font-bold"><Download className="size-4" /> Manual backup</h2>
        <p className="text-sm text-muted">Downloads a complete, checksum-protected copy of all entries, clients, bills, settings and audit history.</p>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="size-5" checked={withFiles} onChange={(e) => setWithFiles(e.target.checked)} /> Include bill photos & attachments stored on this device</label>
        <button className="btn-primary w-full" disabled={busy} onClick={download}>Download backup file</button>
        <p className="text-xs text-muted">Last manual backup: {lastBackup ? formatDateTime(lastBackup) : 'never'}</p>
      </section>
      <section className="card space-y-3 p-4">
        <h2 className="flex items-center gap-2 font-bold"><Upload className="size-4" /> Restore backup</h2>
        <p className="text-sm text-muted">Safe merge: never overwrites or deletes existing records. Damaged or edited backup files are rejected.</p>
        <label className={`btn-outline w-full cursor-pointer ${busy ? 'pointer-events-none opacity-50' : ''}`}>
          Choose backup file (.json)
          <input type="file" accept="application/json,.json" className="hidden" onChange={async (e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) await restore(await f.text()) }} />
        </label>
      </section>
      <section className="card space-y-3 p-4">
        <h2 className="flex items-center gap-2 font-bold"><DatabaseBackup className="size-4" /> Automatic weekly backups (this device)</h2>
        {snaps.length ? (
          <ul className="divide-y divide-line text-sm">
            {snaps.map((s) => (
              <li key={s.id} className="flex items-center gap-2 py-2">
                <span className="flex-1">{formatDateTime(s.created_at)}</span>
                <button className="btn-ghost min-h-9 px-2 text-sm" onClick={() => downloadBlob(new Blob([s.data], { type: 'application/json' }), `CashBook_auto_${s.created_at.slice(0, 10)}.json`)}>Download</button>
                <button className="btn-ghost min-h-9 px-2 text-sm" onClick={() => restore(s.data)}>Restore</button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">The app keeps the last 4 weekly snapshots on this device automatically once you have entries.</p>
        )}
      </section>
      <section className="card space-y-2 p-4">
        <h2 className="flex items-center gap-2 font-bold"><FileSpreadsheet className="size-4" /> Export</h2>
        <p className="text-sm text-muted">Export all transactions to Excel from the Transactions screen (download icon), or any report from Reports.</p>
      </section>
    </div>
  )
}
