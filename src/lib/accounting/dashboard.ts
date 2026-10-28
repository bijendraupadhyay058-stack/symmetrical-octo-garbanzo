import { addDays, fyMonths, fyRange, monthRange, formatMonth, type ISODate } from '../dates'
import type { Paise } from '../money'
import type { DataSnapshot, Transaction } from '../types'
import { clientPositions } from './fees'
import { balanceAsOf, buildLookups, compareTxns } from './ledger'

export interface DashboardData {
  asOn: ISODate
  cashIds: string[]
  bankIds: string[]
  todayOpeningCash: Paise
  todayCashIncome: Paise
  todayCashExpense: Paise
  todayContraCashIn: Paise
  todayContraCashOut: Paise
  todayClosingCash: Paise
  bankBalance: Paise
  monthIncome: Paise
  monthIncomeCash: Paise
  monthExpense: Paise
  monthExpenseCash: Paise
  monthNet: Paise
  outstandingFees: Paise
  totalTransactions: number
  recent: Transaction[]
  monthly: { month: string; label: string; income: number; expense: number; cash: number; bank: number }[]
  expenseByCategory: { name: string; value: number }[]
}

/** Every figure is derived from saved transactions – nothing is stored or hard-coded. */
export function computeDashboard(snap: DataSnapshot, asOn: ISODate, fy: number): DashboardData {
  const cashIds = snap.accounts.filter((a) => a.kind === 'cash').map((a) => a.id)
  const bankIds = snap.accounts.filter((a) => a.kind !== 'cash').map((a) => a.id)
  const isCash = (id: string | null) => !!id && cashIds.includes(id)
  const active = snap.transactions.filter((t) => t.status === 'active')

  const today = active.filter((t) => t.txn_date === asOn)
  const todayCashIncome = today.filter((t) => t.type === 'income' && isCash(t.account_id)).reduce((s, t) => s + t.amount_paise, 0)
  const todayCashExpense = today.filter((t) => t.type === 'expense' && isCash(t.account_id)).reduce((s, t) => s + t.amount_paise, 0)
  const contra = today.filter((t) => t.type === 'contra')
  const todayContraCashIn = contra.filter((t) => isCash(t.to_account_id) && !isCash(t.account_id)).reduce((s, t) => s + t.amount_paise, 0)
  const todayContraCashOut = contra.filter((t) => isCash(t.account_id) && !isCash(t.to_account_id)).reduce((s, t) => s + t.amount_paise, 0)
  const todayOpeningCash = balanceAsOf(snap, cashIds, addDays(asOn, -1))
  const todayClosingCash = balanceAsOf(snap, cashIds, asOn)

  const m = monthRange(asOn)
  const month = active.filter((t) => t.txn_date >= m.from && t.txn_date <= m.to)
  const monthIncome = month.filter((t) => t.type === 'income').reduce((s, t) => s + t.amount_paise, 0)
  const monthIncomeCash = month.filter((t) => t.type === 'income' && isCash(t.account_id)).reduce((s, t) => s + t.amount_paise, 0)
  const monthExpense = month.filter((t) => t.type === 'expense').reduce((s, t) => s + t.amount_paise, 0)
  const monthExpenseCash = month.filter((t) => t.type === 'expense' && isCash(t.account_id)).reduce((s, t) => s + t.amount_paise, 0)

  let outstandingFees = 0
  for (const p of clientPositions(snap).values()) outstandingFees += p.outstanding

  const monthly = fyMonths(fy).map((ym) => {
    const r = monthRange(ym + '-01')
    const txns = active.filter((t) => t.txn_date >= r.from && t.txn_date <= r.to)
    const inc = txns.filter((t) => t.type === 'income')
    const income = inc.reduce((s, t) => s + t.amount_paise, 0)
    const cash = inc.filter((t) => isCash(t.account_id)).reduce((s, t) => s + t.amount_paise, 0)
    return {
      month: ym,
      label: formatMonth(ym).replace(' 20', " '"),
      income: income / 100,
      expense: txns.filter((t) => t.type === 'expense').reduce((s, t) => s + t.amount_paise, 0) / 100,
      cash: cash / 100,
      bank: (income - cash) / 100,
    }
  })

  const lk = buildLookups(snap)
  const fr = fyRange(fy)
  const byCat = new Map<string, number>()
  for (const t of active) {
    if (t.type !== 'expense' || t.txn_date < fr.from || t.txn_date > fr.to) continue
    const k = lk.categoryName(t.category_id)
    byCat.set(k, (byCat.get(k) ?? 0) + t.amount_paise)
  }
  const expenseByCategory = [...byCat.entries()].map(([name, v]) => ({ name, value: v / 100 })).sort((a, b) => b.value - a.value)

  return {
    asOn,
    cashIds,
    bankIds,
    todayOpeningCash,
    todayCashIncome,
    todayCashExpense,
    todayContraCashIn,
    todayContraCashOut,
    todayClosingCash,
    bankBalance: balanceAsOf(snap, bankIds, asOn),
    monthIncome,
    monthIncomeCash,
    monthExpense,
    monthExpenseCash,
    monthNet: monthIncome - monthExpense,
    outstandingFees,
    totalTransactions: active.length,
    recent: [...snap.transactions].sort((a, b) => -compareTxns(a, b)).slice(0, 5),
    monthly,
    expenseByCategory,
  }
}
