'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from 'react'
import type { Session, User } from '@supabase/supabase-js'
import { getSupabase, isLocalModeAllowed, isSupabaseConfigured } from '@/lib/supabase/client'
import { deleteLocalDb, openLocalDb, requestPersistentStorage } from '@/lib/store/local-db'
import { LocalStore } from '@/lib/store/store'
import { defaultBusinessRecords } from '@/lib/store/repo'
import { SyncEngine, type SyncStatus } from '@/lib/sync/engine'
import { createRemote } from '@/lib/sync/remote-factory'
import { DEMO_BUSINESS_ID, DEMO_DB_NAME, seedDemo } from '@/lib/demo'
import { autoSnapshot } from '@/lib/backup'
import { uuid } from '@/lib/ids'
import { fyOf, todayIST } from '@/lib/dates'
import { forgetLocalSecrets, rememberPassword, verifyBiometric, verifyLocalPassword, biometricEnabled } from '@/lib/security/local-auth'
import type { DataSnapshot } from '@/lib/types'

export type Mode = 'cloud' | 'local' | 'demo'
export type Phase = 'loading' | 'signed-out' | 'ready' | 'error'

interface AppContextValue {
  phase: Phase
  mode: Mode | null
  error: string | null
  user: { id: string; email: string } | null
  store: LocalStore | null
  engine: SyncEngine | null
  lockScope: string
  fy: number
  setFy: (fy: number) => void
  locked: boolean
  lockNow: () => void
  unlockWithPassword: (password: string) => Promise<boolean>
  unlockWithBiometric: () => Promise<boolean>
  signIn: (email: string, password: string) => Promise<string | null>
  signUp: (email: string, password: string, businessName: string) => Promise<string | null>
  signOut: (opts?: { eraseDevice?: boolean }) => Promise<void>
  startLocal: (businessName: string, password: string) => Promise<void>
  openDemo: () => Promise<void>
  leaveDemo: () => Promise<void>
  resetDemo: () => Promise<void>
  retry: () => void
}

const AppContext = createContext<AppContextValue | null>(null)

const LS = {
  mode: 'fintax.mode',
  prevMode: 'fintax.prevMode',
  fy: 'fintax.fy',
  lastActive: 'fintax.lastActive',
  locked: 'fintax.locked',
  theme: 'fintax.theme',
}

function ls(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}
function lsSet(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key)
    else localStorage.setItem(key, value)
  } catch {
    /* storage unavailable */
  }
}

export function applyTheme(theme: 'light' | 'dark' | 'system') {
  lsSet(LS.theme, theme)
  const dark = theme === 'dark' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.classList.toggle('dark', dark)
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#0a1220' : '#0b2545')
}

async function openBusiness(dbName: string, opts: { syncEnabled: boolean; isDemo: boolean }, resolveId: () => Promise<{ id: string; create: boolean }>) {
  const db = await openLocalDb(dbName)
  let bid = (await db.get('meta', 'business_id')) as string | undefined
  let create = false
  if (!bid) {
    const r = await resolveId()
    bid = r.id
    create = r.create
    await db.put('meta', bid, 'business_id')
  }
  const store = await LocalStore.open(db, bid, opts)
  if (!store.getSnapshot().profile && !create) create = !opts.syncEnabled
  return { store, create }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<Phase>('loading')
  const [mode, setMode] = useState<Mode | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [user, setUser] = useState<AppContextValue['user']>(null)
  const [store, setStore] = useState<LocalStore | null>(null)
  const [engine, setEngine] = useState<SyncEngine | null>(null)
  const [fy, setFyState] = useState<number>(() => fyOf(todayIST()))
  const [locked, setLocked] = useState(false)
  const [bootKey, setBootKey] = useState(0)
  const cleanupRef = useRef<(() => void) | null>(null)

  const lockScope = mode === 'cloud' && user ? user.id : mode === 'local' ? 'local' : 'demo'

  const attach = useCallback((s: LocalStore, e: SyncEngine | null, m: Mode) => {
    cleanupRef.current?.()
    const cleanups: (() => void)[] = []
    if (e) {
      const kick = () => void e.sync()
      const timer = window.setInterval(kick, 60_000)
      const onVis = () => document.visibilityState === 'visible' && kick()
      window.addEventListener('online', kick)
      document.addEventListener('visibilitychange', onVis)
      // Push soon after every local save.
      let debounce: number | undefined
      const unsub = s.subscribe(() => {
        if (!s.pendingCount()) return
        window.clearTimeout(debounce)
        debounce = window.setTimeout(kick, 1500)
      })
      cleanups.push(() => {
        window.clearInterval(timer)
        window.removeEventListener('online', kick)
        document.removeEventListener('visibilitychange', onVis)
        window.clearTimeout(debounce)
        unsub()
      })
    }
    cleanupRef.current = () => cleanups.forEach((c) => c())
    setStore(s)
    setEngine(e)
    setMode(m)
    const theme = s.getSnapshot().profile?.settings?.theme
    if (theme) applyTheme(theme)
    if (m !== 'demo') void autoSnapshot(s).catch(() => {})
    const mins = s.getSnapshot().profile?.settings?.auto_lock_minutes ?? 0
    const last = Number(ls(LS.lastActive) || 0)
    if (m !== 'demo' && mins > 0 && (ls(LS.locked) === '1' || (last && Date.now() - last > mins * 60_000))) setLocked(true)
    lsSet(LS.lastActive, String(Date.now()))
    setPhase('ready')
  }, [])

  const bootCloud = useCallback(async (u: User) => {
    const sb = getSupabase()!
    setUser({ id: u.id, email: u.email ?? '' })
    const { store: s, create } = await openBusiness(`fintaxpro-u-${u.id}`, { syncEnabled: true, isDemo: false }, async () => {
      const { data, error: err } = await sb.from('business_members').select('business_id').eq('user_id', u.id).limit(1)
      if (err) throw new Error('Could not reach the server. The first sign-in on a device needs an internet connection.')
      if (data?.length) return { id: data[0].business_id as string, create: false }
      return { id: uuid(), create: true }
    })
    if (create) {
      const name = (u.user_metadata?.business_name as string) || 'FIN TAX PRO'
      await s.save(defaultBusinessRecords(s.businessId, name, u.id))
    }
    const e = new SyncEngine(s, createRemote())
    if (!s.getSnapshot().profile || create) await e.sync()
    else void e.sync()
    lsSet(LS.mode, 'cloud')
    attach(s, e, 'cloud')
  }, [attach])

  const bootLocal = useCallback(async (businessName = 'FIN TAX PRO') => {
    const { store: s } = await openBusiness('fintaxpro-local', { syncEnabled: false, isDemo: false }, async () => ({ id: uuid(), create: true }))
    if (!s.getSnapshot().profile) await s.save(defaultBusinessRecords(s.businessId, businessName, null))
    lsSet(LS.mode, 'local')
    setUser(null)
    attach(s, null, 'local')
  }, [attach])

  const bootDemo = useCallback(async () => {
    const db = await openLocalDb(DEMO_DB_NAME)
    await db.put('meta', DEMO_BUSINESS_ID, 'business_id')
    const s = await LocalStore.open(db, DEMO_BUSINESS_ID, { syncEnabled: false, isDemo: true })
    await seedDemo(s)
    lsSet(LS.mode, 'demo')
    attach(s, null, 'demo')
  }, [attach])

  // Boot
  useEffect(() => {
    let cancelled = false
    const savedFy = Number(ls(LS.fy))
    if (savedFy > 2000) setFyState(savedFy)
    void requestPersistentStorage()
    const run = async () => {
      try {
        const saved = ls(LS.mode) as Mode | null
        if (saved === 'demo') return await bootDemo()
        if (saved === 'local' && isLocalModeAllowed()) return await bootLocal()
        const sb = getSupabase()
        if (sb) {
          const { data } = await sb.auth.getSession()
          if (cancelled) return
          if (data.session?.user) return await bootCloud(data.session.user)
        }
        setPhase('signed-out')
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e))
          setPhase('error')
        }
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [bootKey, bootCloud, bootDemo, bootLocal])

  // React to auth changes from other tabs / token expiry / password recovery links
  useEffect(() => {
    const sb = getSupabase()
    if (!sb) return
    const { data } = sb.auth.onAuthStateChange((event: string, session: Session | null) => {
      if (event === 'PASSWORD_RECOVERY' && !location.pathname.startsWith('/update-password')) location.assign('/update-password')
      if (event === 'SIGNED_OUT' && ls(LS.mode) === 'cloud') {
        cleanupRef.current?.()
        setStore(null)
        setEngine(null)
        setUser(null)
        setPhase('signed-out')
      }
      void session
    })
    return () => data.subscription.unsubscribe()
  }, [])

  // Inactivity auto-lock
  useEffect(() => {
    if (phase !== 'ready' || !store || mode === 'demo') return
    const minutes = () => store.getSnapshot().profile?.settings?.auto_lock_minutes ?? 0
    let lastWrite = 0
    const touch = () => {
      const now = Date.now()
      if (now - lastWrite > 5000) {
        lastWrite = now
        lsSet(LS.lastActive, String(now))
      }
    }
    const check = () => {
      const m = minutes()
      if (!m) return
      const last = Number(ls(LS.lastActive) || Date.now())
      if (Date.now() - last > m * 60_000) {
        lsSet(LS.locked, '1')
        setLocked(true)
      }
    }
    const events = ['pointerdown', 'keydown', 'scroll', 'touchstart']
    events.forEach((ev) => window.addEventListener(ev, touch, { passive: true }))
    const onVis = () => (document.visibilityState === 'visible' ? check() : touch())
    document.addEventListener('visibilitychange', onVis)
    const t = window.setInterval(check, 15_000)
    return () => {
      events.forEach((ev) => window.removeEventListener(ev, touch))
      document.removeEventListener('visibilitychange', onVis)
      window.clearInterval(t)
    }
  }, [phase, store, mode])

  const unlocked = useCallback(() => {
    lsSet(LS.locked, null)
    lsSet(LS.lastActive, String(Date.now()))
    setLocked(false)
  }, [])

  const value = useMemo<AppContextValue>(() => ({
    phase,
    mode,
    error,
    user,
    store,
    engine,
    lockScope,
    fy,
    setFy: (n) => {
      lsSet(LS.fy, String(n))
      setFyState(n)
    },
    locked,
    lockNow: () => {
      lsSet(LS.locked, '1')
      setLocked(true)
    },
    unlockWithPassword: async (password) => {
      let ok = false
      const sb = getSupabase()
      if (mode === 'cloud' && sb && user && navigator.onLine) {
        const { error: err } = await sb.auth.signInWithPassword({ email: user.email, password })
        ok = !err
        if (ok) await rememberPassword(lockScope, password)
      } else {
        ok = await verifyLocalPassword(lockScope, password)
      }
      if (ok) unlocked()
      return ok
    },
    unlockWithBiometric: async () => {
      if (!biometricEnabled(lockScope)) return false
      const ok = await verifyBiometric(lockScope)
      if (ok) unlocked()
      return ok
    },
    signIn: async (email, password) => {
      const sb = getSupabase()
      if (!sb) return 'Cloud sign-in is not configured for this installation.'
      const { data, error: err } = await sb.auth.signInWithPassword({ email: email.trim(), password })
      if (err || !data.user) return err?.message === 'Invalid login credentials' ? 'Incorrect email or password.' : err?.message ?? 'Sign-in failed'
      await rememberPassword(data.user.id, password)
      try {
        setPhase('loading')
        await bootCloud(data.user)
        unlocked()
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
        setPhase('error')
      }
      return null
    },
    signUp: async (email, password, businessName) => {
      const sb = getSupabase()
      if (!sb) return 'Cloud sign-up is not configured for this installation.'
      const { data, error: err } = await sb.auth.signUp({
        email: email.trim(),
        password,
        options: { data: { business_name: businessName.trim() }, emailRedirectTo: `${location.origin}/login` },
      })
      if (err) return err.message
      if (!data.session) return 'CONFIRM_EMAIL'
      await rememberPassword(data.user!.id, password)
      setPhase('loading')
      await bootCloud(data.user!)
      return null
    },
    signOut: async (opts) => {
      cleanupRef.current?.()
      const currentMode = mode
      const s = store
      if (currentMode === 'cloud') await getSupabase()?.auth.signOut()
      if (opts?.eraseDevice && s) {
        s.db.close()
        await deleteLocalDb(s.db.name)
        forgetLocalSecrets(lockScope)
      }
      lsSet(LS.mode, null)
      lsSet(LS.locked, null)
      setStore(null)
      setEngine(null)
      setUser(null)
      setMode(null)
      setPhase('signed-out')
    },
    startLocal: async (businessName, password) => {
      await rememberPassword('local', password)
      setPhase('loading')
      await bootLocal(businessName)
    },
    openDemo: async () => {
      const prev = ls(LS.mode)
      if (prev && prev !== 'demo') lsSet(LS.prevMode, prev)
      setPhase('loading')
      await bootDemo()
    },
    leaveDemo: async () => {
      const prev = ls(LS.prevMode)
      lsSet(LS.prevMode, null)
      lsSet(LS.mode, prev)
      cleanupRef.current?.()
      setStore(null)
      setPhase('loading')
      setBootKey((k) => k + 1)
    },
    resetDemo: async () => {
      store?.db.close()
      await deleteLocalDb(DEMO_DB_NAME)
      setPhase('loading')
      await bootDemo()
    },
    retry: () => {
      setError(null)
      setPhase('loading')
      setBootKey((k) => k + 1)
    },
  }), [phase, mode, error, user, store, engine, lockScope, fy, locked, unlocked, bootCloud, bootLocal, bootDemo])

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useApp(): AppContextValue {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used inside AppProvider')
  return ctx
}

const noopSub = () => () => {}

/** Live business data; re-renders whenever anything is saved or synced. */
export function useData(): DataSnapshot {
  const { store } = useApp()
  if (!store) throw new Error('Data not loaded')
  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot)
}

export function useStore(): LocalStore {
  const { store } = useApp()
  if (!store) throw new Error('Data not loaded')
  return store
}

const disabledStatus: SyncStatus = { state: 'disabled', pending: 0, errors: 0, conflicts: 0, lastSyncAt: null, lastError: null }

export function useSyncStatus(): SyncStatus {
  const { engine } = useApp()
  return useSyncExternalStore(engine?.subscribe ?? noopSub, engine?.getStatus ?? (() => disabledStatus), () => disabledStatus)
}

export const cloudAvailable = isSupabaseConfigured
