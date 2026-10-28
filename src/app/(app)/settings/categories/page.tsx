'use client'

import { useState } from 'react'
import { Eye, EyeOff, Pencil, Plus } from 'lucide-react'
import { useData, useStore } from '@/components/app-provider'
import { useFeedback } from '@/components/feedback'
import { PageHeader, Segmented } from '@/components/ui'
import { saveCategory } from '@/lib/store/repo'
import type { CategoryKind } from '@/lib/types'

export default function CategoriesPage() {
  const data = useData()
  const store = useStore()
  const { toast, confirm } = useFeedback()
  const [kind, setKind] = useState<CategoryKind>('income')
  const [name, setName] = useState('')
  const list = data.categories.filter((c) => c.kind === kind).sort((a, b) => Number(b.is_active) - Number(a.is_active) || a.sort_order - b.sort_order)
  const used = new Set(data.transactions.map((t) => t.category_id))
  return (
    <div>
      <PageHeader title="Categories" subtitle="Hidden categories stay on old entries but are not offered for new ones" back="/settings" />
      <Segmented value={kind} onChange={setKind} options={[{ value: 'income', label: 'Income / Services' }, { value: 'expense', label: 'Expenses' }]} />
      <form className="mt-3 flex gap-2" onSubmit={async (e) => {
        e.preventDefault()
        const r = await saveCategory(store, kind, name)
        if (!r.ok) return toast(Object.values(r.errors)[0], 'error')
        setName('')
        toast('Category added')
      }}>
        <input className="input" placeholder={`New ${kind} category`} value={name} onChange={(e) => setName(e.target.value)} aria-label="New category name" />
        <button className="btn-primary shrink-0" disabled={!name.trim()}><Plus className="size-4" /> Add</button>
      </form>
      <div className="card mt-3 divide-y divide-line overflow-hidden">
        {list.map((c) => (
          <div key={c.id} className={`flex items-center gap-2 px-4 py-2.5 ${c.is_active ? '' : 'opacity-55'}`}>
            <span className="min-w-0 flex-1 truncate text-[15px]">{c.name}</span>
            {used.has(c.id) && <span className="text-[11px] text-muted">in use</span>}
            <button className="btn-ghost min-h-10 px-2" aria-label={`Rename ${c.name}`} onClick={async () => {
              const r = await confirm({ title: 'Rename category', input: { label: 'New name', required: true }, confirmLabel: 'Rename' })
              if (!r.ok) return
              const res = await saveCategory(store, kind, r.value, c, c.is_active)
              if (!res.ok) toast(Object.values(res.errors)[0], 'error')
            }}><Pencil className="size-4" /></button>
            <button className="btn-ghost min-h-10 px-2" aria-label={c.is_active ? `Hide ${c.name}` : `Show ${c.name}`} onClick={() => saveCategory(store, kind, c.name, c, !c.is_active)}>
              {c.is_active ? <Eye className="size-4" /> : <EyeOff className="size-4" />}
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
