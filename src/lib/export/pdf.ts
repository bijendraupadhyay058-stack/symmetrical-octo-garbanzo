import type { jsPDF } from 'jspdf'
import { formatDate, formatDateTime } from '../dates'
import { amountInWords, formatAmount } from '../money'
import type { BusinessProfile, Transaction } from '../types'
import { paymentMethodLabel } from '../types'
import type { ReportData, RowStyle } from '../reports/types'
import { cellText } from './format'

const NAVY: [number, number, number] = [11, 37, 69]

export interface PdfOptions {
  /** Disable stream compression (used by tests to read the text). */
  compress?: boolean
}

async function newDoc(landscape: boolean, opts: PdfOptions = {}): Promise<jsPDF> {
  const { jsPDF } = await import('jspdf')
  return new jsPDF({ orientation: landscape ? 'landscape' : 'portrait', unit: 'pt', format: 'a4', compress: opts.compress ?? true })
}

function imageFormat(dataUrl: string): string {
  if (dataUrl.startsWith('data:image/png')) return 'PNG'
  if (dataUrl.startsWith('data:image/webp')) return 'WEBP'
  return 'JPEG'
}

/** Letterhead; returns the y position below it. */
function letterhead(doc: jsPDF, profile: BusinessProfile | null): number {
  const w = doc.internal.pageSize.getWidth()
  let x = 40
  if (profile?.logo_data_url) {
    try {
      doc.addImage(profile.logo_data_url, imageFormat(profile.logo_data_url), 40, 28, 44, 44)
      x = 94
    } catch {
      /* ignore an unreadable logo */
    }
  }
  doc.setTextColor(...NAVY)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(16)
  doc.text(profile?.name || 'FIN TAX PRO', x, 44)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8.5)
  doc.setTextColor(80)
  const sub = [profile?.tagline, profile?.address, [profile?.phone && `Ph: ${profile.phone}`, profile?.email, profile?.gstin && `GSTIN: ${profile.gstin}`].filter(Boolean).join('  |  ')]
    .filter(Boolean) as string[]
  let y = 57
  for (const s of sub) {
    const lines = doc.splitTextToSize(s, w - x - 40) as string[]
    doc.text(lines, x, y)
    y += lines.length * 10
  }
  y = Math.max(y, 78)
  doc.setDrawColor(...NAVY)
  doc.setLineWidth(1.2)
  doc.line(40, y, w - 40, y)
  return y + 16
}

function footer(doc: jsPDF) {
  const pages = doc.getNumberOfPages()
  const w = doc.internal.pageSize.getWidth()
  const h = doc.internal.pageSize.getHeight()
  for (let i = 1; i <= pages; i++) {
    doc.setPage(i)
    doc.setFontSize(7.5)
    doc.setTextColor(130)
    doc.text(`Generated ${formatDateTime(new Date().toISOString())} · FIN TAX PRO – CashBook`, 40, h - 20)
    doc.text(`Page ${i} of ${pages}`, w - 40, h - 20, { align: 'right' })
  }
}

export async function reportToPdf(report: ReportData, profile: BusinessProfile | null, opts: PdfOptions = {}): Promise<jsPDF> {
  const { autoTable } = await import('jspdf-autotable')
  const landscape = report.columns.length > 6
  const doc = await newDoc(landscape, opts)
  const w = doc.internal.pageSize.getWidth()
  let y = letterhead(doc, profile)
  doc.setTextColor(20)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(12.5)
  doc.text(report.title, 40, y)
  y += 14
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  doc.text(`Period: ${report.period}    (Amounts in Rs.)`, 40, y)
  y += 12
  if (report.note) {
    doc.setFontSize(7.8)
    doc.setTextColor(90)
    const lines = doc.splitTextToSize(report.note, w - 80) as string[]
    doc.text(lines, 40, y)
    y += lines.length * 9 + 2
  }
  if (report.summary?.length) {
    doc.setFontSize(8.5)
    doc.setTextColor(20)
    const s = report.summary.map((i) => `${i.label}: ${i.kind === 'count' ? i.value : 'Rs. ' + formatAmount(i.value)}`).join('     ')
    doc.text(doc.splitTextToSize(s, w - 80) as string[], 40, y + 2)
    y += 14
  }

  const totalW = report.columns.reduce((s, c) => s + (c.width ?? (c.type === 'money' ? 1.3 : 1.2)), 0)
  const avail = w - 80
  const styleFor: Partial<Record<RowStyle, { fillColor?: [number, number, number]; fontStyle?: 'bold' | 'italic'; textColor?: number }>> = {
    heading: { fillColor: [232, 238, 246], fontStyle: 'bold' },
    subtotal: { fillColor: [241, 244, 248], fontStyle: 'bold' },
    total: { fillColor: [220, 230, 242], fontStyle: 'bold' },
    opening: { fillColor: [247, 249, 252], fontStyle: 'bold' },
    muted: { textColor: 140, fontStyle: 'italic' },
  }
  autoTable(doc, {
    startY: y + 4,
    margin: { left: 40, right: 40, bottom: 36 },
    head: [report.columns.map((c) => c.label)],
    body: report.rows.map((r) =>
      report.columns.map((c) => ({ content: cellText(c, r.cells[c.key]), styles: styleFor[r.style ?? 'normal'] ?? {} })),
    ),
    theme: 'grid',
    styles: { fontSize: landscape ? 7.6 : 8, cellPadding: 3, lineColor: [215, 222, 232], lineWidth: 0.4, overflow: 'linebreak', textColor: 30 },
    headStyles: { fillColor: NAVY, textColor: 255, fontStyle: 'bold', halign: 'left' },
    columnStyles: Object.fromEntries(
      report.columns.map((c, i) => [
        i,
        { halign: c.type === 'money' || c.type === 'number' ? 'right' : 'left', cellWidth: (avail * (c.width ?? (c.type === 'money' ? 1.3 : 1.2))) / totalW },
      ]),
    ),
    didParseCell: (data) => {
      const col = report.columns[data.column.index]
      if (data.section === 'head' && (col.type === 'money' || col.type === 'number')) data.cell.styles.halign = 'right'
    },
  })
  footer(doc)
  return doc
}

/** Printable receipt / payment voucher for one transaction (used for sharing). */
export async function voucherPdf(
  t: Transaction,
  profile: BusinessProfile | null,
  info: { partyName: string; partyFirm?: string; category: string; account: string; toAccount?: string; billNos?: string[] },
  opts: PdfOptions = {},
): Promise<jsPDF> {
  const doc = await newDoc(false, opts)
  const w = doc.internal.pageSize.getWidth()
  let y = letterhead(doc, profile)
  const title = t.type === 'income' ? 'RECEIPT' : t.type === 'expense' ? 'PAYMENT VOUCHER' : 'CONTRA VOUCHER'
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(15)
  doc.setTextColor(...NAVY)
  doc.text(title, w / 2, y + 6, { align: 'center' })
  y += 26
  if (t.status === 'cancelled') {
    doc.setTextColor(200, 30, 30)
    doc.setFontSize(28)
    doc.text('CANCELLED', w / 2, y + 140, { align: 'center', angle: 20 })
  }
  doc.setFontSize(10)
  doc.setTextColor(20)
  doc.setFont('helvetica', 'normal')
  doc.text(`Voucher No: ${t.voucher_no}`, 40, y)
  doc.text(`Date: ${formatDate(t.txn_date)}`, w - 40, y, { align: 'right' })
  y += 22
  const rows: [string, string][] = []
  if (t.type === 'income') {
    rows.push(['Received from', info.partyName + (info.partyFirm ? ` (${info.partyFirm})` : '')])
    rows.push(['Towards', info.category + (t.service ? ` – ${t.service}` : '')])
    if (info.billNos?.length) rows.push(['Against bill(s)', info.billNos.join(', ')])
  } else if (t.type === 'expense') {
    rows.push(['Paid to', info.partyName])
    rows.push(['Towards', info.category])
  } else {
    rows.push(['From account', info.account])
    rows.push(['To account', info.toAccount ?? ''])
  }
  rows.push(['Amount', `Rs. ${formatAmount(t.amount_paise)}`])
  rows.push(['In words', amountInWords(t.amount_paise)])
  rows.push(['Mode', paymentMethodLabel(t.payment_method) + (t.type !== 'contra' ? ` (${info.account})` : '')])
  if (t.reference_no) rows.push(['Reference No.', t.reference_no])
  if (t.narration) rows.push(['Narration', t.narration])
  const { autoTable } = await import('jspdf-autotable')
  autoTable(doc, {
    startY: y,
    margin: { left: 40, right: 40 },
    body: rows,
    theme: 'grid',
    styles: { fontSize: 10.5, cellPadding: 6, lineColor: [215, 222, 232], lineWidth: 0.5 },
    columnStyles: { 0: { fontStyle: 'bold', cellWidth: 130, fillColor: [244, 247, 251] } },
  })
  const lastY = (doc as unknown as { lastAutoTable: { finalY: number } }).lastAutoTable.finalY
  doc.setFontSize(9)
  doc.text('Authorised Signatory', w - 40, lastY + 60, { align: 'right' })
  doc.setFontSize(8)
  doc.setTextColor(120)
  doc.text(profile?.settings?.receipt_footer || 'This is a computer-generated receipt.', 40, lastY + 60)
  footer(doc)
  return doc
}
