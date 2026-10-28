/**
 * Money is stored and calculated exclusively as integer paise (1 ₹ = 100 paise).
 * Floating point rupee values are only produced for display/charting.
 */
export type Paise = number

export function assertPaise(value: number): asserts value is Paise {
  if (!Number.isSafeInteger(value)) throw new Error(`Invalid money value: ${value}`)
}

/**
 * Parse user input such as "1,500", "1500.5", "₹ 2,500.75" into paise.
 * Returns null for anything that is not a valid non-negative amount with at
 * most two decimal places. Never uses float multiplication.
 */
export function parseRupees(input: string | number | null | undefined): Paise | null {
  if (input === null || input === undefined) return null
  let s = String(input).trim().replace(/[₹,\s]/g, '').replace(/^rs\.?/i, '')
  if (s === '') return null
  if (!/^\d+(\.\d{0,2})?$/.test(s)) return null
  if (s.endsWith('.')) s = s.slice(0, -1)
  const [whole, frac = ''] = s.split('.')
  const paise = Number(whole) * 100 + Number((frac + '00').slice(0, 2))
  if (!Number.isSafeInteger(paise)) return null
  return paise
}

function groupIndian(whole: string): string {
  if (whole.length <= 3) return whole
  const last3 = whole.slice(-3)
  const rest = whole.slice(0, -3)
  return rest.replace(/\B(?=(\d{2})+(?!\d))/g, ',') + ',' + last3
}

/** 150050 → "1,500.50" (Indian digit grouping, always two decimals). */
export function formatAmount(paise: Paise, opts: { decimals?: boolean } = {}): string {
  const neg = paise < 0
  const abs = Math.abs(paise)
  const whole = Math.floor(abs / 100)
  const frac = abs % 100
  const body = groupIndian(String(whole)) + (opts.decimals === false ? '' : '.' + String(frac).padStart(2, '0'))
  return (neg ? '-' : '') + body
}

/** 150050 → "₹1,500.50" */
export function formatINR(paise: Paise, opts: { decimals?: boolean } = {}): string {
  const s = formatAmount(Math.abs(paise), opts)
  return (paise < 0 ? '-₹' : '₹') + s
}

/** Paise → rupee string suitable for an <input> ("1500.5" → "1500.50"). */
export function paiseToInput(paise: Paise): string {
  return formatAmount(paise).replace(/,/g, '')
}

/** For charts only. */
export function toRupees(paise: Paise): number {
  return paise / 100
}

export function sum(values: Paise[]): Paise {
  let t = 0
  for (const v of values) t += v
  return t
}

const ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten', 'Eleven', 'Twelve',
  'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen']
const tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']

function twoDigits(n: number): string {
  if (n < 20) return ones[n]
  return (tens[Math.floor(n / 10)] + ' ' + ones[n % 10]).trim()
}

function threeDigits(n: number): string {
  const h = Math.floor(n / 100)
  const r = n % 100
  return [h ? ones[h] + ' Hundred' : '', r ? twoDigits(r) : ''].filter(Boolean).join(' ')
}

/** Indian-system amount in words, used on printed receipts. */
export function amountInWords(paise: Paise): string {
  const rupees = Math.floor(Math.abs(paise) / 100)
  const p = Math.abs(paise) % 100
  if (rupees === 0 && p === 0) return 'Rupees Zero Only'
  const parts: string[] = []
  let n = rupees
  const crore = Math.floor(n / 10000000); n %= 10000000
  const lakh = Math.floor(n / 100000); n %= 100000
  const thousand = Math.floor(n / 1000); n %= 1000
  if (crore) parts.push(threeDigits(crore) + ' Crore')
  if (lakh) parts.push(twoDigits(lakh) + ' Lakh')
  if (thousand) parts.push(twoDigits(thousand) + ' Thousand')
  if (n) parts.push(threeDigits(n))
  let words = rupees ? 'Rupees ' + parts.join(' ') : 'Rupees Zero'
  if (p) words += ' and ' + twoDigits(p) + ' Paise'
  return words + ' Only'
}
