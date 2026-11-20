"""Year-end closing pack (PDF) with an index of its sections and page numbers."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.platypus.tableofcontents import TableOfContents

from ..core.money import ZERO, fmt_inr

NAVY, GRID, MUTED = colors.HexColor("#1F3864"), colors.HexColor("#D9DEE7"), colors.HexColor("#52514E")
RAG = {"red": colors.HexColor("#FFCDD2"), "amber": colors.HexColor("#FFF3C4"), "green": colors.HexColor("#C8E6C9")}


class _Doc(SimpleDocTemplate):
    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name == "Section":
            self.notify("TOCEntry", (0, flowable.getPlainText(), self.page))


def _t(text) -> str:
    """Text for the PDF font, which has no rupee sign."""
    return str(text or "").replace("₹", "Rs. ").replace("&", "&amp;").replace("<", "&lt;")


def _m(v) -> str:
    return "–" if v is None else fmt_inr(v)


def _table(rows, widths, money_from: int = 1, colours=None):
    t = Table(rows, colWidths=widths, repeatRows=1)
    style = [("FONTSIZE", (0, 0), (-1, -1), 7.5), ("GRID", (0, 0), (-1, -1), 0.3, GRID),
             ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF1F6")), ("FONTNAME", (0, 0), (-1, 0),
                                                                             "Helvetica-Bold"),
             ("ALIGN", (money_from, 1), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
    for r, c in (colours or {}).items():
        style.append(("BACKGROUND", (0, r), (-1, r), c))
    t.setStyle(TableStyle(style))
    return t


def build_closing_pdf(d, path: Path, firm: str = "") -> Path:
    from ..itc.claim_plan import BARRED, CLAIM, HOLD, WRITTEN_OFF

    ss = getSampleStyleSheet()
    sec = ParagraphStyle("Section", parent=ss["Heading2"], textColor=NAVY, fontSize=12, spaceBefore=4, spaceAfter=4,
                         keepWithNext=1)  # a heading never stays alone at the foot of a page
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=8.5, leading=11)
    small = ParagraphStyle("s", parent=body, fontSize=7.5, leading=9.5, textColor=MUTED)
    cell = ParagraphStyle("c", parent=body, fontSize=7.5, leading=9)
    story = [Spacer(1, 30 * mm),
             Paragraph(f"<b>Year-end GST pack – FY {d.fy}</b>", ParagraphStyle("t", parent=ss["Title"], fontSize=20,
                                                                              textColor=NAVY, alignment=0)),
             Paragraph(f"{_t(d.client.name)}<br/>GSTIN {d.client.gstin}", ParagraphStyle("c2", parent=body, fontSize=12,
                                                                                     leading=16)),
             Spacer(1, 6), Paragraph(f"Prepared on {d.as_of:%d-%m-%Y}" + (f" by {_t(firm)}" if firm else ""), body),
             Spacer(1, 14), Paragraph("<b>Contents</b>", body)]
    toc = TableOfContents()
    toc.levelStyles = [ParagraphStyle("toc", parent=body, fontSize=10, leading=15)]
    story += [toc]
    if d.gaps:
        story += [Spacer(1, 10), Paragraph("Parts not prepared:", small)] + [Paragraph(f"• {_t(g)}", small) for g in d.gaps]
    story.append(PageBreak())

    # 1. status by month
    story.append(Paragraph("1. Compliance status by month", sec))
    if d.compliance is None:
        story.append(Paragraph("Not available.", body))
    else:
        rows = [["Month", "Status", "Purchases", "GSTR-2B", "Sales", "GSTR-3B", "Issues"]]
        colours = {}
        for i, m in enumerate(d.compliance.months, start=1):
            rows.append([m.period, m.rag.upper(), m.purchase_docs, m.gstr2b_docs, m.sales_docs,
                         "yes" if m.gstr3b_imported else "–",
                         Paragraph(_t("; ".join(t for _r, t in m.issues)[:300]), cell)])
            if m.rag in RAG:
                colours[i] = RAG[m.rag]
        story.append(_table(rows, [16 * mm, 15 * mm, 18 * mm, 17 * mm, 14 * mm, 15 * mm, 87 * mm], 2, colours))

    # 2. GSTR-9
    story.append(Paragraph("2. GSTR-9 working (returns vs books)", sec))
    if d.gstr9 is None:
        story.append(Paragraph("Not available.", body))
    else:
        rows = [["Table", "Description", "Returns taxable", "Returns tax", "Books tax", "Difference"]]
        for r in d.gstr9.table4 + d.gstr9.table5 + d.gstr9.table6 + d.gstr9.table7:
            g, b = r.gstr1, r.books
            if g is None and b is None:
                continue
            diff = r.diff
            rows.append([r.code, Paragraph(_t(r.label[:110]), cell), _m(g.taxable if g else None),
                         _m(g.total if g else None), _m(b.total if b else None), _m(diff.total if diff else None)])
        story.append(_table(rows, [14 * mm, 84 * mm, 22 * mm, 21 * mm, 20 * mm, 21 * mm], 2))
        if d.gstr9.table9:
            rows = [["Tax", "Payable (4N)", "Declared in 3B", "Paid in cash", "Paid through ITC"]]
            for t in d.gstr9.table9:
                rows.append([t.head.upper(), _m(t.payable), _m(t.declared), _m(t.paid_cash), _m(t.paid_itc)])
            story += [Spacer(1, 4), Paragraph("Table 9 – tax payable and paid", body),
                      _table(rows, [20 * mm, 40 * mm, 40 * mm, 40 * mm, 42 * mm])]

    # 3. GSTR-9C
    story.append(Paragraph("3. GSTR-9C reconciliation – summary", sec))
    if d.gstr9c is None:
        story.append(Paragraph("Not available.", body))
    else:
        rows = [["Table", "Description", "Amount", "Source"]]
        for ln in d.gstr9c.table5 + d.gstr9c.table7 + d.gstr9c.table12:
            if ln.code in ("5A", "5P", "5Q", "5R", "7E", "7F", "7G", "12D", "12E", "12F"):
                rows.append([ln.code, Paragraph(_t(ln.label[:110]), cell), _m(ln.amount), Paragraph(_t(ln.source), cell)])
        story.append(_table(rows, [14 * mm, 100 * mm, 28 * mm, 40 * mm], 2))
        if d.gstr9c.notes:
            story += [Paragraph(f"• {_t(n)}", small) for n in d.gstr9c.notes[:6]]

    # 4. Table 8
    story.append(Paragraph("4. ITC as per GSTR-2B and as availed (GSTR-9 Table 8)", sec))
    if d.table8 is None:
        story.append(Paragraph("Not available.", body))
    else:
        t8 = d.table8
        rows = [["", "IGST", "CGST", "SGST", "Cess", "Total"]]
        for label, v in (("8A ITC as per GSTR-2B", t8.a), ("8B ITC availed (6B + 6H)", t8.b),
                         ("8C ITC of the year availed next year", t8.c), ("8D Difference A − (B + C)", t8.d)):
            rows.append([label, _m(v.igst), _m(v.cgst), _m(v.sgst), _m(v.cess), _m(v.total)])
        story.append(_table(rows, [62 * mm, 24 * mm, 24 * mm, 24 * mm, 20 * mm, 28 * mm]))
        story.append(Paragraph(f"Cut-off for ITC of the year availed in the next year: {t8.cutoff}.", small))

    # 5. claim plan
    story.append(Paragraph("5. ITC not yet claimed at the year end", sec))
    if d.plan is None:
        story.append(Paragraph("Not available.", body))
    else:
        p = d.plan
        rows = [["", "Documents", "ITC"]] + [[b, len(p.bucket(b)), _m(p.total(b))]
                                            for b in (CLAIM, HOLD, BARRED, WRITTEN_OFF)]
        story.append(_table(rows, [60 * mm, 30 * mm, 40 * mm]))
        items = [ln for ln in p.lines if ln.bucket in (HOLD, BARRED)][:40]
        if items:
            rows = [["Plan", "Supplier", "Invoice", "Date", "ITC", "Last date"]]
            for ln in items:
                rows.append([ln.bucket, Paragraph(_t((ln.doc.supplier_name or ln.doc.supplier_gstin)[:40]), cell),
                             ln.doc.invoice_no, f"{ln.doc.invoice_date:%d-%m-%Y}", _m(ln.itc),
                             f"{ln.deadline:%d-%m-%Y}" if ln.deadline else "–"])
            story += [Spacer(1, 4), _table(rows, [20 * mm, 62 * mm, 30 * mm, 22 * mm, 24 * mm, 24 * mm], 4)]
            more = len([ln for ln in p.lines if ln.bucket in (HOLD, BARRED)]) - len(items)
            if more > 0:
                story.append(Paragraph(f"… and {more} more – see the Excel file.", small))

    # 6. interest and late fee
    story.append(Paragraph("6. Interest and late fee", sec))
    if d.interest is None:
        story.append(Paragraph("Not available.", body))
    else:
        w = d.interest
        late = [r for r in w.late if r.days > 0]
        if late:
            rows = [["Return", "Period", "Due", "Filed", "Days late", "Interest", "Late fee"]]
            for r in late:
                rows.append([r.return_type, r.period, f"{r.due:%d-%m-%Y}", f"{r.filed:%d-%m-%Y}" if r.filed else "–",
                             r.days, _m(r.interest_total), _m(r.fee_total)])
            story.append(_table(rows, [20 * mm, 20 * mm, 24 * mm, 24 * mm, 20 * mm, 36 * mm, 36 * mm], 4))
        else:
            story.append(Paragraph("No return filed late (as recorded).", body))
        open_exp = [e for e in w.exposures if e.status == "OPEN"]
        if open_exp:
            total = sum((e.interest for e in open_exp), ZERO)
            story.append(Paragraph(f"Open short payments / excess ITC: {len(open_exp)} item(s), interest "
                                   f"Rs. {fmt_inr(total)} up to {w.as_of:%d-%m-%Y}.", body))
        story += [Paragraph(f"• {_t(n)}", small) for n in w.notes[:5]]

    # 7. notices
    story.append(Paragraph("7. Open GST notices", sec))
    if d.notices:
        rows = [["Form", "Reference", "Date", "Period", "Amount", "Reply due", "Status"]]
        for n in d.notices:
            rows.append([n.form, Paragraph(_t(n.reference), cell), f"{n.notice_date:%d-%m-%Y}",
                         f"{n.period_from}..{n.period_to}", _m(n.amount),
                         f"{n.reply_due:%d-%m-%Y}" if n.reply_due else "–", n.status])
        story.append(_table(rows, [18 * mm, 40 * mm, 20 * mm, 30 * mm, 26 * mm, 22 * mm, 26 * mm], 4))
    else:
        story.append(Paragraph("No open notices.", body))

    # 8. suppliers
    story.append(Paragraph("8. Suppliers with ITC at risk", sec))
    if d.suppliers:
        rows = [["Supplier", "GSTIN", "ITC at risk", "Docs not in 2B", "Risk"]]
        for x in d.suppliers:
            rows.append([Paragraph(_t(x.name[:50]), cell), x.gstin, _m(x.itc_at_risk), x.missing_docs, x.band])
        story.append(_table(rows, [66 * mm, 36 * mm, 30 * mm, 26 * mm, 24 * mm], 2))
    else:
        story.append(Paragraph("No supplier with ITC at risk.", body))
    story += [Spacer(1, 10), Paragraph("Prepared from the client's data in FIN TAX PRO. A working pack for review and "
                                       "the audit file – not a return as filed.", small)]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(14 * mm, 8 * mm, f"{d.client.name} · FY {d.fy} · year-end GST pack")
        canvas.drawRightString(196 * mm, 8 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = _Doc(str(path), pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm,
               bottomMargin=14 * mm, title=f"Year-end GST pack {d.client.name} {d.fy}")
    doc.multiBuild(story, onFirstPage=footer, onLaterPages=footer)
    return path


__all__ = ["build_closing_pdf", "Decimal"]
