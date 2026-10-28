import { billOutstanding } from '../accounting/fees'
import { effectiveOpening } from '../accounting/ledger'
import {
  validateCancellation,
  validateOpeningBalance,
  validateTransaction,
  withTransactions,
  cashShortfall,
  type AllocationDraft,
  type FieldErrors,
} from '../accounting/validation'
import { nextVoucherNo, voucherMatches, voucherPrefix } from '../accounting/vouchers'
import { addMonths, formatDate, fyOf, fyShort, todayIST, type ISODate } from '../dates'
import { nowISO, uuid } from '../ids'
import { formatINR, type Paise } from '../money'
import {
  DEFAULT_EXPENSE_CATEGORIES,
  DEFAULT_INCOME_CATEGORIES,
  DEFAULT_SETTINGS,
  type Account,
  type AccountKind,
  type Attachment,
  type AuditAction,
  type AuditLog,
  type BaseRecord,
  type BusinessProfile,
  type Category,
  type CategoryKind,
  type Client,
  type FeeAllocation,
  type FeeBill,
  type OpeningBalance,
  type RecurringTemplate,
  type TableName,
  type Transaction,
} from '../types'
import type { Change, LocalStore } from './store'

export type Result<T> = { ok: true; value: T; warning?: string } | { ok: false; errors: FieldErrors }

export function base(businessId: string, id: string = uuid()): BaseRecord {
  const now = nowISO()
  return { id, business_id: businessId, created_at: now, updated_at: now, version: 0 }
}

function stripMeta<T extends object>(r: T | undefined | null): unknown {
  if (!r) return null
  const { _sync, ...rest } = r as T & { _sync?: unknown }
  void _sync
  return rest
}

export function auditRecord(
  businessId: string,
  entity: TableName,
  entity_id: string,
  action: AuditAction,
  summary: string,
  before: unknown,
  after: unknown,
): AuditLog {
  return {
    ...base(businessId),
    entity,
    entity_id,
    action,
    summary,
    before_data: stripMeta(before as object),
    after_data: stripMeta(after as object),
    source: 'app',
  }
}

/* ------------------------------------------------------------------ business */

export function defaultBusinessRecords(businessId: string, name: string, ownerId: string | null): Change[] {
  const profile: BusinessProfile = {
    ...base(businessId, businessId),
    owner_id: ownerId,
    name,
    tagline: 'Accounting · GST · TDS · Income Tax · Audit',
    address: '',
    phone: '',
    email: '',
    gstin: '',
    pan: '',
    logo_data_url: null,
    settings: { ...DEFAULT_SETTINGS },
  }
  const accounts: Account[] = [
    { ...base(businessId), name: 'Cash in Hand', kind: 'cash', details: '', is_active: true, sort_order: 1 },
    { ...base(businessId), name: 'Bank Account', kind: 'bank', details: '', is_active: true, sort_order: 2 },
    { ...base(businessId), name: 'UPI Collections', kind: 'upi', details: '', is_active: true, sort_order: 3 },
  ]
  const cats: Category[] = [
    ...DEFAULT_INCOME_CATEGORIES.map((n, i) => ({ ...base(businessId), kind: 'income' as const, name: n, is_active: true, sort_order: i + 1 })),
    ...DEFAULT_EXPENSE_CATEGORIES.map((n, i) => ({ ...base(businessId), kind: 'expense' as const, name: n, is_active: true, sort_order: i + 1 })),
  ]
  return [
    { table: 'business_profiles', record: profile },
    ...accounts.map((a) => ({ table: 'accounts' as const, record: a })),
    ...cats.map((c) => ({ table: 'categories' as const, record: c })),
  ]
}

export async function saveProfile(store: LocalStore, next: BusinessProfile) {
  const before = store.getSnapshot().profile
  await store.save([
    { table: 'business_profiles', record: next },
    { table: 'audit_logs', record: auditRecord(store.businessId, 'business_profiles', next.id, 'update', 'Business profile updated', before, next) },
  ])
}

/* -------------------------------------------------------------- transactions */

export function newTransactionDraft(store: LocalStore, type: Transaction['type']): Transaction {
  const snap = store.getSnapshot()
  const cash = snap.accounts.find((a) => a.kind === 'cash' && a.is_active)
  const bank = snap.accounts.find((a) => a.kind !== 'cash' && a.is_active)
  return {
    ...base(store.businessId),
    type,
    voucher_no: '',
    txn_date: todayIST(),
    amount_paise: 0,
    payment_method: type === 'contra' ? 'other' : 'cash',
    account_id: cash?.id ?? '',
    to_account_id: type === 'contra' ? bank?.id ?? null : null,
    category_id: null,
    client_id: null,
    party: '',
    service: '',
    narration: '',
    reference_no: '',
    status: 'active',
    cancel_reason: '',
    cancelled_at: null,
    recurring_template_id: null,
  }
}

function assignVoucher(store: LocalStore, draft: Transaction, existing: Transaction | undefined): string {
  const snap = store.getSnapshot()
  const kind = snap.accounts.find((a) => a.id === draft.account_id)?.kind
  const prefix = voucherPrefix(draft.type, kind)
  if (existing && voucherMatches(existing.voucher_no, prefix, draft.txn_date)) return existing.voucher_no
  return nextVoucherNo(snap.transactions.map((t) => t.voucher_no), prefix, draft.txn_date)
}

function describeTxn(store: LocalStore, t: Transaction): string {
  const kind = t.type === 'income' ? 'Receipt' : t.type === 'expense' ? 'Payment' : 'Contra'
  return `${kind} ${t.voucher_no} ${formatINR(t.amount_paise)} dated ${formatDate(t.txn_date)}`
}

export async function saveTransaction(
  store: LocalStore,
  draft: Transaction,
  allocations: AllocationDraft[] = [],
): Promise<Result<Transaction>> {
  const snap = store.getSnapshot()
  const existing = snap.transactions.find((t) => t.id === draft.id)
  if (existing?.status === 'cancelled') return { ok: false, errors: { form: 'Cancelled entries cannot be edited' } }
  const clean: Transaction = {
    ...draft,
    party: draft.party.trim(),
    narration: draft.narration.trim(),
    reference_no: draft.reference_no.trim(),
    service: draft.service.trim(),
    to_account_id: draft.type === 'contra' ? draft.to_account_id : null,
    category_id: draft.type === 'contra' ? null : draft.category_id,
    client_id: draft.type === 'income' ? draft.client_id : null,
    status: 'active',
  }
  const allocs = clean.type === 'income' && clean.client_id ? allocations.filter((a) => a.amount_paise > 0) : []
  const errors = validateTransaction(snap, clean, allocs)
  if (Object.keys(errors).length) return { ok: false, errors }

  clean.voucher_no = assignVoucher(store, clean, existing)
  if (existing) {
    clean.created_at = existing.created_at
    clean.version = existing.version
  }

  const changes: Change[] = [{ table: 'transactions', record: clean }]

  // Fee allocations: update in place; ones no longer wanted are set to zero (never deleted).
  const current = snap.fee_allocations.filter((a) => a.transaction_id === clean.id)
  const byBill = new Map(current.map((a) => [a.fee_bill_id, a]))
  const wanted = new Map(allocs.map((a) => [a.fee_bill_id, a.amount_paise]))
  for (const [billId, amount] of wanted) {
    const prev = byBill.get(billId)
    if (prev && prev.amount_paise === amount) continue
    const rec: FeeAllocation = prev
      ? { ...prev, amount_paise: amount }
      : { ...base(store.businessId), fee_bill_id: billId, transaction_id: clean.id, amount_paise: amount }
    changes.push({ table: 'fee_allocations', record: rec })
  }
  for (const prev of current) {
    if (!wanted.has(prev.fee_bill_id) && prev.amount_paise !== 0) {
      changes.push({ table: 'fee_allocations', record: { ...prev, amount_paise: 0 } })
    }
  }

  // Posting from a recurring template moves the template to its next due date.
  if (!existing && clean.recurring_template_id) {
    const tpl = snap.recurring_templates.find((t) => t.id === clean.recurring_template_id)
    if (tpl) changes.push({ table: 'recurring_templates', record: { ...tpl, next_due_date: nextDueAfter(tpl, clean.txn_date) } })
  }

  let summary = (existing ? 'Edited ' : 'Created ') + describeTxn(store, clean)
  if (existing && existing.voucher_no !== clean.voucher_no) summary += ` (voucher renumbered from ${existing.voucher_no})`
  changes.push({
    table: 'audit_logs',
    record: auditRecord(store.businessId, 'transactions', clean.id, existing ? 'update' : 'create', summary, existing, clean),
  })
  await store.save(changes)
  return { ok: true, value: clean }
}

export async function cancelTransaction(store: LocalStore, id: string, reason: string): Promise<Result<Transaction>> {
  const snap = store.getSnapshot()
  const txn = snap.transactions.find((t) => t.id === id)
  if (!txn) return { ok: false, errors: { form: 'Entry not found' } }
  const err = validateCancellation(snap, txn, reason)
  if (err) return { ok: false, errors: { form: err } }
  const next: Transaction = { ...txn, status: 'cancelled', cancel_reason: reason.trim(), cancelled_at: nowISO() }
  await store.save([
    { table: 'transactions', record: next },
    {
      table: 'audit_logs',
      record: auditRecord(store.businessId, 'transactions', id, 'cancel', `Cancelled ${describeTxn(store, txn)} – ${reason.trim()}`, txn, next),
    },
  ])
  return { ok: true, value: next }
}

export async function restoreTransaction(store: LocalStore, id: string): Promise<Result<Transaction>> {
  const snap = store.getSnapshot()
  const txn = snap.transactions.find((t) => t.id === id)
  if (!txn || txn.status !== 'cancelled') return { ok: false, errors: { form: 'Entry is not cancelled' } }
  const next: Transaction = { ...txn, status: 'active', cancel_reason: '', cancelled_at: null }
  const allocs = snap.fee_allocations.filter((a) => a.transaction_id === id && a.amount_paise > 0)
  const errors = validateTransaction(snap, next, allocs)
  if (Object.keys(errors).length) return { ok: false, errors }
  await store.save([
    { table: 'transactions', record: next },
    { table: 'audit_logs', record: auditRecord(store.businessId, 'transactions', id, 'restore', `Reinstated ${describeTxn(store, txn)}`, txn, next) },
  ])
  return { ok: true, value: next }
}

/* ------------------------------------------------------------------- masters */

export function nextClientCode(store: LocalStore): string {
  let max = 0
  for (const c of store.getSnapshot().clients) {
    const m = /^C-(\d+)$/.exec(c.code)
    if (m) max = Math.max(max, Number(m[1]))
  }
  return `C-${String(max + 1).padStart(4, '0')}`
}

export function newClient(store: LocalStore, name = ''): Client {
  return {
    ...base(store.businessId),
    code: nextClientCode(store),
    name,
    firm_name: '',
    mobile: '',
    email: '',
    gstin: '',
    pan: '',
    service_type: '',
    notes: '',
    is_active: true,
  }
}

export function validateClient(store: LocalStore, c: Client): FieldErrors {
  const e: FieldErrors = {}
  if (!c.name.trim()) e.name = 'Client name is required'
  if (c.mobile && !/^(\+?91[\s-]?)?[6-9]\d{9}$/.test(c.mobile.replace(/\s/g, ''))) e.mobile = 'Enter a valid 10-digit Indian mobile number'
  if (c.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(c.email)) e.email = 'Enter a valid email'
  if (c.gstin && !/^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/.test(c.gstin.toUpperCase())) e.gstin = 'GSTIN format looks wrong'
  if (c.pan && !/^[A-Z]{5}\d{4}[A-Z]$/.test(c.pan.toUpperCase())) e.pan = 'PAN format looks wrong (e.g. ABCDE1234F)'
  const dup = store.getSnapshot().clients.find(
    (x) => x.id !== c.id && x.name.trim().toLowerCase() === c.name.trim().toLowerCase() && (x.mobile || '') === (c.mobile || ''),
  )
  if (dup) e.name = `A client with this name already exists (${dup.code})`
  return e
}

export async function saveClient(store: LocalStore, c: Client): Promise<Result<Client>> {
  const errors = validateClient(store, c)
  if (Object.keys(errors).length) return { ok: false, errors }
  const before = store.get('clients', c.id)
  const rec: Client = { ...c, name: c.name.trim(), gstin: c.gstin.toUpperCase().trim(), pan: c.pan.toUpperCase().trim() }
  await store.save([
    { table: 'clients', record: rec },
    { table: 'audit_logs', record: auditRecord(store.businessId, 'clients', c.id, before ? 'update' : 'create', `${before ? 'Updated' : 'Added'} client ${rec.name} (${rec.code})`, before, rec) },
  ])
  return { ok: true, value: rec }
}

export async function saveCategory(store: LocalStore, kind: CategoryKind, name: string, existing?: Category, isActive = true): Promise<Result<Category>> {
  const n = name.trim()
  if (!n) return { ok: false, errors: { name: 'Name is required' } }
  const dup = store.getSnapshot().categories.find((c) => c.kind === kind && c.id !== existing?.id && c.name.toLowerCase() === n.toLowerCase())
  if (dup) return { ok: false, errors: { name: 'A category with this name already exists' } }
  const maxOrder = Math.max(0, ...store.getSnapshot().categories.filter((c) => c.kind === kind).map((c) => c.sort_order))
  const rec: Category = existing
    ? { ...existing, name: n, is_active: isActive }
    : { ...base(store.businessId), kind, name: n, is_active: true, sort_order: maxOrder + 1 }
  await store.save([
    { table: 'categories', record: rec },
    { table: 'audit_logs', record: auditRecord(store.businessId, 'categories', rec.id, existing ? 'update' : 'create', `${existing ? 'Updated' : 'Added'} ${kind} category "${n}"`, existing, rec) },
  ])
  return { ok: true, value: rec }
}

export async function saveAccount(store: LocalStore, acc: Account): Promise<Result<Account>> {
  if (!acc.name.trim()) return { ok: false, errors: { name: 'Name is required' } }
  const before = store.get('accounts', acc.id)
  if (before && before.kind !== acc.kind) {
    const used = store.getSnapshot().transactions.some((t) => t.account_id === acc.id || t.to_account_id === acc.id)
    if (used) return { ok: false, errors: { kind: 'Account type cannot change after entries are posted to it' } }
  }
  const rec = { ...acc, name: acc.name.trim() }
  await store.save([
    { table: 'accounts', record: rec },
    { table: 'audit_logs', record: auditRecord(store.businessId, 'accounts', acc.id, before ? 'update' : 'create', `${before ? 'Updated' : 'Added'} account ${rec.name}`, before, rec) },
  ])
  return { ok: true, value: rec }
}

export function newAccount(store: LocalStore, kind: AccountKind): Account {
  const max = Math.max(0, ...store.getSnapshot().accounts.map((a) => a.sort_order))
  return { ...base(store.businessId), name: '', kind, details: '', is_active: true, sort_order: max + 1 }
}

/**
 * Opening balances are never edited in place: each correction is a new record
 * (the latest one is effective) so the history is preserved and audited.
 */
export async function setOpeningBalance(
  store: LocalStore,
  input: { account_id: string; as_of_date: ISODate; amount_paise: Paise; reason: string },
): Promise<Result<OpeningBalance>> {
  const snap = store.getSnapshot()
  const errors = validateOpeningBalance(snap, input)
  if (Object.keys(errors).length) return { ok: false, errors }
  const prev = effectiveOpening(snap.opening_balances, input.account_id)
  const rec: OpeningBalance = { ...base(store.businessId), ...input, reason: input.reason.trim() }
  const acc = snap.accounts.find((a) => a.id === input.account_id)!
  const summary = prev.record
    ? `Opening balance of ${acc.name} corrected from ${formatINR(prev.amount)} to ${formatINR(rec.amount_paise)} – ${rec.reason}`
    : `Opening balance of ${acc.name} set to ${formatINR(rec.amount_paise)} as on ${formatDate(rec.as_of_date)}`
  await store.save([
    { table: 'opening_balances', record: rec },
    { table: 'audit_logs', record: auditRecord(store.businessId, 'opening_balances', rec.id, 'opening_balance', summary, prev.record, rec) },
  ])
  return { ok: true, value: rec }
}

/* ------------------------------------------------------------------ fee bills */

export function nextBillNo(store: LocalStore, date: ISODate): string {
  const fy = fyShort(fyOf(date))
  let max = 0
  for (const b of store.getSnapshot().fee_bills) {
    const m = /^FB\/(\d{2}-\d{2})\/(\d+)$/.exec(b.bill_no)
    if (m && m[1] === fy) max = Math.max(max, Number(m[2]))
  }
  return `FB/${fy}/${String(max + 1).padStart(3, '0')}`
}

export function newFeeBill(store: LocalStore, clientId = ''): FeeBill {
  return {
    ...base(store.businessId),
    bill_no: '',
    bill_date: todayIST(),
    due_date: null,
    client_id: clientId,
    category_id: null,
    service: '',
    amount_paise: 0,
    narration: '',
    status: 'active',
    cancel_reason: '',
    last_reminded_at: null,
  }
}

export async function saveFeeBill(store: LocalStore, bill: FeeBill): Promise<Result<FeeBill>> {
  const snap = store.getSnapshot()
  const e: FieldErrors = {}
  const before = snap.fee_bills.find((b) => b.id === bill.id)
  if (!snap.clients.some((c) => c.id === bill.client_id)) e.client_id = 'Select a client'
  if (!Number.isSafeInteger(bill.amount_paise) || bill.amount_paise <= 0) e.amount = 'Fees charged must be greater than zero'
  if (!bill.category_id && !bill.service.trim()) e.service = 'Select or enter the service'
  if (bill.due_date && bill.due_date < bill.bill_date) e.due_date = 'Due date cannot be before bill date'
  if (before) {
    const received = before.amount_paise - billOutstanding(snap, before.id)
    if (bill.amount_paise < received) e.amount = `Already received ${formatINR(received)} against this bill`
    if (before.client_id !== bill.client_id && received > 0) e.client_id = 'Client cannot change after receipts are adjusted'
    if (before.status === 'cancelled') e.form = 'Cancelled bills cannot be edited'
  }
  if (Object.keys(e).length) return { ok: false, errors: e }
  const rec: FeeBill = {
    ...bill,
    service: bill.service.trim(),
    bill_no: before?.bill_no || nextBillNo(store, bill.bill_date),
    created_at: before?.created_at ?? bill.created_at,
    version: before?.version ?? bill.version,
  }
  await store.save([
    { table: 'fee_bills', record: rec },
    {
      table: 'audit_logs',
      record: auditRecord(store.businessId, 'fee_bills', rec.id, before ? 'update' : 'create', `${before ? 'Edited' : 'Raised'} fee bill ${rec.bill_no} for ${formatINR(rec.amount_paise)}`, before, rec),
    },
  ])
  return { ok: true, value: rec }
}

export async function cancelFeeBill(store: LocalStore, id: string, reason: string): Promise<Result<FeeBill>> {
  const snap = store.getSnapshot()
  const bill = snap.fee_bills.find((b) => b.id === id)
  if (!bill) return { ok: false, errors: { form: 'Bill not found' } }
  if (!reason.trim()) return { ok: false, errors: { form: 'Enter a reason' } }
  if (billOutstanding(snap, id) !== bill.amount_paise) {
    return { ok: false, errors: { form: 'Receipts are adjusted against this bill. Remove the adjustment from those receipts first.' } }
  }
  const next: FeeBill = { ...bill, status: 'cancelled', cancel_reason: reason.trim() }
  await store.save([
    { table: 'fee_bills', record: next },
    { table: 'audit_logs', record: auditRecord(store.businessId, 'fee_bills', id, 'cancel', `Cancelled fee bill ${bill.bill_no} – ${reason.trim()}`, bill, next) },
  ])
  return { ok: true, value: next }
}

export async function markReminded(store: LocalStore, billId: string) {
  const bill = store.get('fee_bills', billId)
  if (bill) await store.save([{ table: 'fee_bills', record: { ...bill, last_reminded_at: nowISO() } }])
}

/* ---------------------------------------------------------- recurring expenses */

export function nextDueAfter(tpl: Pick<RecurringTemplate, 'day_of_month' | 'next_due_date'>, postedDate: ISODate): ISODate {
  let d = tpl.next_due_date
  // Advance at least one month, and beyond the date just posted.
  do {
    d = withDay(addMonths(d.slice(0, 8) + '01', 1), tpl.day_of_month)
  } while (d <= postedDate)
  return d
}

function withDay(d: ISODate, day: number): ISODate {
  const [y, m] = d.split('-').map(Number)
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate()
  return `${y}-${String(m).padStart(2, '0')}-${String(Math.min(day, last)).padStart(2, '0')}`
}

export function newTemplate(store: LocalStore): RecurringTemplate {
  const snap = store.getSnapshot()
  const today = todayIST()
  return {
    ...base(store.businessId),
    name: '',
    party: '',
    category_id: null,
    amount_paise: 0,
    payment_method: 'cash',
    account_id: snap.accounts.find((a) => a.kind === 'cash')?.id ?? '',
    narration: '',
    day_of_month: Number(today.slice(8, 10)),
    next_due_date: today,
    is_active: true,
  }
}

export async function saveTemplate(store: LocalStore, tpl: RecurringTemplate): Promise<Result<RecurringTemplate>> {
  const e: FieldErrors = {}
  if (!tpl.name.trim()) e.name = 'Name is required'
  if (!tpl.category_id) e.category_id = 'Select a category'
  if (!(tpl.amount_paise > 0)) e.amount = 'Amount must be greater than zero'
  if (!(tpl.day_of_month >= 1 && tpl.day_of_month <= 31)) e.day_of_month = 'Day must be 1–31'
  if (!tpl.account_id) e.account_id = 'Select an account'
  if (Object.keys(e).length) return { ok: false, errors: e }
  const before = store.get('recurring_templates', tpl.id)
  await store.save([
    { table: 'recurring_templates', record: tpl },
    { table: 'audit_logs', record: auditRecord(store.businessId, 'recurring_templates', tpl.id, before ? 'update' : 'create', `${before ? 'Updated' : 'Added'} recurring template "${tpl.name}"`, before, tpl) },
  ])
  return { ok: true, value: tpl }
}

export function dueTemplates(store: LocalStore, today = todayIST()): RecurringTemplate[] {
  return store.getSnapshot().recurring_templates.filter((t) => t.is_active && t.next_due_date <= today)
}

/* ---------------------------------------------------------------- attachments */

export const MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024

export async function addAttachment(store: LocalStore, transactionId: string, file: Blob, fileName: string): Promise<Result<Attachment>> {
  const allowed = ['image/jpeg', 'image/png', 'image/webp', 'application/pdf']
  if (!allowed.includes(file.type)) return { ok: false, errors: { file: 'Only JPG, PNG, WEBP images or PDF files can be attached' } }
  if (file.size > MAX_ATTACHMENT_BYTES) return { ok: false, errors: { file: 'File is larger than 5 MB' } }
  const rec: Attachment = {
    ...base(store.businessId),
    transaction_id: transactionId,
    file_name: fileName.slice(0, 120),
    mime_type: file.type,
    size_bytes: file.size,
    storage_path: null,
  }
  await store.putBlob(rec.id, file, file.type)
  await store.save([
    { table: 'attachments', record: rec },
    { table: 'audit_logs', record: auditRecord(store.businessId, 'attachments', rec.id, 'create', `Attached ${rec.file_name}`, null, rec) },
  ])
  return { ok: true, value: rec }
}

/** Re-check a change (used by tests and the import tool). */
export function wouldMakeCashNegative(store: LocalStore, txn: Transaction): string | null {
  const snap = store.getSnapshot()
  return cashShortfall(snap, withTransactions(snap, [txn]), [snap.transactions.find((t) => t.id === txn.id), txn])
}
