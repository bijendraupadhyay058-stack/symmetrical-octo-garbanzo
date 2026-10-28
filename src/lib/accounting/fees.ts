import type { ISODate } from '../dates'
import type { Paise } from '../money'
import type { DataSnapshot, FeeBill, Transaction } from '../types'

export type FeeStatus = 'unpaid' | 'partial' | 'paid' | 'cancelled'

export interface BillPosition {
  bill: FeeBill
  received: Paise
  outstanding: Paise
  status: FeeStatus
  overdue: boolean
}

type FeeSnap = Pick<DataSnapshot, 'fee_bills' | 'fee_allocations' | 'transactions'>

/**
 * Fee bills are memorandum demands, not income. Income is recognised only when
 * a receipt (income transaction) is recorded; a receipt may be *allocated*
 * against bills to reduce what the client owes. This keeps billing and
 * collection separate so the same fee is never counted twice.
 */
export function billPositions(snap: FeeSnap, today?: ISODate): BillPosition[] {
  const activeTxn = new Set(snap.transactions.filter((t) => t.status === 'active').map((t) => t.id))
  const received = new Map<string, Paise>()
  for (const a of snap.fee_allocations) {
    if (!activeTxn.has(a.transaction_id)) continue
    received.set(a.fee_bill_id, (received.get(a.fee_bill_id) ?? 0) + a.amount_paise)
  }
  return snap.fee_bills.map((bill) => {
    const rec = received.get(bill.id) ?? 0
    if (bill.status === 'cancelled') {
      return { bill, received: rec, outstanding: 0, status: 'cancelled' as const, overdue: false }
    }
    const outstanding = bill.amount_paise - rec
    const status: FeeStatus = outstanding <= 0 ? 'paid' : rec > 0 ? 'partial' : 'unpaid'
    const overdue = !!today && outstanding > 0 && !!bill.due_date && bill.due_date < today
    return { bill, received: rec, outstanding, status, overdue }
  })
}

export function billOutstanding(snap: FeeSnap, billId: string, excludeTxnId?: string): Paise {
  const bill = snap.fee_bills.find((b) => b.id === billId)
  if (!bill || bill.status === 'cancelled') return 0
  const activeTxn = new Set(
    snap.transactions.filter((t) => t.status === 'active' && t.id !== excludeTxnId).map((t) => t.id),
  )
  let rec = 0
  for (const a of snap.fee_allocations) {
    if (a.fee_bill_id === billId && activeTxn.has(a.transaction_id)) rec += a.amount_paise
  }
  return bill.amount_paise - rec
}

export interface ClientPosition {
  clientId: string
  billed: Paise
  allocated: Paise
  outstanding: Paise
  totalReceived: Paise
  /** Receipts from the client not adjusted against any bill (advances / on-account). */
  unadjusted: Paise
  lastReceiptDate: ISODate | null
}

export function clientPositions(snap: FeeSnap, range?: { from: ISODate; to: ISODate }): Map<string, ClientPosition> {
  const map = new Map<string, ClientPosition>()
  const get = (id: string) => {
    let p = map.get(id)
    if (!p) {
      p = { clientId: id, billed: 0, allocated: 0, outstanding: 0, totalReceived: 0, unadjusted: 0, lastReceiptDate: null }
      map.set(id, p)
    }
    return p
  }
  for (const pos of billPositions(snap)) {
    if (pos.status === 'cancelled') continue
    const p = get(pos.bill.client_id)
    p.billed += pos.bill.amount_paise
    p.allocated += pos.received
    p.outstanding += Math.max(0, pos.outstanding)
  }
  const allocByTxn = new Map<string, Paise>()
  for (const a of snap.fee_allocations) allocByTxn.set(a.transaction_id, (allocByTxn.get(a.transaction_id) ?? 0) + a.amount_paise)
  for (const t of snap.transactions) {
    if (t.type !== 'income' || t.status !== 'active' || !t.client_id) continue
    if (range && (t.txn_date < range.from || t.txn_date > range.to)) continue
    const p = get(t.client_id)
    p.totalReceived += t.amount_paise
    p.unadjusted += t.amount_paise - (allocByTxn.get(t.id) ?? 0)
    if (!p.lastReceiptDate || t.txn_date > p.lastReceiptDate) p.lastReceiptDate = t.txn_date
  }
  return map
}

/** Suggest allocating a receipt to the client's oldest open bills first. */
export function suggestAllocations(
  snap: FeeSnap,
  clientId: string,
  amount: Paise,
  excludeTxnId?: string,
): { fee_bill_id: string; amount_paise: Paise }[] {
  const open = snap.fee_bills
    .filter((b) => b.client_id === clientId && b.status === 'active')
    .sort((a, b) => (a.bill_date < b.bill_date ? -1 : a.bill_date > b.bill_date ? 1 : a.bill_no.localeCompare(b.bill_no)))
  const out: { fee_bill_id: string; amount_paise: Paise }[] = []
  let left = amount
  for (const b of open) {
    if (left <= 0) break
    const os = billOutstanding(snap, b.id, excludeTxnId)
    if (os <= 0) continue
    const take = Math.min(os, left)
    out.push({ fee_bill_id: b.id, amount_paise: take })
    left -= take
  }
  return out
}

export function txnAllocations(snap: Pick<DataSnapshot, 'fee_allocations'>, txn: Transaction) {
  return snap.fee_allocations.filter((a) => a.transaction_id === txn.id)
}
