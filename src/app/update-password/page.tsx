'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { getSupabase } from '@/lib/supabase/client'
import { Logo } from '@/components/splash'
import { Field } from '@/components/ui'

export default function UpdatePasswordPage() {
  const sb = getSupabase()
  const [ready, setReady] = useState(false)
  const [pw, setPw] = useState('')
  const [pw2, setPw2] = useState('')
  const [err, setErr] = useState('')
  const [done, setDone] = useState(false)
  useEffect(() => {
    if (!sb) return
    // The recovery link signs the user in (PKCE code exchange happens automatically).
    sb.auth.getSession().then(({ data }) => setReady(!!data.session))
    const { data } = sb.auth.onAuthStateChange((_e, session) => setReady(!!session))
    return () => data.subscription.unsubscribe()
  }, [sb])
  return (
    <div className="min-h-dvh bg-navy-900 px-5 pt-16">
      <div className="mx-auto max-w-md">
        <div className="mb-6 flex justify-center"><Logo size={56} /></div>
        <div className="card p-5">
          <h1 className="text-lg font-bold">Choose a new password</h1>
          {done ? (
            <p className="mt-2 text-sm text-muted">Password updated. <Link className="font-semibold text-balance" href="/login">Continue</Link></p>
          ) : !ready ? (
            <p className="mt-2 text-sm text-muted">Open the reset link from your email on this device. If it has expired, request a new one.</p>
          ) : (
            <form
              className="mt-4 space-y-4"
              onSubmit={async (e) => {
                e.preventDefault()
                if (pw.length < 8) return setErr('Use at least 8 characters')
                if (pw !== pw2) return setErr('Passwords do not match')
                const { error } = await sb!.auth.updateUser({ password: pw })
                if (error) setErr(error.message)
                else setDone(true)
              }}
            >
              <Field label="New password"><input className="input" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} /></Field>
              <Field label="Confirm new password" error={err}><input className="input" type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} /></Field>
              <button className="btn-primary w-full">Update password</button>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}
