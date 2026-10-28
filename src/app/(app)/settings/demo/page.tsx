'use client'

import { useRouter } from 'next/navigation'
import { FlaskConical } from 'lucide-react'
import { useApp } from '@/components/app-provider'
import { useFeedback } from '@/components/feedback'
import { PageHeader } from '@/components/ui'

const rows = [
  ['GST Return Filing Fees received', '₹2,500', 'Cash', 'Cash Book: +2,500 (CR)', 'Income +2,500 · Cash balance +2,500'],
  ['Income Tax Return Fees received', '₹1,500', 'UPI', 'UPI Book: +1,500 (BR)', 'Income +1,500 · Cash unchanged'],
  ['Accounting Fees received', '₹8,000', 'Bank', 'Bank Book: +8,000 (BR)', 'Income +8,000 · Cash unchanged'],
  ['Office Stationery expense', '₹750', 'Cash', 'Cash Book: −750 (CP)', 'Expense +750 · Cash balance −750'],
  ['Internet expense', '₹999', 'UPI', 'UPI Book: −999 (BP)', 'Expense +999 · Cash unchanged'],
  ['Travelling expense', '₹350', 'Cash', 'Cash Book: −350 (CP)', 'Expense +350 · Cash balance −350'],
]

export default function DemoPage() {
  const { mode, openDemo, leaveDemo, resetDemo } = useApp()
  const { confirm, toast } = useFeedback()
  const router = useRouter()
  return (
    <div className="space-y-4">
      <PageHeader title="Sample Data (Demo)" subtitle="A separate practice workspace with example entries" back="/settings" />
      <div className="card space-y-3 p-4">
        <p className="flex gap-2 text-sm"><FlaskConical className="size-5 shrink-0 text-[#b45309]" /> The demo lives in its own database on this device. It is never synced and never mixed with your real books. Clearing it cannot affect real data.</p>
        {mode === 'demo' ? (
          <div className="grid gap-2">
            <button className="btn-primary" onClick={async () => { await leaveDemo(); router.replace('/') }}>Exit demo – back to my books</button>
            <button className="btn-outline text-expense" onClick={async () => {
              const r = await confirm({ title: 'Clear and reload sample data?', message: 'Only the demo workspace is reset.', confirmLabel: 'Reset demo', danger: true })
              if (!r.ok) return
              await resetDemo()
              toast('Sample data reset')
            }}>Clear & reload sample data</button>
          </div>
        ) : (
          <button className="btn-primary w-full" onClick={async () => { await openDemo(); router.replace('/dashboard') }}>Open demo workspace</button>
        )}
      </div>
      <div className="card overflow-x-auto p-4">
        <h2 className="mb-1 font-bold">How the sample entries post</h2>
        <p className="mb-3 text-xs text-muted">Opening: Cash ₹10,000 · Bank ₹50,000 · UPI ₹0</p>
        <table className="fin-table min-w-[620px]">
          <thead><tr><th>Entry</th><th>Amount</th><th>Mode</th><th>Ledger</th><th>Effect</th></tr></thead>
          <tbody>{rows.map((r) => <tr key={r[0]}>{r.map((c, i) => <td key={i}>{c}</td>)}</tr>)}</tbody>
        </table>
        <div className="mt-3 grid gap-1 text-sm">
          <div>Cash: 10,000 + 2,500 − 750 − 350 = <b>₹11,400</b></div>
          <div>Bank: 50,000 + 8,000 = <b>₹58,000</b></div>
          <div>UPI: 0 + 1,500 − 999 = <b>₹501</b></div>
          <div>Total income ₹12,000 · Total expenses ₹2,099 · Net ₹9,901</div>
        </div>
      </div>
    </div>
  )
}
