import { Spinner } from './ui'

export function Logo({ size = 56 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden>
      <rect width="64" height="64" rx="16" fill="#0b2545" />
      <path d="M17 44V20h18" stroke="#fff" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      <path d="M17 32h13" stroke="#fff" strokeWidth="5" strokeLinecap="round" fill="none" />
      <path d="M38 44l5-10 5 5 6-13" stroke="#4ade80" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      <circle cx="47" cy="20" r="3" fill="#8ecae6" />
    </svg>
  )
}

export function Splash({ text }: { text?: string }) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-navy-900 text-white">
      <Logo size={72} />
      <div className="text-center">
        <div className="text-xl font-bold tracking-wide">FIN TAX PRO</div>
        <div className="text-sm text-white/70">CashBook</div>
      </div>
      <Spinner className="mt-2 text-white/80" />
      {text && <p className="text-sm text-white/70">{text}</p>}
    </div>
  )
}
