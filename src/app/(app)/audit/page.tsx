'use client'

import { useMemo, useState } from 'react'
import { Search } from 'lucide-react'
import { useData } from '@/components/app-provider'
import { Badge, EmptyState, PageHeader, Select } from '@/components/ui'
import { formatDateTime } from '@/lib/dates'
import type { AuditLog } from '@/lib/types'

const tone: Record<string, 'income' | 'expense' | 'balance' | 'warn' | 'neutral'> = {
  create: 'income', update: 'balance', cancel: 'expense', restore: 'warn', opening_balance: 'warn', import: 'balance', conflict: 'expense',
}

export default function AuditPage() {
  const data = useData()
  const [q, setQ] = useState('')
  const [action, setAction] = useState('')
  const [source, setSource] = useState<'app' | 'db' | ''>('app')
  const [limit, setLimit] = useState(150)
  const [open, setOpen] = useState<AuditLog | null>(null)
  const list = useMemo(
    () => data.audit_logs
      .filter((a) => (!action || a.action === action) && (!source || a.source === source) && (!q || a.summary.toLowerCase().includes(q.toLowerCase())))
      .sort((a, b) => (a.created_at < b.created_at ? 1 : -1)),
    [data.audit_logs, q, action, source],
  )
  return (
    <div>
      <PageHeader title="Audit History" subtitle="Accounting records are never deleted – every change is listed here" />
      <div className="mb-3 space-y-2">
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted" />
          <input className="input pl-10" placeholder="Search voucher, client…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search audit log" />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <Select value={action} onChange={(e) => setAction(e.target.value)} aria-label="Action">
            <option value="">All actions</option>
            {Object.keys(tone).map((k) => <option key={k} value={k}>{k.replace('_', ' ')}</option>)}
          </Select>
          <Select value={source} onChange={(e) => setSource(e.target.value as typeof source)} aria-label="Source">
            <option value="app">App entries</option><option value="db">Server records</option><option value="">All</option>
          </Select>
        </div>
      </div>
      {list.length ? (
        <div className="card divide-y divide-line overflow-hidden">
          {list.slice(0, limit).map((a) => (
            <button key={a.id} className="block w-full px-4 py-3 text-left hover:bg-elev" onClick={() => setOpen(open?.id === a.id ? null : a)}>
              <div className="flex items-center gap-2">
                <Badge tone={tone[a.action] ?? 'neutral'}>{a.action.replace('_', ' ')}</Badge>
                <span className="text-xs text-muted">{formatDateTime(a.created_at)}</span>
              </div>
              <div className="mt-1 text-sm">{a.summary}</div>
              {open?.id === a.id && (
                <pre className="mt-2 max-h-72 overflow-auto rounded-lg bg-elev p-2 text-[11px] whitespace-pre-wrap">
                  {JSON.stringify({ before: a.before_data, after: a.after_data }, null, 1)}
                </pre>
              )}
            </button>
          ))}
          {list.length > limit && <button className="btn-ghost w-full" onClick={() => setLimit((l) => l + 300)}>Show more</button>}
        </div>
      ) : (
        <EmptyState title="No audit entries" />
      )}
    </div>
  )
}
