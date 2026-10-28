'use client'

import { Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { formatAmount } from '@/lib/money'

// Categorical order (validated for colour-vision deficiency); never cycled –
// categories beyond 7 fold into "Other".
const CATEGORICAL = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#8a94a6']

const rupees = (v: number) => '₹' + formatAmount(Math.round(v * 100))
const compact = (v: number) => (v >= 100000 ? `${(v / 100000).toFixed(v >= 1000000 ? 0 : 1)}L` : v >= 1000 ? `${Math.round(v / 1000)}k` : String(v))

const tooltipStyle = {
  contentStyle: { background: 'var(--app-surface)', border: '1px solid var(--app-border)', borderRadius: 12, fontSize: 12, color: 'var(--app-text)' },
  labelStyle: { fontWeight: 700, color: 'var(--app-text)' },
  itemStyle: { color: 'var(--app-text)' },
  cursor: { fill: 'var(--app-elev)' },
}

const axis = { tick: { fontSize: 11, fill: 'var(--app-muted)' }, axisLine: false, tickLine: false }

export interface MonthPoint {
  label: string
  income: number
  expense: number
  cash: number
  bank: number
}

export function IncomeExpenseChart({ data }: { data: MonthPoint[] }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} margin={{ top: 8, right: 4, left: -12, bottom: 0 }} barGap={2} barCategoryGap="22%">
        <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
        <XAxis dataKey="label" {...axis} interval={0} angle={-35} textAnchor="end" height={42} />
        <YAxis {...axis} tickFormatter={compact} width={44} />
        <Tooltip formatter={(v) => rupees(Number(v))} {...tooltipStyle} />
        <Legend iconType="circle" iconSize={9} wrapperStyle={{ fontSize: 12, color: 'var(--app-muted)' }} />
        <Bar dataKey="income" name="Income" fill="var(--chart-income)" radius={[4, 4, 0, 0]} maxBarSize={18} />
        <Bar dataKey="expense" name="Expenses" fill="var(--chart-expense)" radius={[4, 4, 0, 0]} maxBarSize={18} />
      </BarChart>
    </ResponsiveContainer>
  )
}

export function CollectionChart({ data }: { data: MonthPoint[] }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} margin={{ top: 8, right: 4, left: -12, bottom: 0 }} barCategoryGap="22%">
        <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
        <XAxis dataKey="label" {...axis} interval={0} angle={-35} textAnchor="end" height={42} />
        <YAxis {...axis} tickFormatter={compact} width={44} />
        <Tooltip formatter={(v) => rupees(Number(v))} {...tooltipStyle} />
        <Legend iconType="circle" iconSize={9} wrapperStyle={{ fontSize: 12, color: 'var(--app-muted)' }} />
        <Bar dataKey="cash" name="Cash" stackId="c" fill="var(--chart-s1)" stroke="var(--app-surface)" strokeWidth={1} maxBarSize={22} />
        <Bar dataKey="bank" name="Bank / UPI" stackId="c" fill="var(--chart-s2)" stroke="var(--app-surface)" strokeWidth={1} radius={[4, 4, 0, 0]} maxBarSize={22} />
      </BarChart>
    </ResponsiveContainer>
  )
}

export function CategoryDonut({ data }: { data: { name: string; value: number }[] }) {
  const top = data.slice(0, 7)
  const rest = data.slice(7).reduce((s, d) => s + d.value, 0)
  const rows = rest > 0 ? [...top, { name: 'Other', value: rest }] : top
  const total = rows.reduce((s, d) => s + d.value, 0)
  return (
    <div className="grid items-center gap-3 sm:grid-cols-[200px_1fr]">
      <ResponsiveContainer width="100%" height={190}>
        <PieChart>
          <Pie data={rows} dataKey="value" nameKey="name" innerRadius={52} outerRadius={84} paddingAngle={1.5} stroke="var(--app-surface)" strokeWidth={2}>
            {rows.map((r, i) => <Cell key={r.name} fill={CATEGORICAL[i]} />)}
          </Pie>
          <Tooltip formatter={(v) => rupees(Number(v))} {...tooltipStyle} />
        </PieChart>
      </ResponsiveContainer>
      <ul className="space-y-1.5 text-[13px]">
        {rows.map((r, i) => (
          <li key={r.name} className="flex items-center gap-2">
            <span className="size-2.5 shrink-0 rounded-full" style={{ background: CATEGORICAL[i] }} aria-hidden />
            <span className="min-w-0 flex-1 truncate">{r.name}</span>
            <span className="num font-semibold">{rupees(r.value)}</span>
            <span className="num w-10 text-right text-muted">{total ? Math.round((r.value * 100) / total) : 0}%</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
