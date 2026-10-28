'use client'

import { useEffect, useState, type ReactNode, type InputHTMLAttributes, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react'
import Link from 'next/link'
import { ArrowLeft, ChevronDown, Loader2, X } from 'lucide-react'
import { formatINR, paiseToInput, parseRupees, type Paise } from '@/lib/money'

export function Spinner({ className = '' }: { className?: string }) {
  return <Loader2 className={`size-5 animate-spin ${className}`} aria-label="Loading" />
}

export function PageHeader({ title, subtitle, back, actions }: { title: string; subtitle?: ReactNode; back?: string; actions?: ReactNode }) {
  return (
    <div className="mb-4 flex items-start gap-2">
      {back && (
        <Link href={back} className="btn-ghost -ml-2 min-h-10 px-2" aria-label="Back">
          <ArrowLeft className="size-5" />
        </Link>
      )}
      <div className="min-w-0 flex-1">
        <h1 className="text-xl leading-tight font-bold text-fg">{title}</h1>
        {subtitle && <div className="mt-0.5 text-[13px] text-muted">{subtitle}</div>}
      </div>
      {actions && <div className="no-print flex shrink-0 items-center gap-1.5">{actions}</div>}
    </div>
  )
}

export function Field({ label, error, hint, children, className = '' }: { label: string; error?: string; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={`block ${className}`}>
      <span className="label">{label}</span>
      {children}
      {error ? (
        <span role="alert" className="mt-1 block text-[13px] font-medium text-expense">{error}</span>
      ) : hint ? (
        <span className="mt-1 block text-[12px] text-muted">{hint}</span>
      ) : null}
    </label>
  )
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`input ${props.className ?? ''}`} />
}

export function Select({ children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className="relative">
      <select {...props} className={`input appearance-none pr-9 ${props.className ?? ''}`}>
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted" aria-hidden />
    </div>
  )
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea rows={2} {...props} className={`input py-3 ${props.className ?? ''}`} />
}

/** Rupee input that keeps the typed text and reports integer paise. */
export function MoneyInput({ value, onChange, id, autoFocus, ariaLabel }: { value: Paise; onChange: (p: Paise) => void; id?: string; autoFocus?: boolean; ariaLabel?: string }) {
  const [text, setText] = useState(value ? paiseToInput(value) : '')
  useEffect(() => {
    const parsed = parseRupees(text) ?? 0
    if (parsed !== value) setText(value ? paiseToInput(value) : '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])
  return (
    <div className="relative">
      <span className="pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-lg font-semibold text-muted">₹</span>
      <input
        id={id}
        autoFocus={autoFocus}
        aria-label={ariaLabel}
        inputMode="decimal"
        autoComplete="off"
        className="input num pl-8 text-xl font-bold"
        placeholder="0.00"
        value={text}
        onChange={(e) => {
          const t = e.target.value.replace(/[^\d.,]/g, '')
          setText(t)
          onChange(parseRupees(t) ?? 0)
        }}
      />
    </div>
  )
}

export function Amount({ paise, tone, className = '', sign }: { paise: Paise; tone?: 'income' | 'expense' | 'balance' | 'auto'; className?: string; sign?: boolean }) {
  const t = tone === 'auto' ? (paise < 0 ? 'expense' : 'balance') : tone
  const color = t === 'income' ? 'text-income' : t === 'expense' ? 'text-expense' : t === 'balance' ? 'text-balance' : ''
  const prefix = sign ? (t === 'income' ? '+' : t === 'expense' ? '−' : '') : ''
  return <span className={`num ${color} ${className}`}>{prefix}{formatINR(sign ? Math.abs(paise) : paise)}</span>
}

export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'income' | 'expense' | 'balance' | 'warn' }) {
  const cls = {
    neutral: 'bg-elev text-muted',
    income: 'bg-income-soft text-income',
    expense: 'bg-expense-soft text-expense',
    balance: 'bg-balance-soft text-balance',
    warn: 'bg-[#fff4e0] text-[#8a5300] dark:bg-[#33270f] dark:text-[#f5c26b]',
  }[tone]
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold ${cls}`}>{children}</span>
}

export function EmptyState({ icon, title, text, action }: { icon?: ReactNode; title: string; text?: string; action?: ReactNode }) {
  return (
    <div className="card flex flex-col items-center px-6 py-10 text-center">
      {icon && <div className="mb-3 text-muted">{icon}</div>}
      <p className="font-semibold">{title}</p>
      {text && <p className="mt-1 max-w-xs text-sm text-muted">{text}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function Sheet({ open, onClose, title, children, footer }: { open: boolean; onClose: () => void; title: string; children: ReactNode; footer?: ReactNode }) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="no-print fixed inset-0 z-[70] flex items-end justify-center bg-black/45 sm:items-center sm:p-4" onClick={onClose} role="dialog" aria-modal="true" aria-label={title}>
      <div className="animate-slide-up flex max-h-[92dvh] w-full max-w-lg flex-col rounded-t-3xl bg-surface shadow-2xl sm:rounded-3xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 border-b border-line px-5 py-3.5">
          <h2 className="flex-1 text-lg font-bold">{title}</h2>
          <button className="btn-ghost min-h-10 px-2" onClick={onClose} aria-label="Close">
            <X className="size-5" />
          </button>
        </div>
        <div className="overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="border-t border-line px-5 py-3 pb-[max(env(safe-area-inset-bottom),12px)]">{footer}</div>}
      </div>
    </div>
  )
}

export function Segmented<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: { value: T; label: string }[] }) {
  return (
    <div className="flex gap-1 rounded-xl bg-elev p-1" role="tablist">
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          aria-selected={value === o.value}
          onClick={() => onChange(o.value)}
          className={`min-h-10 flex-1 rounded-lg px-2 text-[13px] font-semibold transition ${value === o.value ? 'bg-surface text-fg shadow-sm' : 'text-muted'}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function StatCard({ label, value, tone, sub, icon }: { label: string; value: Paise | string; tone: 'income' | 'expense' | 'balance' | 'neutral'; sub?: ReactNode; icon?: ReactNode }) {
  const bar = { income: 'bg-income', expense: 'bg-expense', balance: 'bg-balance', neutral: 'bg-muted' }[tone]
  const color = { income: 'text-income', expense: 'text-expense', balance: 'text-balance', neutral: 'text-fg' }[tone]
  return (
    <div className="card relative overflow-hidden p-3.5">
      <span className={`absolute inset-y-0 left-0 w-1 ${bar}`} aria-hidden />
      <div className="flex items-center gap-1.5 text-[12px] font-semibold text-muted">
        {icon}
        <span className="truncate">{label}</span>
      </div>
      <div className={`num mt-1 text-[19px] leading-tight font-bold ${color}`}>{typeof value === 'number' ? formatINR(value) : value}</div>
      {sub && <div className="mt-0.5 truncate text-[11.5px] text-muted">{sub}</div>}
    </div>
  )
}
