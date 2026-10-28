'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { Building2, ChevronRight, FlaskConical, HardDriveDownload, List, Lock, LogOut, Moon, RefreshCw, ShieldCheck, Smartphone, Sun, Wallet, History, CalendarRange } from 'lucide-react'
import { applyTheme, useApp, useData, useStore, useSyncStatus } from '@/components/app-provider'
import { useFeedback } from '@/components/feedback'
import { PageHeader, Segmented, Select } from '@/components/ui'
import { saveProfile } from '@/lib/store/repo'
import { fyLabel, fyOf, todayIST } from '@/lib/dates'
import { useEffect, useState } from 'react'

const links = [
  { href: '/settings/profile', label: 'Business Profile & Logo', icon: Building2, text: 'Name, address, GSTIN, receipt footer, reminder text' },
  { href: '/settings/accounts', label: 'Accounts & Opening Balances', icon: Wallet, text: 'Cash, bank and UPI accounts' },
  { href: '/settings/categories', label: 'Income & Expense Categories', icon: List, text: 'Add, rename or hide categories' },
  { href: '/settings/recurring', label: 'Recurring Expense Templates', icon: RefreshCw, text: 'Rent, salary, internet…' },
  { href: '/settings/backup', label: 'Backup, Restore & Export', icon: HardDriveDownload, text: 'Download or restore all data' },
  { href: '/settings/security', label: 'Security & Lock', icon: ShieldCheck, text: 'Auto-lock, fingerprint, password, books lock' },
  { href: '/audit', label: 'Audit History', icon: History, text: 'Every create, edit and cancellation' },
  { href: '/settings/demo', label: 'Sample Data (Demo)', icon: FlaskConical, text: 'Try the app with example entries' },
]

export default function SettingsPage() {
  const data = useData()
  const store = useStore()
  const { mode, user, fy, setFy, signOut, lockNow } = useApp()
  const { confirm } = useFeedback()
  const st = useSyncStatus()
  const router = useRouter()
  const theme = data.profile?.settings.theme ?? 'system'
  const [canInstall, setCanInstall] = useState<null | (() => void)>(null)
  useEffect(() => {
    const h = (e: Event) => {
      e.preventDefault()
      const ev = e as Event & { prompt: () => Promise<void> }
      setCanInstall(() => () => void ev.prompt())
    }
    window.addEventListener('beforeinstallprompt', h)
    return () => window.removeEventListener('beforeinstallprompt', h)
  }, [])
  const years = Array.from({ length: 6 }, (_, i) => fyOf(todayIST()) - i)
  return (
    <div className="space-y-4">
      <PageHeader title="Settings" subtitle={mode === 'cloud' ? `Signed in as ${user?.email}` : mode === 'demo' ? 'Demo workspace' : 'Device-only mode'} />
      <div className="card space-y-4 p-4">
        <div>
          <span className="label flex items-center gap-1.5"><Sun className="size-3.5" /> Theme <Moon className="size-3.5" /></span>
          <Segmented value={theme} onChange={async (t) => {
            applyTheme(t)
            if (data.profile) await saveProfile(store, { ...data.profile, settings: { ...data.profile.settings, theme: t } })
          }} options={[{ value: 'light', label: 'Light' }, { value: 'dark', label: 'Dark' }, { value: 'system', label: 'Auto' }]} />
        </div>
        <label className="block">
          <span className="label flex items-center gap-1.5"><CalendarRange className="size-3.5" /> Working financial year</span>
          <Select value={fy} onChange={(e) => setFy(Number(e.target.value))}>
            {years.map((y) => <option key={y} value={y}>FY {fyLabel(y)} (1 Apr {y} – 31 Mar {y + 1})</option>)}
          </Select>
        </label>
      </div>
      <div className="card divide-y divide-line overflow-hidden">
        {links.map((l) => (
          <Link key={l.href} href={l.href} className="flex items-center gap-3 px-4 py-3.5 hover:bg-elev">
            <l.icon className="size-5 text-balance" />
            <div className="min-w-0 flex-1">
              <div className="font-semibold">{l.label}</div>
              <div className="truncate text-xs text-muted">{l.text}</div>
            </div>
            <ChevronRight className="size-4 text-muted" />
          </Link>
        ))}
      </div>
      {canInstall && (
        <button className="btn-primary w-full" onClick={() => canInstall()}><Smartphone className="size-5" /> Install app on this device</button>
      )}
      {mode !== 'demo' && (
        <div className="grid gap-2">
          {(data.profile?.settings.auto_lock_minutes ?? 0) > 0 && <button className="btn-outline" onClick={lockNow}><Lock className="size-4" /> Lock now</button>}
          <button className="btn-outline text-expense" onClick={async () => {
            const r = await confirm({
              title: 'Sign out?',
              message: st.pending ? `${st.pending} change(s) are not uploaded yet. They stay on this device and upload when you sign in again.` : 'Your data stays saved.',
              confirmLabel: 'Sign out',
            })
            if (!r.ok) return
            await signOut()
            router.replace('/login')
          }}><LogOut className="size-4" /> Sign out</button>
        </div>
      )}
      <p className="text-center text-xs text-muted">FIN TAX PRO – CashBook v1.0 · Amounts in ₹ · Time zone Asia/Kolkata</p>
    </div>
  )
}
