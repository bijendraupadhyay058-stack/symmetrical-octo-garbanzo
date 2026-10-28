import { describe, expect, it } from 'vitest'
import { amountInWords, formatAmount, formatINR, parseRupees } from '@/lib/money'
import { addMonths, fyLabel, fyMonths, fyOf, fyRange, formatDate, presetRange, todayIST } from '@/lib/dates'

describe('money (integer paise)', () => {
  it('parses rupee input without floating point error', () => {
    expect(parseRupees('1,500')).toBe(150000)
    expect(parseRupees('₹ 2,500.75')).toBe(250075)
    expect(parseRupees('0.1')).toBe(10)
    expect(parseRupees('19.99')).toBe(1999)
    expect(parseRupees('1.005')).toBeNull()
    expect(parseRupees('-5')).toBeNull()
    expect(parseRupees('abc')).toBeNull()
    expect(parseRupees('')).toBeNull()
  })
  it('sums exactly', () => {
    // 0.1 + 0.2 style errors cannot happen with paise
    expect(parseRupees('0.10')! + parseRupees('0.20')!).toBe(30)
  })
  it('formats with Indian grouping', () => {
    expect(formatAmount(1234567890)).toBe('1,23,45,678.90')
    expect(formatAmount(100000)).toBe('1,000.00')
    expect(formatAmount(-150050)).toBe('-1,500.50')
    expect(formatINR(1350000)).toBe('₹13,500.00')
  })
  it('writes amounts in words (Indian system)', () => {
    expect(amountInWords(250000)).toBe('Rupees Two Thousand Five Hundred Only')
    expect(amountInWords(12345678950)).toBe('Rupees Twelve Crore Thirty Four Lakh Fifty Six Thousand Seven Hundred Eighty Nine and Fifty Paise Only')
  })
})

describe('dates (Asia/Kolkata, April–March FY)', () => {
  it('computes today in IST regardless of device timezone', () => {
    // 2026-03-31 20:00 UTC is already 1 April 01:30 in India
    expect(todayIST(new Date('2026-03-31T20:00:00Z'))).toBe('2026-04-01')
    expect(todayIST(new Date('2026-04-01T18:29:00Z'))).toBe('2026-04-01')
  })
  it('maps dates to financial years', () => {
    expect(fyOf('2026-04-01')).toBe(2026)
    expect(fyOf('2027-03-31')).toBe(2026)
    expect(fyLabel(2026)).toBe('2026-27')
    expect(fyRange(2026)).toEqual({ from: '2026-04-01', to: '2027-03-31' })
    expect(fyMonths(2026)[0]).toBe('2026-04')
    expect(fyMonths(2026)[11]).toBe('2027-03')
  })
  it('handles period presets and month ends', () => {
    expect(presetRange('previous_month', '2026-03-15')).toEqual({ from: '2026-02-01', to: '2026-02-28' })
    expect(presetRange('previous_fy', '2026-05-01')).toEqual({ from: '2025-04-01', to: '2026-03-31' })
    expect(addMonths('2026-01-31', 1)).toBe('2026-02-28')
    expect(formatDate('2026-04-02')).toBe('02-04-2026')
  })
})
