import { formatDate, isValidISODate } from '../dates'
import { formatINR, type Paise } from '../money'
import { accountKindsForMethod, type DataSnapshot, type FeeAllocation, type OpeningBalance, type Transaction } from '../types'
import { billOutstanding } from './fees'
import { effectiveOpening, firstNegativeDay } from './ledger'

export type FieldErrors = Record<string, string>

export interface AllocationDraft {
  fee_bill_id: string
  amount_paise: Paise
}

function booksLocked(snap: DataSnapshot, date: string): boolean {
  const lock = snap.profile?.settings?.books_locked_until
  return !!lock && date <= lock
}

/** Replace/insert transaction(s) into a copy of the snapshot for "what-if" checks. */
export function withTransactions(snap: DataSnapshot, changed: Transaction[]): DataSnapshot {
  const ids = new Set(changed.map((t) => t.id))
  return { ...snap, transactions: [...snap.transactions.filter((t) => !ids.has(t.id)), ...changed] }
}

function cashAccountsTouched(snap: DataSnapshot, txns: (Transaction | undefined)[]): string[] {
  const cash = new Set(snap.accounts.filter((a) => a.kind === 'cash').map((a) => a.id))
  const out = new Set<string>()
  for (const t of txns) {
    if (!t) continue
    if (cash.has(t.account_id)) out.add(t.account_id)
    if (t.to_account_id && cash.has(t.to_account_id)) out.add(t.to_account_id)
  }
  return [...out]
}

/** Returns an error message if the change would make any cash account's end-of-day balance negative. */
export function cashShortfall(before: DataSnapshot, after: DataSnapshot, touched: (Transaction | undefined)[]): string | null {
  for (const accountId of cashAccountsTouched(before, touched)) {
    const neg = firstNegativeDay(after, accountId)
    if (!neg) continue
    // Do not block a change if the account was already short on an earlier day
    // and this change does not make things worse.
    const prior = firstNegativeDay(before, accountId)
    if (prior && prior.date < neg.date) continue
    if (prior && prior.date === neg.date && prior.balance <= neg.balance) continue
    const name = before.accounts.find((a) => a.id === accountId)?.name ?? 'Cash'
    return `Insufficient cash: ${name} balance would become ${formatINR(neg.balance)} on ${formatDate(neg.date)}. Record the receipt or a Bank-to-Cash contra first, or correct the opening balance.`
  }
  return null
}

export function validateTransaction(
  snap: DataSnapshot,
  draft: Transaction,
  allocations: AllocationDraft[] = [],
): FieldErrors {
  const e: FieldErrors = {}
  const existing = snap.transactions.find((t) => t.id === draft.id)

  if (!isValidISODate(draft.txn_date)) e.txn_date = 'Enter a valid date'
  else if (booksLocked(snap, draft.txn_date)) e.txn_date = `Books are locked up to ${formatDate(snap.profile!.settings.books_locked_until)}`
  if (existing && booksLocked(snap, existing.txn_date)) e.txn_date = 'This entry is in a locked period and cannot be changed'

  if (!Number.isSafeInteger(draft.amount_paise) || draft.amount_paise <= 0) e.amount = 'Amount must be greater than zero'
  else if (draft.amount_paise > 100_000_000_000) e.amount = 'Amount looks too large – please check'

  const account = snap.accounts.find((a) => a.id === draft.account_id)
  if (!account) e.account_id = 'Select an account'
  else if (!account.is_active && existing?.account_id !== account.id) e.account_id = 'This account is inactive'

  for (const id of [draft.account_id, draft.type === 'contra' ? draft.to_account_id : null]) {
    if (!id || e.txn_date) continue
    const ob = effectiveOpening(snap.opening_balances, id)
    if (ob.as_of_date && draft.txn_date < ob.as_of_date) {
      e.txn_date = `Date is before the opening balance date of ${snap.accounts.find((a) => a.id === id)?.name ?? 'the account'} (${formatDate(ob.as_of_date)})`
    }
  }

  if (draft.type === 'contra') {
    const to = snap.accounts.find((a) => a.id === draft.to_account_id)
    if (!to) e.to_account_id = 'Select the destination account'
    else if (to.id === draft.account_id) e.to_account_id = 'From and To accounts must be different'
    if (draft.client_id || draft.category_id) e.type = 'A contra entry cannot have a client or category'
  } else {
    if (account && !accountKindsForMethod(draft.payment_method).includes(account.kind)) {
      e.account_id = draft.payment_method === 'cash'
        ? 'Cash payments must use a Cash account'
        : 'Non-cash payments must use a Bank or UPI account, not Cash in Hand'
    }
    const cat = snap.categories.find((c) => c.id === draft.category_id)
    if (!cat) e.category_id = draft.type === 'income' ? 'Select the service / income category' : 'Select an expense category'
    else if (cat.kind !== draft.type) e.category_id = 'Category does not match entry type'
    if (draft.type === 'income' && draft.client_id && !snap.clients.some((c) => c.id === draft.client_id)) {
      e.client_id = 'Unknown client'
    }
    if (draft.type === 'expense' && !draft.party.trim()) e.party = 'Enter who was paid'
    if (draft.type === 'income' && !draft.client_id && !draft.party.trim()) e.client_id = 'Select a client or enter the payer name'
  }

  // Fee allocations (income only)
  const allocTotal = allocations.reduce((s, a) => s + a.amount_paise, 0)
  if (allocations.length && draft.type !== 'income') e.allocations = 'Only receipts can be adjusted against fee bills'
  if (allocTotal > draft.amount_paise) e.allocations = 'Adjusted amount exceeds the amount received'
  for (const a of allocations) {
    if (!Number.isSafeInteger(a.amount_paise) || a.amount_paise < 0) e.allocations = 'Invalid adjustment amount'
    const bill = snap.fee_bills.find((b) => b.id === a.fee_bill_id)
    if (!bill) { e.allocations = 'Unknown fee bill'; continue }
    if (bill.client_id !== draft.client_id) e.allocations = 'Fee bill belongs to a different client'
    if (a.amount_paise > 0 && bill.status === 'cancelled') e.allocations = `Bill ${bill.bill_no} is cancelled`
    const os = billOutstanding(snap, bill.id, draft.id)
    if (a.amount_paise > os) e.allocations = `Bill ${bill.bill_no} has only ${formatINR(Math.max(0, os))} outstanding`
  }

  if (Object.keys(e).length === 0 && draft.status === 'active') {
    const after = withTransactions(snap, [draft])
    const msg = cashShortfall(snap, after, [existing, draft])
    if (msg) e.amount = msg
  }
  return e
}

export function validateCancellation(snap: DataSnapshot, txn: Transaction, reason: string): string | null {
  if (txn.status === 'cancelled') return 'Entry is already cancelled'
  if (!reason.trim()) return 'Enter a reason for cancellation'
  if (booksLocked(snap, txn.txn_date)) return 'This entry is in a locked period and cannot be cancelled'
  const cancelled = { ...txn, status: 'cancelled' as const }
  return cashShortfall(snap, withTransactions(snap, [cancelled]), [txn])
}

/**
 * Opening balance changes are allowed (they are the authorised way to correct
 * cash), but the caller must show the returned warning and obtain explicit
 * confirmation if the change makes the cash book go negative.
 */
export function openingBalanceWarning(snap: DataSnapshot, next: OpeningBalance): string | null {
  const account = snap.accounts.find((a) => a.id === next.account_id)
  if (!account || account.kind !== 'cash') return null
  const after = { ...snap, opening_balances: [...snap.opening_balances, next] }
  const neg = firstNegativeDay(after, account.id)
  if (!neg) return null
  return `With this opening balance, ${account.name} would show ${formatINR(neg.balance)} on ${formatDate(neg.date)}.`
}

export function validateOpeningBalance(snap: DataSnapshot, ob: Pick<OpeningBalance, 'account_id' | 'as_of_date' | 'amount_paise' | 'reason'>): FieldErrors {
  const e: FieldErrors = {}
  if (!snap.accounts.some((a) => a.id === ob.account_id)) e.account_id = 'Select an account'
  if (!isValidISODate(ob.as_of_date)) e.as_of_date = 'Enter a valid date'
  if (!Number.isSafeInteger(ob.amount_paise)) e.amount = 'Enter a valid amount'
  const account = snap.accounts.find((a) => a.id === ob.account_id)
  if (account?.kind === 'cash' && ob.amount_paise < 0) e.amount = 'Cash in hand cannot be negative'
  const prev = effectiveOpening(snap.opening_balances, ob.account_id)
  if (prev.record && !ob.reason.trim()) e.reason = 'Give a reason for correcting the opening balance'
  const earliest = snap.transactions
    .filter((t) => t.status === 'active' && (t.account_id === ob.account_id || t.to_account_id === ob.account_id))
    .reduce<string | null>((m, t) => (!m || t.txn_date < m ? t.txn_date : m), null)
  if (earliest && isValidISODate(ob.as_of_date) && ob.as_of_date > earliest) {
    e.as_of_date = `Opening date must be on or before the first entry (${formatDate(earliest)})`
  }
  return e
}

/** Potential duplicate: same type, date, amount and party/client within the last few entries. */
export function findLikelyDuplicate(snap: DataSnapshot, draft: Transaction): Transaction | null {
  return (
    snap.transactions.find(
      (t) =>
        t.id !== draft.id &&
        t.status === 'active' &&
        t.type === draft.type &&
        t.txn_date === draft.txn_date &&
        t.amount_paise === draft.amount_paise &&
        t.account_id === draft.account_id &&
        (t.client_id ?? '') === (draft.client_id ?? '') &&
        t.party.trim().toLowerCase() === draft.party.trim().toLowerCase() &&
        (t.reference_no || '') === (draft.reference_no || ''),
    ) ?? null
  )
}

export function activeAllocations(allocs: FeeAllocation[]): FeeAllocation[] {
  return allocs.filter((a) => a.amount_paise > 0)
}
