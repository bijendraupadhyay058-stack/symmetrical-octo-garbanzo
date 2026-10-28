'use client'

import { useEffect, useState } from 'react'
import { Fingerprint, Lock } from 'lucide-react'
import { useApp } from './app-provider'
import { Logo } from './splash'
import { biometricEnabled } from '@/lib/security/local-auth'

export function LockScreen() {
  const { unlockWithPassword, unlockWithBiometric, lockScope, user, mode, signOut } = useApp()
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const bio = biometricEnabled(lockScope)

  useEffect(() => {
    if (bio) void unlockWithBiometric()
  }, [bio, unlockWithBiometric])

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center bg-navy-900 px-6 text-white">
      <Logo size={64} />
      <h1 className="mt-4 flex items-center gap-2 text-xl font-bold"><Lock className="size-5" /> CashBook is locked</h1>
      <p className="mt-1 text-sm text-white/70">{mode === 'cloud' ? user?.email : 'Enter your app password to continue'}</p>
      <form
        className="mt-6 w-full max-w-xs space-y-3"
        onSubmit={async (e) => {
          e.preventDefault()
          setBusy(true)
          setErr('')
          const ok = await unlockWithPassword(password)
          setBusy(false)
          if (!ok) setErr('Incorrect password')
        }}
      >
        <input
          type="password"
          autoComplete="current-password"
          className="input bg-white text-[#0f172a]"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          aria-label="Password"
        />
        {err && <p role="alert" className="text-sm font-semibold text-[#fca5a5]">{err}</p>}
        <button className="btn w-full bg-white text-navy-900" disabled={busy || !password}>Unlock</button>
        {bio && (
          <button type="button" className="btn w-full border border-white/30 text-white" onClick={() => unlockWithBiometric()}>
            <Fingerprint className="size-5" /> Use fingerprint / screen lock
          </button>
        )}
      </form>
      <button className="mt-8 text-sm text-white/60 underline" onClick={() => signOut()}>
        Sign out instead
      </button>
    </div>
  )
}
