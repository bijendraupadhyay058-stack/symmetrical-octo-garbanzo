'use client'

import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'

/** Precached app routes so every screen opens offline after the first visit. */
export const APP_ROUTES = [
  '/', '/login', '/dashboard', '/transactions', '/add', '/add/income', '/add/expense', '/add/contra',
  '/cashbook', '/clients', '/clients/view', '/fees', '/reports', '/reports/view', '/reminders', '/more',
  '/audit', '/sync', '/settings', '/settings/profile', '/settings/accounts', '/settings/categories',
  '/settings/recurring', '/settings/backup', '/settings/security', '/settings/demo',
  '/reset-password', '/update-password',
]

let updateAccepted = false

/**
 * Registers the service worker. A new version is never activated behind the
 * user's back: a banner asks before reloading, so a half-filled form is not
 * lost. Saved data lives in IndexedDB and is untouched by updates.
 */
export function ServiceWorkerRegistrar() {
  const [waiting, setWaiting] = useState<ServiceWorker | null>(null)
  useEffect(() => {
    if (!('serviceWorker' in navigator) || process.env.NODE_ENV !== 'production') return
    let refreshing = false
    const onChange = () => {
      // Only reload when the user accepted an update (not on the first install's clients.claim()).
      if (refreshing || !updateAccepted) return
      refreshing = true
      window.location.reload()
    }
    navigator.serviceWorker.addEventListener('controllerchange', onChange)
    let timer: number | undefined
    navigator.serviceWorker
      .register('/sw.js', { scope: '/', updateViaCache: 'none' })
      .then((reg) => {
        const warm = () => reg.active?.postMessage({ type: 'WARM', routes: APP_ROUTES })
        if (reg.active) warm()
        else navigator.serviceWorker.ready.then(warm)
        if (reg.waiting && navigator.serviceWorker.controller) setWaiting(reg.waiting)
        reg.addEventListener('updatefound', () => {
          const w = reg.installing
          w?.addEventListener('statechange', () => {
            if (w.state === 'installed' && navigator.serviceWorker.controller) setWaiting(w)
          })
        })
        timer = window.setInterval(() => reg.update().catch(() => {}), 60 * 60 * 1000)
      })
      .catch(() => {})
    return () => {
      navigator.serviceWorker.removeEventListener('controllerchange', onChange)
      window.clearInterval(timer)
    }
  }, [])
  if (!waiting) return null
  return (
    <div className="no-print fixed inset-x-3 bottom-[calc(76px+env(safe-area-inset-bottom))] z-[60] mx-auto flex max-w-md items-center gap-3 rounded-2xl bg-navy-900 px-4 py-3 text-white shadow-xl">
      <RefreshCw className="size-5 shrink-0" aria-hidden />
      <span className="flex-1 text-sm">A new version is ready. Your data is safe.</span>
      <button className="rounded-lg bg-white px-3 py-1.5 text-sm font-semibold text-navy-900" onClick={() => {
        updateAccepted = true
        waiting.postMessage({ type: 'SKIP_WAITING' })
      }}>
        Update
      </button>
    </div>
  )
}
