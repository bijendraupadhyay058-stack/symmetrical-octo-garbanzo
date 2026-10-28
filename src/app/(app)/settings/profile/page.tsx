'use client'

import { useState } from 'react'
import { ImagePlus, Trash2 } from 'lucide-react'
import { useData, useStore } from '@/components/app-provider'
import { useFeedback } from '@/components/feedback'
import { Field, PageHeader, Textarea } from '@/components/ui'
import { saveProfile } from '@/lib/store/repo'
import { blobToDataUrl, compressImage } from '@/lib/share'
import type { BusinessProfile } from '@/lib/types'

export default function ProfilePage() {
  const data = useData()
  const store = useStore()
  const { toast } = useFeedback()
  const [p, setP] = useState<BusinessProfile>(data.profile!)
  const [busy, setBusy] = useState(false)
  const set = <K extends keyof BusinessProfile>(k: K, v: BusinessProfile[K]) => setP((x) => ({ ...x, [k]: v }))
  const setS = <K extends keyof BusinessProfile['settings']>(k: K, v: BusinessProfile['settings'][K]) => setP((x) => ({ ...x, settings: { ...x.settings, [k]: v } }))
  return (
    <div>
      <PageHeader title="Business Profile" subtitle="Shown on receipts, reports and statements" back="/settings" />
      <form className="space-y-4" onSubmit={async (e) => {
        e.preventDefault()
        if (!p.name.trim()) return toast('Business name is required', 'error')
        setBusy(true)
        await saveProfile(store, { ...p, name: p.name.trim() })
        setBusy(false)
        toast('Business profile saved')
      }}>
        <div className="card flex items-center gap-4 p-4">
          {p.logo_data_url ? <img src={p.logo_data_url} alt="Business logo" className="size-20 rounded-2xl border border-line bg-white object-contain" /> : <div className="flex size-20 items-center justify-center rounded-2xl bg-elev text-xs text-muted">No logo</div>}
          <div className="flex flex-col gap-2">
            <label className="btn-outline cursor-pointer text-sm"><ImagePlus className="size-4" /> Upload logo
              <input type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={async (e) => {
                const f = e.target.files?.[0]
                if (!f) return
                const small = await compressImage(f, 256, 0.9, 'image/png')
                set('logo_data_url', await blobToDataUrl(small))
              }} />
            </label>
            {p.logo_data_url && <button type="button" className="btn-ghost text-sm text-expense" onClick={() => set('logo_data_url', null)}><Trash2 className="size-4" /> Remove</button>}
          </div>
        </div>
        <div className="card space-y-3.5 p-4">
          <Field label="Business name *"><input className="input" value={p.name} onChange={(e) => set('name', e.target.value)} /></Field>
          <Field label="Tagline / services"><input className="input" value={p.tagline} onChange={(e) => set('tagline', e.target.value)} /></Field>
          <Field label="Address"><Textarea value={p.address} onChange={(e) => set('address', e.target.value)} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Phone"><input className="input" inputMode="tel" value={p.phone} onChange={(e) => set('phone', e.target.value)} /></Field>
            <Field label="Email"><input className="input" type="email" value={p.email} onChange={(e) => set('email', e.target.value)} /></Field>
            <Field label="GSTIN"><input className="input uppercase" value={p.gstin} maxLength={15} onChange={(e) => set('gstin', e.target.value.toUpperCase())} /></Field>
            <Field label="PAN"><input className="input uppercase" value={p.pan} maxLength={10} onChange={(e) => set('pan', e.target.value.toUpperCase())} /></Field>
          </div>
        </div>
        <div className="card space-y-3.5 p-4">
          <Field label="Receipt footer"><input className="input" value={p.settings.receipt_footer} onChange={(e) => setS('receipt_footer', e.target.value)} /></Field>
          <Field label="Payment reminder message" hint="Placeholders: {client} {amount} {bill} {date} {business}">
            <Textarea rows={4} value={p.settings.reminder_message} onChange={(e) => setS('reminder_message', e.target.value)} />
          </Field>
        </div>
        <button className="btn-primary w-full" disabled={busy}>Save profile</button>
      </form>
    </div>
  )
}
