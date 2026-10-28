'use client'

import { presetLabels, presetRange, todayIST, type DateRange, type PeriodPreset } from '@/lib/dates'

export function PeriodFilter({
  preset,
  range,
  onChange,
  presets = ['today', 'current_month', 'previous_month', 'current_fy', 'previous_fy', 'custom'],
}: {
  preset: PeriodPreset
  range: DateRange
  onChange: (preset: PeriodPreset, range: DateRange) => void
  presets?: PeriodPreset[]
}) {
  return (
    <div className="space-y-2">
      <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1" role="radiogroup" aria-label="Period">
        {presets.map((p) => (
          <button key={p} role="radio" aria-checked={preset === p} className={preset === p ? 'chip-active' : 'chip'} onClick={() => onChange(p, presetRange(p, todayIST(), range))}>
            {presetLabels[p]}
          </button>
        ))}
      </div>
      {preset === 'custom' && (
        <div className="grid grid-cols-2 gap-2">
          <label>
            <span className="label">From</span>
            <input className="input" type="date" value={range.from} onChange={(e) => e.target.value && onChange('custom', { ...range, from: e.target.value })} />
          </label>
          <label>
            <span className="label">To</span>
            <input className="input" type="date" value={range.to} onChange={(e) => e.target.value && onChange('custom', { ...range, to: e.target.value })} />
          </label>
        </div>
      )}
    </div>
  )
}
