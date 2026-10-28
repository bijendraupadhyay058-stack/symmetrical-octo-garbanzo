import { fyOf, fyShort, type ISODate } from '../dates'
import type { AccountKind, TxnType } from '../types'

export type VoucherPrefix = 'CR' | 'BR' | 'CP' | 'BP' | 'CT' | 'FB'

export const VOUCHER_PREFIX_LABELS: Record<VoucherPrefix, string> = {
  CR: 'Cash Receipt',
  BR: 'Bank/UPI Receipt',
  CP: 'Cash Payment',
  BP: 'Bank/UPI Payment',
  CT: 'Contra',
  FB: 'Fee Bill',
}

export function voucherPrefix(type: TxnType, accountKind: AccountKind | undefined): VoucherPrefix {
  if (type === 'contra') return 'CT'
  const cash = accountKind === 'cash'
  if (type === 'income') return cash ? 'CR' : 'BR'
  return cash ? 'CP' : 'BP'
}

/** "CR/26-27/007" → { prefix: 'CR', fy: '26-27', seq: 7 } */
export function parseVoucher(v: string): { prefix: string; fy: string; seq: number } | null {
  const m = /^([A-Z]{2})\/(\d{2}-\d{2})\/(\d+)$/.exec(v)
  if (!m) return null
  return { prefix: m[1], fy: m[2], seq: Number(m[3]) }
}

export function formatVoucher(prefix: VoucherPrefix, fy: number, seq: number): string {
  return `${prefix}/${fyShort(fy)}/${String(seq).padStart(3, '0')}`
}

/**
 * Next sequential number for a prefix in the financial year of `date`.
 * Numbers restart every April. Gaps are never re-used, so a cancelled
 * voucher keeps its number permanently.
 */
export function nextVoucherNo(existing: Iterable<string>, prefix: VoucherPrefix, date: ISODate): string {
  const fy = fyOf(date)
  const fyStr = fyShort(fy)
  let max = 0
  for (const v of existing) {
    const p = parseVoucher(v)
    if (p && p.prefix === prefix && p.fy === fyStr && p.seq > max) max = p.seq
  }
  return formatVoucher(prefix, fy, max + 1)
}

export function voucherMatches(voucher: string, prefix: VoucherPrefix, date: ISODate): boolean {
  const p = parseVoucher(voucher)
  return !!p && p.prefix === prefix && p.fy === fyShort(fyOf(date))
}
