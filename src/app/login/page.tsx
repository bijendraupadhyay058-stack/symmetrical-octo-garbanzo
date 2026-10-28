'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { FlaskConical, Smartphone } from 'lucide-react'
import { useApp, cloudAvailable } from '@/components/app-provider'
import { Logo, Splash } from '@/components/splash'
import { Field, Segmented } from '@/components/ui'
import { isLocalModeAllowed } from '@/lib/supabase/client'

export default function LoginPage() {
  const { phase, signIn, signUp, openDemo, startLocal } = useApp()
  const router = useRouter()
  const cloud = cloudAvailable()
  const localAllowed = isLocalModeAllowed()
  const [tab, setTab] = useState<'signin' | 'signup' | 'local'>(cloud ? 'signin' : 'local')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [password2, setPassword2] = useState('')
  const [business, setBusiness] = useState('FIN TAX PRO')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ kind: 'error' | 'info'; text: string } | null>(null)

  useEffect(() => {
    if (phase === 'ready') router.replace('/dashboard')
  }, [phase, router])

  if (phase === 'loading' || phase === 'ready') return <Splash />

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setMsg(null)
    if (tab !== 'signin') {
      if (password.length < 8) return setMsg({ kind: 'error', text: 'Use a password of at least 8 characters.' })
      if (password !== password2) return setMsg({ kind: 'error', text: 'Passwords do not match.' })
      if (!business.trim()) return setMsg({ kind: 'error', text: 'Enter your business name.' })
    }
    setBusy(true)
    try {
      if (tab === 'signin') {
        const err = await signIn(email, password)
        if (err) setMsg({ kind: 'error', text: err })
      } else if (tab === 'signup') {
        const err = await signUp(email, password, business)
        if (err === 'CONFIRM_EMAIL') setMsg({ kind: 'info', text: 'Account created. Open the confirmation link sent to your email, then sign in.' })
        else if (err) setMsg({ kind: 'error', text: err })
      } else {
        await startLocal(business, password)
      }
    } finally {
      setBusy(false)
    }
  }

  const tabs = [
    ...(cloud ? [{ value: 'signin' as const, label: 'Sign in' }, { value: 'signup' as const, label: 'Create account' }] : []),
    ...(localAllowed ? [{ value: 'local' as const, label: cloud ? 'This device' : 'Set up' }] : []),
  ]

  return (
    <div className="min-h-dvh bg-navy-900">
      <div className="mx-auto flex min-h-dvh max-w-md flex-col px-5 pt-[max(env(safe-area-inset-top),40px)] pb-8">
        <div className="mb-8 flex flex-col items-center text-white">
          <Logo size={72} />
          <h1 className="mt-4 text-2xl font-bold tracking-wide">FIN TAX PRO</h1>
          <p className="text-sm text-white/70">CashBook · Income & Expense Manager</p>
        </div>
        <div className="card p-5">
          {tabs.length > 1 && (
            <div className="mb-5">
              <Segmented value={tab} onChange={(v) => { setTab(v); setMsg(null) }} options={tabs} />
            </div>
          )}
          {tab === 'local' && (
            <p className="mb-4 flex gap-2 rounded-xl bg-elev p-3 text-[13px] text-muted">
              <Smartphone className="size-4 shrink-0" />
              {cloud
                ? 'Data stays only on this device (no cloud backup or multi-device sync). Take regular backups from Settings.'
                : 'Cloud sync is not configured for this installation, so data is stored securely on this device only. Take regular backups from Settings.'}
            </p>
          )}
          <form onSubmit={submit} className="space-y-4">
            {tab !== 'signin' && (
              <Field label="Business name">
                <input className="input" value={business} onChange={(e) => setBusiness(e.target.value)} required />
              </Field>
            )}
            {tab !== 'local' && (
              <Field label="Email">
                <input className="input" type="email" autoComplete="username" inputMode="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
              </Field>
            )}
            <Field label={tab === 'local' ? 'App password (to unlock this app)' : 'Password'}>
              <input className="input" type="password" autoComplete={tab === 'signin' ? 'current-password' : 'new-password'} value={password} onChange={(e) => setPassword(e.target.value)} required />
            </Field>
            {tab !== 'signin' && (
              <Field label="Confirm password">
                <input className="input" type="password" autoComplete="new-password" value={password2} onChange={(e) => setPassword2(e.target.value)} required />
              </Field>
            )}
            {msg && (
              <p role="alert" className={`rounded-xl p-3 text-sm font-medium ${msg.kind === 'error' ? 'bg-expense-soft text-expense' : 'bg-balance-soft text-balance'}`}>{msg.text}</p>
            )}
            <button className="btn-primary w-full" disabled={busy}>
              {busy ? 'Please wait…' : tab === 'signin' ? 'Sign in' : tab === 'signup' ? 'Create account' : 'Start using CashBook'}
            </button>
            {tab === 'signin' && (
              <Link href="/reset-password" className="block text-center text-sm font-semibold text-balance">Forgot password?</Link>
            )}
          </form>
        </div>
        <button className="btn mt-5 border border-white/25 text-white" onClick={() => openDemo()}>
          <FlaskConical className="size-5" /> Explore with sample data
        </button>
        <p className="mt-6 text-center text-xs text-white/50">Secure connection · Your records are private to your account</p>
      </div>
    </div>
  )
}
