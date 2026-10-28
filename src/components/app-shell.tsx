'use client'

import { useEffect, useState, type ReactNode } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import {
  BarChart3, BookOpen, Bell, Building2, CloudOff, Cloud, FileText, FlaskConical, History, Home, List, Lock,
  Menu, Plus, RefreshCw, Settings, ShieldCheck, Users, Wallet, X, AlertTriangle, LogOut, Receipt, HardDriveDownload,
} from 'lucide-react'
import { useApp, useData, useSyncStatus } from './app-provider'
import { Logo, Splash } from './splash'
import { LockScreen } from './lock-screen'
import { useFeedback } from './feedback'

const bottomNav = [
  { href: '/dashboard', label: 'Home', icon: Home },
  { href: '/transactions', label: 'Transactions', icon: List },
  { href: '/add', label: 'Add Entry', icon: Plus, primary: true },
  { href: '/reports', label: 'Reports', icon: BarChart3 },
  { href: '/settings', label: 'Settings', icon: Settings },
]

export const menuSections: { title: string; items: { href: string; label: string; icon: typeof Home }[] }[] = [
  {
    title: 'Daily work',
    items: [
      { href: '/dashboard', label: 'Dashboard', icon: Home },
      { href: '/add/income', label: 'Add Income', icon: Plus },
      { href: '/add/expense', label: 'Add Expense', icon: Receipt },
      { href: '/transactions', label: 'Transactions', icon: List },
      { href: '/cashbook', label: 'Cash Book & Bank Book', icon: BookOpen },
    ],
  },
  {
    title: 'Clients & fees',
    items: [
      { href: '/clients', label: 'Client Master', icon: Users },
      { href: '/fees', label: 'Professional Fee Register', icon: FileText },
      { href: '/reminders', label: 'Reminders', icon: Bell },
    ],
  },
  {
    title: 'Reports & records',
    items: [
      { href: '/reports', label: 'Reports', icon: BarChart3 },
      { href: '/audit', label: 'Audit History', icon: History },
      { href: '/sync', label: 'Sync Status', icon: RefreshCw },
    ],
  },
  {
    title: 'Setup',
    items: [
      { href: '/settings/profile', label: 'Business Profile', icon: Building2 },
      { href: '/settings/accounts', label: 'Accounts & Opening Balances', icon: Wallet },
      { href: '/settings/categories', label: 'Categories', icon: List },
      { href: '/settings/recurring', label: 'Recurring Expenses', icon: RefreshCw },
      { href: '/settings/backup', label: 'Backup & Restore', icon: HardDriveDownload },
      { href: '/settings/security', label: 'Security', icon: ShieldCheck },
      { href: '/settings/demo', label: 'Sample Data (Demo)', icon: FlaskConical },
      { href: '/settings', label: 'All Settings', icon: Settings },
    ],
  },
]

function isActive(path: string, href: string) {
  if (href === '/dashboard') return path === '/dashboard'
  return path === href || path.startsWith(href + '/')
}

function SyncBadge() {
  const { mode } = useApp()
  const st = useSyncStatus()
  const [online, setOnline] = useState(true)
  useEffect(() => {
    const u = () => setOnline(navigator.onLine)
    u()
    window.addEventListener('online', u)
    window.addEventListener('offline', u)
    return () => {
      window.removeEventListener('online', u)
      window.removeEventListener('offline', u)
    }
  }, [])
  if (mode !== 'cloud') {
    return (
      <span className="rounded-full bg-white/10 px-2.5 py-1 text-[11px] font-semibold text-white/80">
        {mode === 'demo' ? 'Demo' : 'This device only'}
      </span>
    )
  }
  const problem = st.errors > 0 || st.conflicts > 0
  const label = !online
    ? st.pending ? `Offline · ${st.pending} pending` : 'Offline'
    : st.state === 'syncing' ? 'Syncing…'
    : problem ? `${st.errors + st.conflicts} need attention`
    : st.pending ? `${st.pending} pending` : 'Synced'
  const Icon = !online ? CloudOff : problem ? AlertTriangle : st.state === 'syncing' ? RefreshCw : Cloud
  return (
    <Link
      href="/sync"
      className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold ${
        problem ? 'bg-[#f59e0b] text-[#2b1700]' : st.pending || !online ? 'bg-white/15 text-white' : 'bg-white/10 text-white/80'
      }`}
      aria-label={`Sync status: ${label}`}
    >
      <Icon className={`size-3.5 ${st.state === 'syncing' ? 'animate-spin' : ''}`} aria-hidden />
      {label}
    </Link>
  )
}

function Drawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const path = usePathname()
  const data = useData()
  const { mode, user, signOut, lockNow } = useApp()
  const { confirm } = useFeedback()
  const router = useRouter()
  const st = useSyncStatus()
  if (!open) return null
  return (
    <div className="no-print fixed inset-0 z-[65] bg-black/40 lg:hidden" onClick={onClose}>
      <nav className="animate-fade-in flex h-full w-[86%] max-w-sm flex-col overflow-y-auto bg-surface pb-[env(safe-area-inset-bottom)]" onClick={(e) => e.stopPropagation()} aria-label="Main menu">
        <div className="flex items-center gap-3 bg-navy-900 px-4 pt-[max(env(safe-area-inset-top),16px)] pb-4 text-white">
          {data.profile?.logo_data_url ? <img src={data.profile.logo_data_url} alt="" className="size-11 rounded-xl bg-white object-contain" /> : <Logo size={44} />}
          <div className="min-w-0 flex-1">
            <div className="truncate font-bold">{data.profile?.name}</div>
            <div className="truncate text-xs text-white/70">{mode === 'cloud' ? user?.email : mode === 'demo' ? 'Demo workspace' : 'Device-only mode'}</div>
          </div>
          <button onClick={onClose} className="rounded-lg p-2 hover:bg-white/10" aria-label="Close menu"><X className="size-5" /></button>
        </div>
        <MenuLinks path={path} onNavigate={onClose} />
        <div className="mt-auto space-y-1 border-t border-line p-3">
          {mode !== 'demo' && (data.profile?.settings.auto_lock_minutes ?? 0) > 0 && (
            <button className="btn-ghost w-full justify-start" onClick={() => { onClose(); lockNow() }}><Lock className="size-5" /> Lock now</button>
          )}
          {mode !== 'demo' && (
            <button
              className="btn-ghost w-full justify-start text-expense"
              onClick={async () => {
                const warn = st.pending ? `${st.pending} change(s) have not been uploaded yet. They stay safely on this device and will upload when you sign in again.` : undefined
                const r = await confirm({ title: 'Sign out?', message: warn, confirmLabel: 'Sign out', danger: !!st.pending })
                if (!r.ok) return
                onClose()
                await signOut()
                router.replace('/login')
              }}
            >
              <LogOut className="size-5" /> Sign out
            </button>
          )}
        </div>
      </nav>
    </div>
  )
}

function MenuLinks({ path, onNavigate }: { path: string; onNavigate?: () => void }) {
  return (
    <div className="p-2">
      {menuSections.map((sec) => (
        <div key={sec.title} className="mb-2">
          <div className="px-3 pt-2 pb-1 text-[11px] font-bold tracking-wider text-muted uppercase">{sec.title}</div>
          {sec.items.map((it) => (
            <Link
              key={it.href + it.label}
              href={it.href}
              onClick={onNavigate}
              className={`flex min-h-11 items-center gap-3 rounded-xl px-3 text-[15px] font-medium ${isActive(path, it.href) && it.href !== '/settings' ? 'bg-balance-soft text-balance' : 'text-fg hover:bg-elev'}`}
            >
              <it.icon className="size-5 shrink-0" aria-hidden />
              {it.label}
            </Link>
          ))}
        </div>
      ))}
    </div>
  )
}

export function AppShell({ children }: { children: ReactNode }) {
  const { phase, locked, mode, error, retry, signOut, leaveDemo } = useApp()
  const router = useRouter()
  const path = usePathname()
  const [drawer, setDrawer] = useState(false)

  useEffect(() => {
    if (phase === 'signed-out') router.replace('/login')
  }, [phase, router])

  if (phase === 'loading' || phase === 'signed-out') return <Splash />
  if (phase === 'error') {
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-4 p-6 text-center">
        <AlertTriangle className="size-10 text-expense" />
        <p className="max-w-sm font-semibold">{error}</p>
        <p className="max-w-sm text-sm text-muted">Your saved entries on this device are not affected.</p>
        <div className="flex gap-3">
          <button className="btn-primary" onClick={retry}>Try again</button>
          <button className="btn-outline" onClick={() => signOut()}>Sign out</button>
        </div>
      </div>
    )
  }
  if (locked) return <LockScreen />

  return (
    <ShellInner path={path} drawer={drawer} setDrawer={setDrawer} mode={mode} leaveDemo={leaveDemo}>
      {children}
    </ShellInner>
  )
}

function ShellInner({ children, path, drawer, setDrawer, mode, leaveDemo }: { children: ReactNode; path: string; drawer: boolean; setDrawer: (b: boolean) => void; mode: string | null; leaveDemo: () => Promise<void> }) {
  const data = useData()
  const router = useRouter()
  return (
    <div className="min-h-dvh lg:pl-72">
      <aside className="no-print fixed inset-y-0 left-0 z-30 hidden w-72 overflow-y-auto border-r border-line bg-surface lg:block" aria-label="Main menu">
        <div className="flex items-center gap-3 px-5 py-5">
          <Logo size={40} />
          <div>
            <div className="font-bold">FIN TAX PRO</div>
            <div className="text-xs text-muted">CashBook</div>
          </div>
        </div>
        <MenuLinks path={path} />
      </aside>

      <header className="no-print sticky top-0 z-40 bg-navy-900 pt-[env(safe-area-inset-top)] text-white shadow-md">
        <div className="mx-auto flex h-14 max-w-4xl items-center gap-2 px-2">
          <button className="rounded-xl p-2.5 hover:bg-white/10 lg:hidden" onClick={() => setDrawer(true)} aria-label="Open menu">
            <Menu className="size-6" />
          </button>
          <Link href="/dashboard" className="flex min-w-0 flex-1 items-center gap-2.5 lg:pl-3">
            {data.profile?.logo_data_url ? <img src={data.profile.logo_data_url} alt="" className="size-8 rounded-lg bg-white object-contain" /> : <Logo size={32} />}
            <span className="truncate text-[16px] font-bold">{data.profile?.name ?? 'FIN TAX PRO'}</span>
          </Link>
          <SyncBadge />
        </div>
        {mode === 'demo' && (
          <div className="flex items-center gap-2 bg-[#f59e0b] px-3 py-1.5 text-[12.5px] font-semibold text-[#2b1700]">
            <FlaskConical className="size-4 shrink-0" aria-hidden />
            <span className="flex-1">SAMPLE DATA – demo workspace, separate from your real books</span>
            <button className="rounded-md bg-[#2b1700] px-2 py-0.5 text-white" onClick={async () => { await leaveDemo(); router.replace('/') }}>Exit demo</button>
          </div>
        )}
      </header>

      <Drawer open={drawer} onClose={() => setDrawer(false)} />

      <main className="mx-auto max-w-4xl px-4 pt-4 pb-[calc(96px+env(safe-area-inset-bottom))] lg:pb-10">{children}</main>

      <nav className="no-print fixed inset-x-0 bottom-0 z-40 border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden" aria-label="Bottom navigation">
        <div className="mx-auto grid h-16 max-w-xl grid-cols-5">
          {bottomNav.map((it) => {
            const active = isActive(path, it.href)
            if (it.primary) {
              return (
                <Link key={it.href} href={it.href} className="flex flex-col items-center justify-start" aria-label={it.label}>
                  <span className={`-mt-5 flex size-14 items-center justify-center rounded-full bg-primary text-primary-fg shadow-lg ring-4 ring-bg ${active ? 'brightness-125' : ''}`}>
                    <it.icon className="size-7" aria-hidden />
                  </span>
                  <span className="mt-0.5 text-[11px] font-semibold text-muted">{it.label}</span>
                </Link>
              )
            }
            return (
              <Link key={it.href} href={it.href} className={`flex flex-col items-center justify-center gap-0.5 text-[11px] font-semibold ${active ? 'text-balance' : 'text-muted'}`} aria-current={active ? 'page' : undefined}>
                <it.icon className="size-6" aria-hidden />
                {it.label}
              </Link>
            )
          })}
        </div>
      </nav>
    </div>
  )
}
