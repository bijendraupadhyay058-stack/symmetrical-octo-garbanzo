import type { ISODate } from './dates'
import type { Paise } from './money'

/** Local-only sync bookkeeping kept alongside each record in IndexedDB. Never sent to the server. */
export interface SyncMeta {
  state: 'synced' | 'pending' | 'error'
  /** Local timestamp of the last unsynced change; pushes happen in this order. */
  changed_at: string
  error?: string
}

export interface BaseRecord {
  /** Client-generated UUID. Immutable; doubles as the idempotency key for sync. */
  id: string
  business_id: string
  created_at: string
  updated_at: string
  /** Server version for optimistic concurrency. 0 = never synced. */
  version: number
  _sync?: SyncMeta
}

export interface BusinessSettings {
  theme: 'light' | 'dark' | 'system'
  /** Minutes of inactivity before the app locks. 0 disables auto-lock. */
  auto_lock_minutes: number
  /** Entries dated on/before this date cannot be created, edited or cancelled. */
  books_locked_until: ISODate | null
  reminder_message: string
  receipt_footer: string
}

export interface BusinessProfile extends BaseRecord {
  owner_id: string | null
  name: string
  tagline: string
  address: string
  phone: string
  email: string
  gstin: string
  pan: string
  logo_data_url: string | null
  settings: BusinessSettings
}

export type AccountKind = 'cash' | 'bank' | 'upi'

export interface Account extends BaseRecord {
  name: string
  kind: AccountKind
  /** Optional bank details shown in reports. */
  details: string
  is_active: boolean
  sort_order: number
}

export interface OpeningBalance extends BaseRecord {
  account_id: string
  as_of_date: ISODate
  amount_paise: Paise
  reason: string
}

export type CategoryKind = 'income' | 'expense'

export interface Category extends BaseRecord {
  kind: CategoryKind
  name: string
  is_active: boolean
  sort_order: number
}

export interface Client extends BaseRecord {
  code: string
  name: string
  firm_name: string
  mobile: string
  email: string
  gstin: string
  pan: string
  service_type: string
  notes: string
  is_active: boolean
}

export type TxnType = 'income' | 'expense' | 'contra'
export type PaymentMethod = 'cash' | 'upi' | 'bank_transfer' | 'neft_rtgs' | 'cheque' | 'other'
export type TxnStatus = 'active' | 'cancelled'

export interface Transaction extends BaseRecord {
  type: TxnType
  voucher_no: string
  txn_date: ISODate
  amount_paise: Paise
  payment_method: PaymentMethod
  /** income: account receiving money; expense: account paying; contra: source account. */
  account_id: string
  /** contra only: destination account. */
  to_account_id: string | null
  category_id: string | null
  client_id: string | null
  /** Income: business/firm name. Expense: "paid to". */
  party: string
  service: string
  narration: string
  reference_no: string
  status: TxnStatus
  cancel_reason: string
  cancelled_at: string | null
  recurring_template_id: string | null
}

export interface FeeBill extends BaseRecord {
  bill_no: string
  bill_date: ISODate
  due_date: ISODate | null
  client_id: string
  category_id: string | null
  service: string
  amount_paise: Paise
  narration: string
  status: TxnStatus
  cancel_reason: string
  last_reminded_at: string | null
}

export interface FeeAllocation extends BaseRecord {
  fee_bill_id: string
  transaction_id: string
  amount_paise: Paise
}

export interface RecurringTemplate extends BaseRecord {
  name: string
  party: string
  category_id: string | null
  amount_paise: Paise
  payment_method: PaymentMethod
  account_id: string
  narration: string
  day_of_month: number
  next_due_date: ISODate
  is_active: boolean
}

export interface Attachment extends BaseRecord {
  transaction_id: string
  file_name: string
  mime_type: string
  size_bytes: number
  /** Path inside the private Supabase storage bucket once uploaded. */
  storage_path: string | null
}

export type AuditAction = 'create' | 'update' | 'cancel' | 'restore' | 'opening_balance' | 'import' | 'conflict'

export interface AuditLog extends BaseRecord {
  entity: TableName
  entity_id: string
  action: AuditAction
  summary: string
  before_data: unknown
  after_data: unknown
  source: 'app' | 'db'
}

export interface TableMap {
  business_profiles: BusinessProfile
  accounts: Account
  opening_balances: OpeningBalance
  categories: Category
  clients: Client
  fee_bills: FeeBill
  recurring_templates: RecurringTemplate
  transactions: Transaction
  fee_allocations: FeeAllocation
  attachments: Attachment
  audit_logs: AuditLog
}

export type TableName = keyof TableMap

/** Order matters: parents are pushed before rows that reference them. */
export const TABLES: TableName[] = [
  'business_profiles',
  'accounts',
  'opening_balances',
  'categories',
  'clients',
  'fee_bills',
  'recurring_templates',
  'transactions',
  'fee_allocations',
  'attachments',
  'audit_logs',
]

/** Everything the UI and reports need, held in memory. */
export interface DataSnapshot {
  businessId: string
  profile: BusinessProfile | null
  accounts: Account[]
  opening_balances: OpeningBalance[]
  categories: Category[]
  clients: Client[]
  transactions: Transaction[]
  fee_bills: FeeBill[]
  fee_allocations: FeeAllocation[]
  recurring_templates: RecurringTemplate[]
  attachments: Attachment[]
  audit_logs: AuditLog[]
}

export const PAYMENT_METHODS: { value: PaymentMethod; label: string }[] = [
  { value: 'cash', label: 'Cash' },
  { value: 'upi', label: 'UPI' },
  { value: 'bank_transfer', label: 'Bank Transfer' },
  { value: 'neft_rtgs', label: 'NEFT / RTGS' },
  { value: 'cheque', label: 'Cheque' },
  { value: 'other', label: 'Other' },
]

export function paymentMethodLabel(m: PaymentMethod): string {
  return PAYMENT_METHODS.find((p) => p.value === m)?.label ?? m
}

/** Which kind of account a payment method may post to. */
export function accountKindsForMethod(m: PaymentMethod): AccountKind[] {
  if (m === 'cash') return ['cash']
  if (m === 'upi') return ['upi', 'bank']
  if (m === 'other') return ['bank', 'upi']
  return ['bank']
}

export const DEFAULT_INCOME_CATEGORIES = [
  'Income Tax Return Filing Fees',
  'GST Return Filing Fees',
  'TDS Return Filing Fees',
  'Tax Audit Fees',
  'Accounting Fees',
  'Bookkeeping Fees',
  'GST Registration Fees',
  'Income Tax Consultancy Fees',
  'Company Compliance Fees',
  'ROC Filing Fees',
  'Financial Statement Preparation Fees',
  'Project Report / CMA Preparation Fees',
  'Other Consultancy Income',
  'Miscellaneous Professional Receipts',
]

export const DEFAULT_EXPENSE_CATEGORIES = [
  'Office Rent',
  'Electricity Expenses',
  'Internet and Mobile Recharge',
  'Staff Salary',
  'Travelling Expenses',
  'Fuel Expenses',
  'Printing and Stationery',
  'Office Maintenance',
  'Computer and Laptop Expenses',
  'Accounting Software Expenses',
  'Professional Subscription Charges',
  'Bank Charges',
  'Refreshment Expenses',
  'Courier Expenses',
  'Other Office Expenses',
]

export const DEFAULT_SETTINGS: BusinessSettings = {
  theme: 'system',
  auto_lock_minutes: 10,
  books_locked_until: null,
  reminder_message:
    'Dear {client}, this is a gentle reminder that professional fees of {amount} against bill {bill} dated {date} are outstanding. Kindly arrange the payment at the earliest. Thank you – {business}',
  receipt_footer: 'This is a computer-generated receipt.',
}
