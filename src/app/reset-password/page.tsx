'use client'

import { useState } from 'react'
import Link from 'next/link'
import { getSupabase } from '@/lib/supabase/client'
import { Logo } from '@/components/splash'
import { Field } from '@/components/ui'

export default function ResetPasswordPage() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const sb = getSupabase()
  return (
    <div className="min-h-dvh bg-navy-900 px-5 pt-16">
      <div className="mx-auto max-w-md">
        <div className="mb-6 flex justify-center"><Logo size={56} /></div>
        <div className="card p-5">
          <h1 className="text-lg font-bold">Reset password</h1>
          {!sb ? (
            <p className="mt-2 text-sm text-muted">Password reset needs cloud sign-in, which is not configured on this installation.</p>
          ) : sent ? (
            <p className="mt-2 text-sm text-muted">If an account exists for <b>{email}</b>, a reset link has been sent. Open it on this device to choose a new password.</p>
          ) : (
            <form
              className="mt-4 space-y-4"
              onSubmit={async (e) => {
                e.preventDefault()
                setBusy(true)
                setErr('')
                const { error } = await sb.auth.resetPasswordForEmail(email.trim(), { redirectTo: `${process.env.NEXT_PUBLIC_SITE_URL || location.origin}/update-password` })
                setBusy(false)
                if (error) setErr(error.message)
                else setSent(true)
              }}
            >
              <Field label="Email" error={err}>
                <input className="input" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
              </Field>
              <button className="btn-primary w-full" disabled={busy}>{busy ? 'Sending…' : 'Send reset link'}</button>
            </form>
          )}
          <Link href="/login" className="mt-4 block text-center text-sm font-semibold text-balance">Back to sign in</Link>
        </div>
      </div>
    </div>
  )
}
