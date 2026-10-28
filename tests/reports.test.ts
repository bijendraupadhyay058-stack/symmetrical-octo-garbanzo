import { describe, expect, it } from 'vitest'
import ExcelJS from 'exceljs'
import { DEMO_EXPECTED, seedDemo } from '@/lib/demo'
import { generateReport, REPORTS } from '@/lib/reports/reports'
import { reportToXlsx } from '@/lib/export/excel'
import { reportToPdf, voucherPdf } from '@/lib/export/pdf'
import { buildLedger } from '@/lib/accounting/ledger'
import { computeDashboard } from '@/lib/accounting/dashboard'
import { fyOf, fyRange, addDays } from '@/lib/dates'
import { makeStore } from './helpers'

const TODAY = '2026-10-28'

async function demo() {
  const store = await makeStore({ seed: false })
  await seedDemo(store, TODAY)
  return store
}

describe('sample dataset & reports', () => {
  it('demo entries land in the correct ledgers', async () => {
    const store = await demo()
    const s = store.getSnapshot()
    const range = { from: addDays(TODAY, -10), to: TODAY }
    for (const kind of ['cash', 'bank', 'upi'] as const) {
      const acc = s.accounts.find((a) => a.kind === kind)!
      const l = buildLedger(s, [acc.id], range)
      expect({ opening: l.opening, receipts: l.totalReceipts, payments: l.totalPayments, closing: l.closing }).toEqual(DEMO_EXPECTED[kind])
    }
    const dash = computeDashboard(s, TODAY, fyOf(TODAY))
    expect(dash.outstandingFees).toBe(DEMO_EXPECTED.outstanding)
    expect(dash.todayClosingCash).toBe(DEMO_EXPECTED.cash.closing)
  })

  it('every report generates with consistent grand totals', async () => {
    const store = await demo()
    const s = store.getSnapshot()
    const filters = { range: fyRange(fyOf(TODAY)), clientId: s.clients[0].id }
    for (const r of REPORTS) {
      const data = generateReport(s, r.id, filters)
      expect(data.title.length).toBeGreaterThan(3)
      expect(data.columns.length).toBeGreaterThan(0)
    }
    const inc = generateReport(s, 'income-register', { range: fyRange(fyOf(TODAY)) })
    expect(inc.rows.at(-1)!.cells.amount).toBe(DEMO_EXPECTED.totalIncome)
    const exp = generateReport(s, 'expense-register', { range: fyRange(fyOf(TODAY)) })
    expect(exp.rows.at(-1)!.cells.amount).toBe(DEMO_EXPECTED.totalExpense)
    const rp = generateReport(s, 'receipts-payments', { range: fyRange(fyOf(TODAY)) })
    const totals = rp.rows.filter((r) => r.style === 'subtotal').map((r) => r.cells.total)
    expect(totals[0]).toBe(totals[1]) // receipts side equals payments side
    const svc = generateReport(s, 'service-income', { range: fyRange(fyOf(TODAY)) })
    expect(svc.rows.at(-1)!.cells.amount).toBe(DEMO_EXPECTED.totalIncome)
    const cat = generateReport(s, 'expense-category', { range: fyRange(fyOf(TODAY)) })
    expect(cat.rows.at(-1)!.cells.amount).toBe(DEMO_EXPECTED.totalExpense)
    const os = generateReport(s, 'client-outstanding', { range: fyRange(fyOf(TODAY)) })
    expect(os.rows.at(-1)!.cells.outstanding).toBe(DEMO_EXPECTED.outstanding)
    const ms = generateReport(s, 'monthly-summary', { range: fyRange(fyOf(TODAY)) })
    expect(ms.rows.at(-1)!.cells.net).toBe(DEMO_EXPECTED.totalIncome - DEMO_EXPECTED.totalExpense)
    // dates in registers are in ascending order
    const dates = inc.rows.slice(0, -1).map((r) => String(r.cells.date))
    expect([...dates].sort()).toEqual(dates)
  })

  it('Excel export contains the same numbers as the report', async () => {
    const store = await demo()
    const data = generateReport(store.getSnapshot(), 'income-register', { range: fyRange(fyOf(TODAY)) })
    const bytes = await reportToXlsx(data, store.getSnapshot().profile)
    const wb = new ExcelJS.Workbook()
    await wb.xlsx.load(bytes.buffer as ArrayBuffer)
    const ws = wb.worksheets[0]
    const amounts: number[] = []
    let total: number | null = null
    ws.eachRow((row) => {
      const party = row.getCell(3).value
      const amt = row.getCell(8).value
      if (typeof amt !== 'number') return
      if (String(party).startsWith('Grand Total')) total = amt
      else amounts.push(amt)
    })
    expect(amounts).toHaveLength(3)
    expect(Math.round(amounts.reduce((a, b) => a + b, 0) * 100)).toBe(DEMO_EXPECTED.totalIncome)
    expect(total).toBe(DEMO_EXPECTED.totalIncome / 100)
  })

  it('PDF export renders report and receipt', async () => {
    const store = await demo()
    const s = store.getSnapshot()
    const data = generateReport(s, 'monthly-cashbook', { range: fyRange(fyOf(TODAY)) })
    const doc = await reportToPdf(data, s.profile, { compress: false })
    const text = doc.output()
    expect(text.startsWith('%PDF')).toBe(true)
    expect(doc.getNumberOfPages()).toBeGreaterThan(0)
    expect(text).toContain('11,400.00') // closing cash
    const t = s.transactions[0]
    const rec = await voucherPdf(t, s.profile, { partyName: 'Rakesh Sharma', category: 'GST Return Filing Fees', account: 'Cash in Hand' }, { compress: false })
    expect(rec.output()).toContain('Two Thousand Five Hundred')
  })
})
