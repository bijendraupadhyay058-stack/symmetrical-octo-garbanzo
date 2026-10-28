import { billPositions, clientPositions } from '../accounting/fees'
import { buildLedger, buildLookups, compareTxns, effectiveOpening, particularsFor, type Lookups } from '../accounting/ledger'
import { fyLabel, fyMonths, fyOf, fyRange, formatDate, formatMonth, monthRange, todayIST, type DateRange } from '../dates'
import { paymentMethodLabel, type DataSnapshot, type Transaction } from '../types'
import type { ReportColumn, ReportData, ReportFilters, ReportId, ReportRow } from './types'

export interface ReportMeta {
  id: ReportId
  title: string
  description: string
  filters: ('range' | 'date' | 'month' | 'fy' | 'client' | 'category' | 'payment' | 'account')[]
  group: 'Books' | 'Registers' | 'Analysis' | 'Clients'
}

export const REPORTS: ReportMeta[] = [
  { id: 'daily-cashbook', title: 'Daily Cash Book', description: 'Cash receipts and payments for one day with opening and closing cash', filters: ['date', 'account'], group: 'Books' },
  { id: 'monthly-cashbook', title: 'Monthly Cash Book', description: 'Cash book for a month or any date range with running balance', filters: ['range', 'account'], group: 'Books' },
  { id: 'bank-register', title: 'Bank / UPI Transaction Register', description: 'Bank and UPI ledger with running balance', filters: ['range', 'account', 'payment'], group: 'Books' },
  { id: 'receipts-payments', title: 'Receipt and Payment Statement', description: 'Consolidated cash + bank receipts and payments (cash basis)', filters: ['range'], group: 'Books' },
  { id: 'income-register', title: 'Income Register', description: 'All receipts with client, service and mode', filters: ['range', 'client', 'category', 'payment'], group: 'Registers' },
  { id: 'expense-register', title: 'Expense Register', description: 'All business expenses paid', filters: ['range', 'category', 'payment'], group: 'Registers' },
  { id: 'voucher-register', title: 'Voucher Register', description: 'Every voucher in number order, including cancelled ones', filters: ['range', 'payment'], group: 'Registers' },
  { id: 'fee-register', title: 'Professional Fee Register', description: 'Fee bills raised, amount received and balance outstanding', filters: ['range', 'client'], group: 'Registers' },
  { id: 'monthly-summary', title: 'Monthly Income & Expense Summary', description: 'Month-wise receipts, payments and net cash flow', filters: ['fy'], group: 'Analysis' },
  { id: 'service-income', title: 'Service-wise Income Report', description: 'Income grouped by service / category', filters: ['range', 'payment'], group: 'Analysis' },
  { id: 'expense-category', title: 'Expense Category-wise Report', description: 'Expenses grouped by category', filters: ['range', 'payment'], group: 'Analysis' },
  { id: 'fy-summary', title: 'Financial Year Summary', description: 'Opening, receipts, payments and closing for the year, plus fees billed vs collected', filters: ['fy'], group: 'Analysis' },
  { id: 'client-income', title: 'Client-wise Income Report', description: 'Fees received from each client', filters: ['range', 'category', 'payment'], group: 'Clients' },
  { id: 'client-outstanding', title: 'Client Outstanding Fees Report', description: 'Fees billed, received and outstanding per client', filters: ['client'], group: 'Clients' },
  { id: 'client-statement', title: 'Client Statement', description: 'Bills and receipts of one client with running balance', filters: ['range', 'client'], group: 'Clients' },
]

const CASH_BASIS_NOTE =
  'Cash-basis statement: shows money actually received and paid during the period. It is not a Profit & Loss account – fees billed but not yet received, expenses payable, depreciation and other accruals are excluded.'

export function periodLabel(r: DateRange): string {
  return r.from === r.to ? formatDate(r.from) : `${formatDate(r.from)} to ${formatDate(r.to)}`
}

function filterTxns(snap: DataSnapshot, f: ReportFilters, opts: { includeCancelled?: boolean } = {}): Transaction[] {
  return snap.transactions
    .filter(
      (t) =>
        (opts.includeCancelled || t.status === 'active') &&
        t.txn_date >= f.range.from &&
        t.txn_date <= f.range.to &&
        (!f.clientId || t.client_id === f.clientId) &&
        (!f.categoryId || t.category_id === f.categoryId) &&
        (!f.paymentMethod || t.payment_method === f.paymentMethod),
    )
    .sort(compareTxns)
}

const ledgerCols: ReportColumn[] = [
  { key: 'date', label: 'Date', type: 'date', width: 1.1 },
  { key: 'voucher', label: 'Voucher No.', type: 'text', width: 1.2 },
  { key: 'particulars', label: 'Particulars', type: 'text', width: 3 },
  { key: 'receipt', label: 'Receipt', type: 'money', width: 1.3 },
  { key: 'payment', label: 'Payment', type: 'money', width: 1.3 },
  { key: 'balance', label: 'Balance', type: 'money', width: 1.4 },
]

function ledgerReport(
  snap: DataSnapshot,
  id: ReportId,
  title: string,
  accountIds: string[],
  range: DateRange,
  lk: Lookups,
  methodFilter?: Transaction['payment_method'],
): ReportData {
  const ledger = buildLedger(snap, accountIds, range, lk)
  const rows: ReportRow[] = []
  let shownR = 0
  let shownP = 0
  for (const r of ledger.rows) {
    if (r.kind === 'opening') {
      rows.push({ style: 'opening', cells: { date: r.date, voucher: '', particulars: 'Opening Balance', receipt: null, payment: null, balance: r.balance } })
    } else if (r.kind === 'entry') {
      if (methodFilter && r.txn!.payment_method !== methodFilter) continue
      shownR += r.receipt
      shownP += r.payment
      const narr = r.narration ? ` (${r.narration})` : ''
      const acct = accountIds.length > 1 ? ` [${lk.accountName(r.accountId)}]` : ''
      rows.push({
        ref: r.txn!.id,
        cells: { date: r.date, voucher: r.voucher_no, particulars: r.particulars + narr + acct, receipt: r.receipt || null, payment: r.payment || null, balance: r.balance },
      })
    }
  }
  rows.push({ style: 'total', cells: { date: null, voucher: '', particulars: 'Total', receipt: shownR, payment: shownP, balance: null } })
  rows.push({ style: 'total', cells: { date: range.to, voucher: '', particulars: 'Closing Balance', receipt: null, payment: null, balance: ledger.closing } })
  const names = accountIds.map((id) => lk.accountName(id)).join(', ')
  return {
    id,
    title: `${title}${names ? ' – ' + names : ''}`,
    period: periodLabel(range),
    note: methodFilter
      ? 'Filtered by payment method: running balance includes all entries; totals show only filtered entries.'
      : 'Opening Balance + Total Receipts − Total Payments = Closing Balance',
    columns: ledgerCols,
    rows,
    summary: [
      { label: 'Opening', value: ledger.opening, tone: 'balance' },
      { label: 'Receipts', value: ledger.totalReceipts, tone: 'income' },
      { label: 'Payments', value: ledger.totalPayments, tone: 'expense' },
      { label: 'Closing', value: ledger.closing, tone: 'balance' },
    ],
  }
}

function groupSum<K>(items: Transaction[], key: (t: Transaction) => K): Map<K, { amount: number; count: number }> {
  const m = new Map<K, { amount: number; count: number }>()
  for (const t of items) {
    const k = key(t)
    const cur = m.get(k) ?? { amount: 0, count: 0 }
    cur.amount += t.amount_paise
    cur.count += 1
    m.set(k, cur)
  }
  return m
}

function groupedReport(
  id: ReportId,
  title: string,
  range: DateRange,
  groups: Map<string, { amount: number; count: number }>,
  label: string,
  note?: string,
): ReportData {
  const total = [...groups.values()].reduce((s, g) => s + g.amount, 0)
  const sorted = [...groups.entries()].sort((a, b) => b[1].amount - a[1].amount || a[0].localeCompare(b[0]))
  const rows: ReportRow[] = sorted.map(([name, g]) => ({
    cells: { name, count: g.count, amount: g.amount, share: total ? `${((g.amount * 100) / total).toFixed(1)}%` : '' },
  }))
  rows.push({ style: 'total', cells: { name: 'Grand Total', count: sorted.reduce((s, [, g]) => s + g.count, 0), amount: total, share: total ? '100.0%' : '' } })
  return {
    id,
    title,
    period: periodLabel(range),
    note,
    columns: [
      { key: 'name', label, type: 'text', width: 3 },
      { key: 'count', label: 'Entries', type: 'number', width: 0.8 },
      { key: 'amount', label: 'Amount', type: 'money', width: 1.4 },
      { key: 'share', label: 'Share', type: 'text', width: 0.8 },
    ],
    rows,
  }
}

function registerReport(snap: DataSnapshot, f: ReportFilters, type: 'income' | 'expense', lk: Lookups): ReportData {
  const txns = filterTxns(snap, f).filter((t) => t.type === type)
  const rows: ReportRow[] = txns.map((t) => ({
    ref: t.id,
    cells: {
      date: t.txn_date,
      voucher: t.voucher_no,
      party: type === 'income' ? lk.clientName(t.client_id) || t.party : t.party,
      category: lk.categoryName(t.category_id) + (t.service ? ` – ${t.service}` : ''),
      mode: paymentMethodLabel(t.payment_method),
      account: lk.accountName(t.account_id),
      reference: t.reference_no,
      amount: t.amount_paise,
    },
  }))
  const total = txns.reduce((s, t) => s + t.amount_paise, 0)
  const cash = txns.filter((t) => lk.account(t.account_id)?.kind === 'cash').reduce((s, t) => s + t.amount_paise, 0)
  rows.push({ style: 'total', cells: { date: null, voucher: '', party: `Grand Total (${txns.length} entries)`, category: '', mode: '', account: '', reference: '', amount: total } })
  return {
    id: type === 'income' ? 'income-register' : 'expense-register',
    title: type === 'income' ? 'Income Register' : 'Expense Register',
    period: periodLabel(f.range),
    columns: [
      { key: 'date', label: 'Date', type: 'date', width: 1 },
      { key: 'voucher', label: 'Voucher', type: 'text', width: 1.1 },
      { key: 'party', label: type === 'income' ? 'Client / Received From' : 'Paid To', type: 'text', width: 2 },
      { key: 'category', label: type === 'income' ? 'Service' : 'Category', type: 'text', width: 2 },
      { key: 'mode', label: 'Mode', type: 'text', width: 0.9 },
      { key: 'account', label: 'Account', type: 'text', width: 1.2 },
      { key: 'reference', label: 'Ref No.', type: 'text', width: 1 },
      { key: 'amount', label: 'Amount', type: 'money', width: 1.2 },
    ],
    rows,
    summary: [
      { label: 'Total', value: total, tone: type === 'income' ? 'income' : 'expense' },
      { label: 'In Cash', value: cash, tone: 'neutral' },
      { label: 'Bank / UPI', value: total - cash, tone: 'neutral' },
    ],
  }
}

export function generateReport(snap: DataSnapshot, id: ReportId, f: ReportFilters): ReportData {
  const lk = buildLookups(snap)
  const cashIds = snap.accounts.filter((a) => a.kind === 'cash').map((a) => a.id)
  const bankIds = snap.accounts.filter((a) => a.kind !== 'cash').map((a) => a.id)

  switch (id) {
    case 'daily-cashbook':
    case 'monthly-cashbook': {
      const ids = f.accountId && cashIds.includes(f.accountId) ? [f.accountId] : cashIds
      const range = id === 'daily-cashbook' ? { from: f.range.to, to: f.range.to } : f.range
      return ledgerReport(snap, id, id === 'daily-cashbook' ? 'Daily Cash Book' : 'Cash Book', ids, range, lk)
    }
    case 'bank-register': {
      const ids = f.accountId && bankIds.includes(f.accountId) ? [f.accountId] : bankIds
      return ledgerReport(snap, id, 'Bank / UPI Register', ids, f.range, lk, f.paymentMethod)
    }
    case 'income-register':
      return registerReport(snap, f, 'income', lk)
    case 'expense-register':
      return registerReport(snap, f, 'expense', lk)

    case 'monthly-summary': {
      const fy = fyOf(f.range.from)
      const rows: ReportRow[] = []
      let ti = 0, te = 0, tc = 0, tb = 0
      for (const ym of fyMonths(fy)) {
        const r = monthRange(ym + '-01')
        const txns = filterTxns(snap, { ...f, range: r })
        const inc = txns.filter((t) => t.type === 'income')
        const income = inc.reduce((s, t) => s + t.amount_paise, 0)
        const incCash = inc.filter((t) => cashIds.includes(t.account_id)).reduce((s, t) => s + t.amount_paise, 0)
        const expense = txns.filter((t) => t.type === 'expense').reduce((s, t) => s + t.amount_paise, 0)
        ti += income; te += expense; tc += incCash; tb += income - incCash
        rows.push({ cells: { month: formatMonth(ym), cash: incCash, bank: income - incCash, income, expense, net: income - expense } })
      }
      rows.push({ style: 'total', cells: { month: 'Total', cash: tc, bank: tb, income: ti, expense: te, net: ti - te } })
      return {
        id, title: 'Monthly Income & Expense Summary', period: `FY ${fyLabel(fy)}`, note: CASH_BASIS_NOTE,
        columns: [
          { key: 'month', label: 'Month', type: 'text', width: 1.2 },
          { key: 'cash', label: 'Income (Cash)', type: 'money' },
          { key: 'bank', label: 'Income (Bank/UPI)', type: 'money' },
          { key: 'income', label: 'Total Income', type: 'money' },
          { key: 'expense', label: 'Total Expenses', type: 'money' },
          { key: 'net', label: 'Net Cash Flow', type: 'money' },
        ],
        rows,
        summary: [
          { label: 'Income', value: ti, tone: 'income' },
          { label: 'Expenses', value: te, tone: 'expense' },
          { label: 'Net', value: ti - te, tone: 'balance' },
        ],
      }
    }

    case 'service-income': {
      const txns = filterTxns(snap, f).filter((t) => t.type === 'income')
      return groupedReport(id, 'Service-wise Income Report', f.range, groupSum(txns, (t) => lk.categoryName(t.category_id)), 'Service / Category', CASH_BASIS_NOTE)
    }
    case 'expense-category': {
      const txns = filterTxns(snap, f).filter((t) => t.type === 'expense')
      return groupedReport(id, 'Expense Category-wise Report', f.range, groupSum(txns, (t) => lk.categoryName(t.category_id)), 'Expense Category', CASH_BASIS_NOTE)
    }
    case 'client-income': {
      const txns = filterTxns(snap, f).filter((t) => t.type === 'income')
      return groupedReport(id, 'Client-wise Income Report', f.range, groupSum(txns, (t) => lk.clientName(t.client_id) || `${t.party || 'Walk-in'} (no client record)`), 'Client', CASH_BASIS_NOTE)
    }

    case 'fy-summary': {
      const fy = fyOf(f.range.from)
      const range = fyRange(fy)
      const rows: ReportRow[] = []
      const lines = (label: string, value: number | null, style: ReportRow['style'] = 'normal') =>
        rows.push({ style, cells: { item: label, amount: value } })
      lines('A. Cash & Bank Position', null, 'heading')
      let open = 0, close = 0
      for (const a of snap.accounts) {
        const l = buildLedger(snap, [a.id], range, lk)
        if (!a.is_active && l.opening === 0 && l.closing === 0 && l.rows.length <= 2) continue
        open += l.opening
        close += l.closing
        lines(`${a.name} – Opening`, l.opening)
      }
      lines('Total Opening Balance', open, 'subtotal')
      const txns = filterTxns(snap, { range })
      const income = txns.filter((t) => t.type === 'income').reduce((s, t) => s + t.amount_paise, 0)
      const expense = txns.filter((t) => t.type === 'expense').reduce((s, t) => s + t.amount_paise, 0)
      lines('Add: Total Receipts (fees collected)', income)
      lines('Less: Total Payments (expenses paid)', expense)
      lines('Total Closing Balance', close, 'subtotal')
      for (const a of snap.accounts) {
        const l = buildLedger(snap, [a.id], range, lk)
        if (!a.is_active && l.closing === 0) continue
        lines(`${a.name} – Closing`, l.closing, 'muted')
      }
      lines('B. Professional Fees (accrual view – memorandum)', null, 'heading')
      const bills = billPositions(snap).filter((p) => p.status !== 'cancelled' && p.bill.bill_date >= range.from && p.bill.bill_date <= range.to)
      const billed = bills.reduce((s, p) => s + p.bill.amount_paise, 0)
      const collected = bills.reduce((s, p) => s + p.received, 0)
      lines('Fees billed during the year', billed)
      lines('Collected against those bills', collected)
      lines('Still outstanding from those bills', billed - collected, 'subtotal')
      lines('C. Net Cash Surplus (Receipts − Payments)', income - expense, 'total')
      return {
        id, title: 'Financial Year Summary', period: `FY ${fyLabel(fy)} (${periodLabel(range)})`,
        note: 'Sections A and C are cash-basis. Section B is a memorandum accrual view of fee billing and is not added to cash. This is not a Profit & Loss account.',
        columns: [{ key: 'item', label: 'Particulars', type: 'text', width: 4 }, { key: 'amount', label: 'Amount', type: 'money', width: 1.5 }],
        rows,
        summary: [
          { label: 'Opening', value: open, tone: 'balance' },
          { label: 'Receipts', value: income, tone: 'income' },
          { label: 'Payments', value: expense, tone: 'expense' },
          { label: 'Closing', value: close, tone: 'balance' },
        ],
      }
    }

    case 'client-outstanding': {
      const pos = clientPositions(snap)
      const today = todayIST()
      const bills = billPositions(snap, today)
      const rows: ReportRow[] = []
      let tb = 0, tr = 0, to = 0, tu = 0
      const clients = [...snap.clients].filter((c) => !f.clientId || c.id === f.clientId).sort((a, b) => a.name.localeCompare(b.name))
      for (const c of clients) {
        const p = pos.get(c.id)
        if (!p || (p.billed === 0 && p.unadjusted === 0)) continue
        const overdue = bills.filter((b) => b.bill.client_id === c.id && b.overdue).reduce((s, b) => s + b.outstanding, 0)
        tb += p.billed; tr += p.allocated; to += p.outstanding; tu += p.unadjusted
        rows.push({ cells: { client: `${c.name} (${c.code})`, mobile: c.mobile, billed: p.billed, received: p.allocated, outstanding: p.outstanding, overdue: overdue || null, advance: p.unadjusted || null } })
      }
      rows.push({ style: 'total', cells: { client: 'Grand Total', mobile: '', billed: tb, received: tr, outstanding: to, overdue: null, advance: tu || null } })
      return {
        id, title: 'Client Outstanding Fees Report', period: `As on ${formatDate(today)}`,
        note: 'Outstanding = fees billed − receipts adjusted against those bills. "On account" shows receipts not yet adjusted against any bill.',
        columns: [
          { key: 'client', label: 'Client', type: 'text', width: 2.4 },
          { key: 'mobile', label: 'Mobile', type: 'text', width: 1.2 },
          { key: 'billed', label: 'Fees Billed', type: 'money' },
          { key: 'received', label: 'Received', type: 'money' },
          { key: 'outstanding', label: 'Outstanding', type: 'money' },
          { key: 'overdue', label: 'Overdue', type: 'money' },
          { key: 'advance', label: 'On Account', type: 'money' },
        ],
        rows,
        summary: [
          { label: 'Billed', value: tb, tone: 'neutral' },
          { label: 'Received', value: tr, tone: 'income' },
          { label: 'Outstanding', value: to, tone: 'expense' },
        ],
      }
    }

    case 'fee-register': {
      const today = todayIST()
      const bills = billPositions(snap, today)
        .filter((p) => p.bill.bill_date >= f.range.from && p.bill.bill_date <= f.range.to && (!f.clientId || p.bill.client_id === f.clientId))
        .sort((a, b) => (a.bill.bill_date < b.bill.bill_date ? -1 : a.bill.bill_date > b.bill.bill_date ? 1 : a.bill.bill_no.localeCompare(b.bill.bill_no)))
      const statusText = { unpaid: 'Unpaid', partial: 'Part Paid', paid: 'Paid', cancelled: 'Cancelled' }
      const rows: ReportRow[] = bills.map((p) => ({
        style: p.status === 'cancelled' ? 'muted' : 'normal',
        cells: {
          bill: p.bill.bill_no, date: p.bill.bill_date, client: lk.clientName(p.bill.client_id),
          service: p.bill.category_id ? lk.categoryName(p.bill.category_id) + (p.bill.service ? ` – ${p.bill.service}` : '') : p.bill.service,
          charged: p.status === 'cancelled' ? null : p.bill.amount_paise, received: p.received || null,
          outstanding: p.status === 'cancelled' ? null : p.outstanding,
          status: statusText[p.status] + (p.overdue ? ' (Overdue)' : ''),
        },
      }))
      const live = bills.filter((p) => p.status !== 'cancelled')
      const c = live.reduce((s, p) => s + p.bill.amount_paise, 0)
      const r = live.reduce((s, p) => s + p.received, 0)
      rows.push({ style: 'total', cells: { bill: '', date: null, client: 'Grand Total', service: '', charged: c, received: r, outstanding: c - r, status: '' } })
      return {
        id, title: 'Professional Fee Register', period: periodLabel(f.range),
        note: 'Fee bills are demands raised on clients and are NOT income. Income is recorded only when the fee is actually received.',
        columns: [
          { key: 'bill', label: 'Bill No.', type: 'text', width: 1.1 },
          { key: 'date', label: 'Date', type: 'date', width: 1 },
          { key: 'client', label: 'Client', type: 'text', width: 2 },
          { key: 'service', label: 'Service', type: 'text', width: 2 },
          { key: 'charged', label: 'Fees Charged', type: 'money' },
          { key: 'received', label: 'Received', type: 'money' },
          { key: 'outstanding', label: 'Balance', type: 'money' },
          { key: 'status', label: 'Status', type: 'text', width: 1 },
        ],
        rows,
        summary: [
          { label: 'Charged', value: c, tone: 'neutral' },
          { label: 'Received', value: r, tone: 'income' },
          { label: 'Outstanding', value: c - r, tone: 'expense' },
        ],
      }
    }

    case 'client-statement': {
      const client = snap.clients.find((c) => c.id === f.clientId)
      if (!client) {
        return { id, title: 'Client Statement', period: periodLabel(f.range), note: 'Select a client to view the statement.', columns: [{ key: 'msg', label: '', type: 'text' }], rows: [] }
      }
      type Ev = { date: string; order: string; doc: string; text: string; debit: number; credit: number }
      const evs: Ev[] = []
      for (const b of snap.fee_bills) {
        if (b.client_id !== client.id || b.status !== 'active') continue
        evs.push({ date: b.bill_date, order: b.created_at, doc: b.bill_no, text: `Fee bill – ${b.category_id ? lk.categoryName(b.category_id) : ''} ${b.service}`.trim(), debit: b.amount_paise, credit: 0 })
      }
      for (const t of snap.transactions) {
        if (t.client_id !== client.id || t.type !== 'income' || t.status !== 'active') continue
        evs.push({ date: t.txn_date, order: t.created_at, doc: t.voucher_no, text: `Received – ${paymentMethodLabel(t.payment_method)}${t.reference_no ? ' Ref ' + t.reference_no : ''}`, debit: 0, credit: t.amount_paise })
      }
      evs.sort((a, b) => (a.date !== b.date ? (a.date < b.date ? -1 : 1) : a.order < b.order ? -1 : 1))
      let bal = 0
      for (const e of evs) if (e.date < f.range.from) bal += e.debit - e.credit
      const rows: ReportRow[] = [{ style: 'opening', cells: { date: f.range.from, doc: '', text: 'Opening balance due', debit: null, credit: null, balance: bal } }]
      let td = 0, tc = 0
      for (const e of evs) {
        if (e.date < f.range.from || e.date > f.range.to) continue
        bal += e.debit - e.credit
        td += e.debit; tc += e.credit
        rows.push({ cells: { date: e.date, doc: e.doc, text: e.text, debit: e.debit || null, credit: e.credit || null, balance: bal } })
      }
      rows.push({ style: 'total', cells: { date: null, doc: '', text: 'Total / Closing balance due', debit: td, credit: tc, balance: bal } })
      return {
        id, title: `Client Statement – ${client.name}${client.firm_name ? ' (' + client.firm_name + ')' : ''}`, period: periodLabel(f.range),
        note: 'Positive balance = fees due from client; negative = advance received.',
        columns: [
          { key: 'date', label: 'Date', type: 'date', width: 1 },
          { key: 'doc', label: 'Doc No.', type: 'text', width: 1.2 },
          { key: 'text', label: 'Particulars', type: 'text', width: 3 },
          { key: 'debit', label: 'Fees Billed', type: 'money' },
          { key: 'credit', label: 'Received', type: 'money' },
          { key: 'balance', label: 'Balance Due', type: 'money' },
        ],
        rows,
        summary: [
          { label: 'Billed', value: td, tone: 'neutral' },
          { label: 'Received', value: tc, tone: 'income' },
          { label: 'Balance Due', value: bal, tone: 'expense' },
        ],
      }
    }

    case 'receipts-payments': {
      const allIds = snap.accounts.map((a) => a.id)
      const txns = filterTxns(snap, f)
      const rows: ReportRow[] = []
      const opening = buildLedger(snap, allIds, f.range, lk).opening
      const cashOpen = cashIds.length ? buildLedger(snap, cashIds, f.range, lk).opening : 0
      rows.push({ style: 'heading', cells: { item: 'RECEIPTS', cash: null, bank: null, total: null } })
      rows.push({ style: 'opening', cells: { item: 'To Opening Balance', cash: cashOpen, bank: opening - cashOpen, total: opening } })
      const add = (type: 'income' | 'expense') => {
        const g = new Map<string, { cash: number; bank: number }>()
        for (const t of txns.filter((x) => x.type === type)) {
          const k = lk.categoryName(t.category_id)
          const cur = g.get(k) ?? { cash: 0, bank: 0 }
          if (cashIds.includes(t.account_id)) cur.cash += t.amount_paise
          else cur.bank += t.amount_paise
          g.set(k, cur)
        }
        let c = 0, b = 0
        for (const [k, v] of [...g.entries()].sort((a, b2) => a[0].localeCompare(b2[0]))) {
          rows.push({ cells: { item: `${type === 'income' ? 'To' : 'By'} ${k}`, cash: v.cash || null, bank: v.bank || null, total: v.cash + v.bank } })
          c += v.cash; b += v.bank
        }
        return { c, b }
      }
      const inc = add('income')
      // Contra entries move money between cash and bank; shown for completeness, they net to zero overall.
      const contraIn = { c: 0, b: 0 }
      const contraOut = { c: 0, b: 0 }
      for (const t of txns.filter((x) => x.type === 'contra')) {
        const fromCash = cashIds.includes(t.account_id)
        const toCash = cashIds.includes(t.to_account_id ?? '')
        if (fromCash === toCash) continue
        if (toCash) { contraIn.c += t.amount_paise; contraOut.b += t.amount_paise } else { contraIn.b += t.amount_paise; contraOut.c += t.amount_paise }
      }
      if (contraIn.c || contraIn.b) rows.push({ style: 'muted', cells: { item: 'To Contra (transfers in)', cash: contraIn.c || null, bank: contraIn.b || null, total: contraIn.c + contraIn.b } })
      rows.push({ style: 'subtotal', cells: { item: 'Total Receipts (incl. opening)', cash: cashOpen + inc.c + contraIn.c, bank: opening - cashOpen + inc.b + contraIn.b, total: opening + inc.c + inc.b + contraIn.c + contraIn.b } })
      rows.push({ style: 'heading', cells: { item: 'PAYMENTS', cash: null, bank: null, total: null } })
      const exp = add('expense')
      if (contraOut.c || contraOut.b) rows.push({ style: 'muted', cells: { item: 'By Contra (transfers out)', cash: contraOut.c || null, bank: contraOut.b || null, total: contraOut.c + contraOut.b } })
      const closeCash = cashOpen + inc.c + contraIn.c - exp.c - contraOut.c
      const closeBank = opening - cashOpen + inc.b + contraIn.b - exp.b - contraOut.b
      rows.push({ style: 'opening', cells: { item: 'By Closing Balance', cash: closeCash, bank: closeBank, total: closeCash + closeBank } })
      rows.push({ style: 'subtotal', cells: { item: 'Total Payments (incl. closing)', cash: exp.c + contraOut.c + closeCash, bank: exp.b + contraOut.b + closeBank, total: exp.c + exp.b + contraOut.c + contraOut.b + closeCash + closeBank } })
      return {
        id, title: 'Receipt and Payment Statement', period: periodLabel(f.range), note: CASH_BASIS_NOTE,
        columns: [
          { key: 'item', label: 'Particulars', type: 'text', width: 3 },
          { key: 'cash', label: 'Cash', type: 'money' },
          { key: 'bank', label: 'Bank / UPI', type: 'money' },
          { key: 'total', label: 'Total', type: 'money' },
        ],
        rows,
        summary: [
          { label: 'Opening', value: opening, tone: 'balance' },
          { label: 'Receipts', value: inc.c + inc.b, tone: 'income' },
          { label: 'Payments', value: exp.c + exp.b, tone: 'expense' },
          { label: 'Closing', value: closeCash + closeBank, tone: 'balance' },
        ],
      }
    }

    case 'voucher-register': {
      const txns = filterTxns(snap, f, { includeCancelled: true }).sort((a, b) => a.voucher_no.localeCompare(b.voucher_no, 'en', { numeric: true }))
      const rows: ReportRow[] = txns.map((t) => ({
        ref: t.id,
        style: t.status === 'cancelled' ? 'muted' : 'normal',
        cells: {
          voucher: t.voucher_no,
          date: t.txn_date,
          type: t.type === 'income' ? 'Receipt' : t.type === 'expense' ? 'Payment' : 'Contra',
          particulars: particularsFor(t, lk),
          mode: paymentMethodLabel(t.payment_method),
          amount: t.amount_paise,
          status: t.status === 'cancelled' ? `Cancelled: ${t.cancel_reason}` : 'Active',
        },
      }))
      const active = txns.filter((t) => t.status === 'active')
      return {
        id, title: 'Voucher Register', period: periodLabel(f.range),
        note: 'Cancelled vouchers are listed for audit trail but excluded from all totals and balances.',
        columns: [
          { key: 'voucher', label: 'Voucher No.', type: 'text', width: 1.2 },
          { key: 'date', label: 'Date', type: 'date', width: 1 },
          { key: 'type', label: 'Type', type: 'text', width: 0.9 },
          { key: 'particulars', label: 'Particulars', type: 'text', width: 2.6 },
          { key: 'mode', label: 'Mode', type: 'text', width: 0.9 },
          { key: 'amount', label: 'Amount', type: 'money', width: 1.2 },
          { key: 'status', label: 'Status', type: 'text', width: 1.4 },
        ],
        rows,
        summary: [
          { label: 'Vouchers', value: txns.length, tone: 'neutral', kind: 'count' },
          { label: 'Receipts', value: active.filter((t) => t.type === 'income').reduce((s, t) => s + t.amount_paise, 0), tone: 'income' },
          { label: 'Payments', value: active.filter((t) => t.type === 'expense').reduce((s, t) => s + t.amount_paise, 0), tone: 'expense' },
        ],
      }
    }
  }
}

export function reportMeta(id: ReportId): ReportMeta {
  return REPORTS.find((r) => r.id === id)!
}

/** Opening of every account at a date – used by the dashboard and tests. */
export function openingsSummary(snap: DataSnapshot) {
  return snap.accounts.map((a) => ({ account: a, ...effectiveOpening(snap.opening_balances, a.id) }))
}
