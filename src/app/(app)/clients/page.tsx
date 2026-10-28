'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import { Plus, Search, Users } from 'lucide-react'
import { useData } from '@/components/app-provider'
import { EmptyState, PageHeader } from '@/components/ui'
import { ClientSheet } from '@/components/client-form'
import { clientPositions } from '@/lib/accounting/fees'
import { formatINR } from '@/lib/money'

export default function ClientsPage() {
  const data = useData()
  const [q, setQ] = useState('')
  const [adding, setAdding] = useState(false)
  const [showInactive, setShowInactive] = useState(false)
  const pos = useMemo(() => clientPositions(data), [data])
  const list = data.clients
    .filter((c) => (showInactive || c.is_active) && (!q || `${c.name} ${c.firm_name} ${c.mobile} ${c.code} ${c.gstin} ${c.service_type}`.toLowerCase().includes(q.toLowerCase())))
    .sort((a, b) => a.name.localeCompare(b.name))
  const totalOs = [...pos.values()].reduce((s, p) => s + p.outstanding, 0)
  return (
    <div>
      <PageHeader title="Client Master" subtitle={`${data.clients.filter((c) => c.is_active).length} active clients · Outstanding ${formatINR(totalOs)}`}
        actions={<button className="btn-primary px-3" onClick={() => setAdding(true)}><Plus className="size-4" /> Client</button>} />
      <div className="relative mb-3">
        <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted" />
        <input className="input pl-10" placeholder="Search name, firm, mobile, GSTIN…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search clients" />
      </div>
      <label className="mb-3 flex items-center gap-2 text-sm text-muted"><input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} /> Show inactive clients</label>
      {list.length ? (
        <div className="card divide-y divide-line overflow-hidden">
          {list.map((c) => {
            const p = pos.get(c.id)
            return (
              <Link key={c.id} href={`/clients/view?id=${c.id}`} className="flex items-center gap-3 px-4 py-3 hover:bg-elev">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-balance-soft font-bold text-balance">{c.name.slice(0, 1).toUpperCase()}</span>
                <div className="min-w-0 flex-1">
                  <div className="truncate font-semibold">{c.name} {!c.is_active && <span className="text-xs text-muted">(inactive)</span>}</div>
                  <div className="truncate text-xs text-muted">{[c.code, c.firm_name, c.mobile].filter(Boolean).join(' · ')}</div>
                </div>
                <div className="text-right text-xs">
                  {p && p.outstanding > 0 ? <div className="num font-bold text-expense">{formatINR(p.outstanding)}</div> : <div className="text-muted">No dues</div>}
                  {p && p.totalReceived > 0 && <div className="num text-muted">Recd {formatINR(p.totalReceived)}</div>}
                </div>
              </Link>
            )
          })}
        </div>
      ) : (
        <EmptyState icon={<Users className="size-8" />} title={q ? 'No matching clients' : 'No clients yet'} text="Add clients to track fees received and outstanding." action={<button className="btn-primary" onClick={() => setAdding(true)}><Plus className="size-4" /> Add client</button>} />
      )}
      {adding && <ClientSheet open onClose={() => setAdding(false)} defaultName={q} />}
    </div>
  )
}
