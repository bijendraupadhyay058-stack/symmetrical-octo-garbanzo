'use client'

import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react'
import { AlertTriangle, CheckCircle2, Info, XCircle } from 'lucide-react'

type ToastKind = 'success' | 'error' | 'info'
interface Toast {
  id: number
  kind: ToastKind
  text: string
}

interface ConfirmOptions {
  title: string
  message?: ReactNode
  confirmLabel?: string
  danger?: boolean
  /** When set, the dialog asks for text (e.g. a cancellation reason) and requires it. */
  input?: { label: string; placeholder?: string; required?: boolean }
}

interface FeedbackValue {
  toast: (text: string, kind?: ToastKind) => void
  confirm: (opts: ConfirmOptions) => Promise<{ ok: boolean; value: string }>
}

const FeedbackContext = createContext<FeedbackValue | null>(null)

export function FeedbackProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const [dialog, setDialog] = useState<(ConfirmOptions & { resolve: (r: { ok: boolean; value: string }) => void }) | null>(null)
  const [value, setValue] = useState('')
  const seq = useRef(0)

  const toast = useCallback((text: string, kind: ToastKind = 'success') => {
    const id = ++seq.current
    setToasts((t) => [...t.slice(-2), { id, kind, text }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === 'error' ? 6000 : 3200)
  }, [])

  const confirm = useCallback((opts: ConfirmOptions) => {
    setValue('')
    return new Promise<{ ok: boolean; value: string }>((resolve) => setDialog({ ...opts, resolve }))
  }, [])

  const close = (ok: boolean) => {
    dialog?.resolve({ ok, value: value.trim() })
    setDialog(null)
  }
  const needsInput = !!dialog?.input && dialog.input.required !== false && !value.trim()

  const icon = { success: CheckCircle2, error: XCircle, info: Info }
  return (
    <FeedbackContext.Provider value={{ toast, confirm }}>
      {children}
      <div className="no-print pointer-events-none fixed inset-x-0 top-[max(env(safe-area-inset-top),12px)] z-[80] flex flex-col items-center gap-2 px-4" aria-live="polite">
        {toasts.map((t) => {
          const Icon = icon[t.kind]
          return (
            <div
              key={t.id}
              role={t.kind === 'error' ? 'alert' : 'status'}
              className={`animate-fade-in pointer-events-auto flex max-w-md items-start gap-2.5 rounded-xl px-4 py-3 text-sm font-medium text-white shadow-lg ${
                t.kind === 'error' ? 'bg-[#b42318]' : t.kind === 'info' ? 'bg-navy-800' : 'bg-[#166534]'
              }`}
            >
              <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
              <span>{t.text}</span>
            </div>
          )
        })}
      </div>
      {dialog && (
        <div className="no-print fixed inset-0 z-[90] flex items-end justify-center bg-black/45 p-3 sm:items-center" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
          <div className="animate-slide-up w-full max-w-md rounded-2xl bg-surface p-5 shadow-2xl">
            <div className="flex items-start gap-3">
              {dialog.danger && <AlertTriangle className="mt-0.5 size-6 shrink-0 text-expense" aria-hidden />}
              <div className="min-w-0 flex-1">
                <h2 id="confirm-title" className="text-lg font-bold">{dialog.title}</h2>
                {dialog.message && <div className="mt-1.5 text-sm text-muted">{dialog.message}</div>}
              </div>
            </div>
            {dialog.input && (
              <label className="mt-4 block">
                <span className="label">{dialog.input.label}</span>
                <input autoFocus className="input" placeholder={dialog.input.placeholder} value={value} onChange={(e) => setValue(e.target.value)} />
              </label>
            )}
            <div className="mt-5 grid grid-cols-2 gap-3">
              <button className="btn-outline" onClick={() => close(false)}>Cancel</button>
              <button className={dialog.danger ? 'btn-danger' : 'btn-primary'} disabled={needsInput} onClick={() => close(true)}>
                {dialog.confirmLabel ?? 'Confirm'}
              </button>
            </div>
          </div>
        </div>
      )}
    </FeedbackContext.Provider>
  )
}

export function useFeedback(): FeedbackValue {
  const ctx = useContext(FeedbackContext)
  if (!ctx) throw new Error('useFeedback must be used inside FeedbackProvider')
  return ctx
}
