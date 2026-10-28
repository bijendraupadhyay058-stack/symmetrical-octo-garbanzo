import type { DateRange, ISODate } from '../dates'
import { addDays } from '../dates'
import type { Paise } from '../money'
import type { Account, DataSnapshot, OpeningBalance, Transaction } from '../types'

export interface Lookups {
  account: (id: string | null | undefined) => Account | undefined
  accountName: (id: string | null | undefined) => string
  categoryName: (id: string | null | undefined) => string
  clientName: (id: string | null | undefined) => string
}

export function buildLookups(snap: Pick<DataSnapshot, 'accounts' | 'categories' | 'clients'>): Lookups {
  const acc = new Map(snap.accounts.map((a) => [a.id, a]))
  const cat = new Map(snap.categories.map((c) => [c.id, c.name]))
  const cli = new Map(snap.clients.map((c) => [c.id, c.name]))
  return {
    account: (id) => (id ? acc.get(id) : undefined),
    accountName: (id) => (id ? acc.get(id)?.name ?? 'Unknown account' : ''),
    categoryName: (id) => (id ? cat.get(id) ?? 'Uncategorised' : 'Uncategorised'),
    clientName: (id) => (id ? cli.get(id) ?? '' : ''),
  }
}

/** Deterministic posting order: date, then entry time, then voucher number. */
export function compareTxns(a: Transaction, b: Transaction): number {
  if (a.txn_date !== b.txn_date) return a.txn_date < b.txn_date ? -1 : 1
  if (a.created_at !== b.created_at) return a.created_at < b.created_at ? -1 : 1
  return a.voucher_no.localeCompare(b.voucher_no)
}

export function activeTxns(txns: Transaction[]): Transaction[] {
  return txns.filter((t) => t.status === 'active')
}

/** The opening balance currently in force (latest correction wins). */
export function effectiveOpening(
  openings: OpeningBalance[],
  accountId: string,
): { amount: Paise; as_of_date: ISODate | null; record: OpeningBalance | null } {
  let best: OpeningBalance | null = null
  for (const o of openings) {
    if (o.account_id !== accountId) continue
    if (!best || o.created_at > best.created_at) best = o
  }
  return { amount: best?.amount_paise ?? 0, as_of_date: best?.as_of_date ?? null, record: best }
}

export interface Movement {
  txn: Transaction
  accountId: string
  receipt: Paise
  payment: Paise
}

/** How a transaction affects one account (zero/absent if it does not touch it). */
export function movementFor(t: Transaction, accountId: string): { receipt: Paise; payment: Paise } | null {
  if (t.status !== 'active') return null
  if (t.type === 'income' && t.account_id === accountId) return { receipt: t.amount_paise, payment: 0 }
  if (t.type === 'expense' && t.account_id === accountId) return { receipt: 0, payment: t.amount_paise }
  if (t.type === 'contra') {
    if (t.account_id === accountId) return { receipt: 0, payment: t.amount_paise }
    if (t.to_account_id === accountId) return { receipt: t.amount_paise, payment: 0 }
  }
  return null
}

export function movements(txns: Transaction[], accountIds: string[]): Movement[] {
  const out: Movement[] = []
  const sorted = [...txns].sort(compareTxns)
  for (const t of sorted) {
    for (const id of accountIds) {
      const m = movementFor(t, id)
      if (m) out.push({ txn: t, accountId: id, ...m })
    }
  }
  return out
}

/** Balance of the given accounts at the end of `date` (inclusive). */
export function balanceAsOf(
  snap: Pick<DataSnapshot, 'transactions' | 'opening_balances'>,
  accountIds: string[],
  date: ISODate,
): Paise {
  let bal = 0
  for (const id of accountIds) bal += effectiveOpening(snap.opening_balances, id).amount
  for (const t of snap.transactions) {
    if (t.txn_date > date) continue
    for (const id of accountIds) {
      const m = movementFor(t, id)
      if (m) bal += m.receipt - m.payment
    }
  }
  return bal
}

export function particularsFor(t: Transaction, lk: Lookups, perspectiveAccountId?: string): string {
  if (t.type === 'contra') {
    const from = lk.accountName(t.account_id)
    const to = lk.accountName(t.to_account_id)
    if (perspectiveAccountId === t.to_account_id) return `Contra: received from ${from}`
    if (perspectiveAccountId === t.account_id) return `Contra: transferred to ${to}`
    return `Contra: ${from} → ${to}`
  }
  const cat = lk.categoryName(t.category_id)
  const who = t.type === 'income' ? lk.clientName(t.client_id) || t.party : t.party
  return [cat, who].filter(Boolean).join(' – ')
}

export interface LedgerRow {
  kind: 'opening' | 'entry' | 'closing'
  date: ISODate
  voucher_no: string
  particulars: string
  narration: string
  receipt: Paise
  payment: Paise
  balance: Paise
  txn?: Transaction
  accountId?: string
}

export interface Ledger {
  accountIds: string[]
  range: DateRange
  opening: Paise
  rows: LedgerRow[]
  totalReceipts: Paise
  totalPayments: Paise
  closing: Paise
}

/**
 * Cash Book / Bank Book for one or more accounts within a date range.
 * Opening for the range = opening balance + every movement before `range.from`,
 * so back-dated entries automatically flow into every later balance.
 * Closing = Opening + Receipts − Payments, always.
 */
export function buildLedger(
  snap: Pick<DataSnapshot, 'transactions' | 'opening_balances' | 'accounts' | 'categories' | 'clients'>,
  accountIds: string[],
  range: DateRange,
  lk: Lookups = buildLookups(snap),
): Ledger {
  const opening = balanceAsOf(snap, accountIds, addDays(range.from, -1))
  const rows: LedgerRow[] = [
    {
      kind: 'opening', date: range.from, voucher_no: 'Opening', particulars: 'Opening Balance', narration: '',
      receipt: opening > 0 ? opening : 0, payment: opening < 0 ? -opening : 0, balance: opening,
    },
  ]
  let bal = opening
  let totalReceipts = 0
  let totalPayments = 0
  const inRange = snap.transactions.filter((t) => t.txn_date >= range.from && t.txn_date <= range.to)
  for (const m of movements(inRange, accountIds)) {
    bal += m.receipt - m.payment
    totalReceipts += m.receipt
    totalPayments += m.payment
    rows.push({
      kind: 'entry',
      date: m.txn.txn_date,
      voucher_no: m.txn.voucher_no,
      particulars: particularsFor(m.txn, lk, m.accountId),
      narration: m.txn.narration,
      receipt: m.receipt,
      payment: m.payment,
      balance: bal,
      txn: m.txn,
      accountId: m.accountId,
    })
  }
  const closing = opening + totalReceipts - totalPayments
  rows.push({
    kind: 'closing', date: range.to, voucher_no: '', particulars: 'Closing Balance', narration: '',
    receipt: 0, payment: 0, balance: closing,
  })
  return { accountIds, range, opening, rows, totalReceipts, totalPayments, closing }
}

/**
 * First date on which the end-of-day balance of an account goes below zero,
 * considering every active entry. Used to stop cash payments that exceed the
 * cash available (including when a back-dated change would cause it later).
 */
export function firstNegativeDay(
  snap: Pick<DataSnapshot, 'transactions' | 'opening_balances'>,
  accountId: string,
): { date: ISODate; balance: Paise } | null {
  const opening = effectiveOpening(snap.opening_balances, accountId)
  const byDate = new Map<ISODate, Paise>()
  for (const t of snap.transactions) {
    const m = movementFor(t, accountId)
    if (!m) continue
    byDate.set(t.txn_date, (byDate.get(t.txn_date) ?? 0) + m.receipt - m.payment)
  }
  let bal = opening.amount
  if (bal < 0) return { date: opening.as_of_date ?? '0000-00-00', balance: bal }
  for (const date of [...byDate.keys()].sort()) {
    bal += byDate.get(date)!
    if (bal < 0) return { date, balance: bal }
  }
  return null
}

export function accountIdsOfKind(accounts: Account[], kinds: Account['kind'][]): string[] {
  return accounts.filter((a) => kinds.includes(a.kind)).map((a) => a.id)
}
