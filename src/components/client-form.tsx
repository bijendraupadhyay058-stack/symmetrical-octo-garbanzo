'use client'

import { useState } from 'react'
import { useStore } from './app-provider'
import { useFeedback } from './feedback'
import { Field, Sheet, Textarea } from './ui'
import { newClient, saveClient } from '@/lib/store/repo'
import type { Client } from '@/lib/types'

export function ClientSheet({ open, onClose, initial, onSaved, defaultName = '' }: { open: boolean; onClose: () => void; initial?: Client | null; onSaved?: (c: Client) => void; defaultName?: string }) {
  const store = useStore()
  const { toast } = useFeedback()
  const [c, setC] = useState<Client>(() => initial ?? newClient(store, defaultName))
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const set = <K extends keyof Client>(k: K, v: Client[K]) => setC((x) => ({ ...x, [k]: v }))
  const save = async () => {
    setBusy(true)
    const r = await saveClient(store, c)
    setBusy(false)
    if (!r.ok) return setErrors(r.errors)
    toast(`Client ${r.value.name} saved`)
    onSaved?.(r.value)
    onClose()
  }
  return (
    <Sheet open={open} onClose={onClose} title={initial ? `Edit ${initial.name}` : 'New client'} footer={<button className="btn-primary w-full" disabled={busy} onClick={save}>Save client</button>}>
      <div className="space-y-3.5">
        <div className="text-xs text-muted">Client ID: <b>{c.code}</b></div>
        <Field label="Client name *" error={errors.name}><input className="input" value={c.name} onChange={(e) => set('name', e.target.value)} autoFocus /></Field>
        <Field label="Business / Firm name"><input className="input" value={c.firm_name} onChange={(e) => set('firm_name', e.target.value)} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Mobile" error={errors.mobile}><input className="input" inputMode="tel" value={c.mobile} onChange={(e) => set('mobile', e.target.value)} /></Field>
          <Field label="Email" error={errors.email}><input className="input" type="email" value={c.email} onChange={(e) => set('email', e.target.value)} /></Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="GSTIN" error={errors.gstin}><input className="input uppercase" value={c.gstin} maxLength={15} onChange={(e) => set('gstin', e.target.value.toUpperCase())} /></Field>
          <Field label="PAN" error={errors.pan} hint="Masked in lists"><input className="input uppercase" value={c.pan} maxLength={10} autoComplete="off" onChange={(e) => set('pan', e.target.value.toUpperCase())} /></Field>
        </div>
        <Field label="Service type"><input className="input" value={c.service_type} placeholder="e.g. GST Returns, ITR, Audit" onChange={(e) => set('service_type', e.target.value)} /></Field>
        <Field label="Notes"><Textarea value={c.notes} onChange={(e) => set('notes', e.target.value)} /></Field>
        {initial && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="size-5" checked={c.is_active} onChange={(e) => set('is_active', e.target.checked)} /> Active client
          </label>
        )}
      </div>
    </Sheet>
  )
}

export function maskPan(pan: string): string {
  if (!pan) return ''
  return pan.slice(0, 2) + '•••••' + pan.slice(-3)
}
