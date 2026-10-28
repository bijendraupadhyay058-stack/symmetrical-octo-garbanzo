'use client'

import { useEffect, useState } from 'react'
import { Fingerprint, KeyRound, Lock, ShieldCheck } from 'lucide-react'
import { useApp, useData, useStore } from '@/components/app-provider'
import { useFeedback } from '@/components/feedback'
import { Field, PageHeader, Select } from '@/components/ui'
import { saveProfile } from '@/lib/store/repo'
import { biometricAvailable, biometricEnabled, disableBiometric, enableBiometric, rememberPassword, verifyLocalPassword } from '@/lib/security/local-auth'
import { getSupabase } from '@/lib/supabase/client'
import { formatDate } from '@/lib/dates'

export default function SecurityPage() {
  const data = useData()
  const store = useStore()
  const { mode, lockScope, user } = useApp()
  const { toast, confirm } = useFeedback()
  const s = data.profile!.settings
  const [bioOk, setBioOk] = useState(false)
  const [bioOn, setBioOn] = useState(false)
  const [pw, setPw] = useState({ current: '', next: '', confirm: '' })
  const [lockDate, setLockDate] = useState(s.books_locked_until ?? '')
  useEffect(() => {
    void biometricAvailable().then(setBioOk)
    setBioOn(biometricEnabled(lockScope))
  }, [lockScope])
  const update = (patch: Partial<typeof s>) => saveProfile(store, { ...data.profile!, settings: { ...s, ...patch } })

  return (
    <div className="space-y-4">
      <PageHeader title="Security" back="/settings" />
      <section className="card space-y-3 p-4">
        <h2 className="flex items-center gap-2 font-bold"><Lock className="size-4" /> Automatic lock (session timeout)</h2>
        <Select value={s.auto_lock_minutes} onChange={async (e) => { await update({ auto_lock_minutes: Number(e.target.value) }); toast('Auto-lock updated') }}>
          {[1, 5, 10, 15, 30, 60].map((m) => <option key={m} value={m}>Lock after {m} minute{m > 1 ? 's' : ''} of inactivity</option>)}
          <option value={0}>Never (not recommended)</option>
        </Select>
        <p className="text-xs text-muted">When locked, enter your password or use fingerprint to continue. Your sign-in session is refreshed securely by the server.</p>
      </section>

      <section className="card space-y-3 p-4">
        <h2 className="flex items-center gap-2 font-bold"><Fingerprint className="size-4" /> Fingerprint / screen-lock unlock</h2>
        {!bioOk ? (
          <p className="text-sm text-muted">This browser or device does not support biometric unlock. Use Chrome on an Android phone with a screen lock set up.</p>
        ) : bioOn ? (
          <button className="btn-outline w-full" onClick={() => { disableBiometric(lockScope); setBioOn(false); toast('Biometric unlock turned off') }}>Turn off biometric unlock</button>
        ) : (
          <button className="btn-primary w-full" onClick={async () => {
            try {
              await enableBiometric(lockScope, user?.email ?? data.profile!.name)
              setBioOn(true)
              toast('Biometric unlock enabled on this device')
            } catch (e) {
              toast(e instanceof Error ? e.message : 'Could not enable biometric unlock', 'error')
            }
          }}>Enable fingerprint unlock on this device</button>
        )}
      </section>

      <section className="card space-y-3 p-4">
        <h2 className="flex items-center gap-2 font-bold"><KeyRound className="size-4" /> Change password</h2>
        <form className="space-y-3" onSubmit={async (e) => {
          e.preventDefault()
          if (pw.next.length < 8) return toast('Use at least 8 characters', 'error')
          if (pw.next !== pw.confirm) return toast('New passwords do not match', 'error')
          if (mode === 'cloud') {
            const sb = getSupabase()!
            const check = await sb.auth.signInWithPassword({ email: user!.email, password: pw.current })
            if (check.error) return toast('Current password is incorrect', 'error')
            const { error } = await sb.auth.updateUser({ password: pw.next })
            if (error) return toast(error.message, 'error')
          } else if (!(await verifyLocalPassword(lockScope, pw.current))) {
            return toast('Current password is incorrect', 'error')
          }
          await rememberPassword(lockScope, pw.next)
          setPw({ current: '', next: '', confirm: '' })
          toast('Password changed')
        }}>
          <Field label="Current password"><input className="input" type="password" autoComplete="current-password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} /></Field>
          <Field label="New password"><input className="input" type="password" autoComplete="new-password" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} /></Field>
          <Field label="Confirm new password"><input className="input" type="password" autoComplete="new-password" value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} /></Field>
          <button className="btn-outline w-full" disabled={!pw.current || !pw.next}>Change password</button>
        </form>
      </section>

      <section className="card space-y-3 p-4">
        <h2 className="flex items-center gap-2 font-bold"><ShieldCheck className="size-4" /> Lock books (year-end closing)</h2>
        <p className="text-sm text-muted">Entries dated on or before this date cannot be added, edited or cancelled – on this device and on the server. Use after finalising accounts or filing returns.</p>
        <Field label="Books locked up to">
          <input className="input" type="date" value={lockDate} onChange={(e) => setLockDate(e.target.value)} />
        </Field>
        <button className="btn-primary w-full" onClick={async () => {
          const r = await confirm({
            title: lockDate ? `Lock books up to ${formatDate(lockDate)}?` : 'Unlock all periods?',
            message: lockDate ? 'Closing balances carry forward automatically. You can unlock later if a correction is required (it is audited).' : 'All past entries will become editable again.',
            confirmLabel: lockDate ? 'Lock books' : 'Unlock',
          })
          if (!r.ok) return
          await update({ books_locked_until: lockDate || null })
          toast(lockDate ? 'Books locked' : 'Books unlocked')
        }}>{lockDate ? 'Save lock date' : 'Remove lock'}</button>
      </section>

      <p className="text-xs text-muted">
        {mode === 'cloud'
          ? 'Data is transmitted over HTTPS and protected in the database by Row Level Security: only your account can read or change your business records.'
          : 'Data is stored in this browser’s private storage on this device.'}
      </p>
    </div>
  )
}
