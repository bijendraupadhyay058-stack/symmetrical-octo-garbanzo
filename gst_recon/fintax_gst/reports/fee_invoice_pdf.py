"""The firm's fee invoice (tax invoice when the firm is registered, else a bill of supply) on A4."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..core.gstin import STATE_CODES
from ..core.money import fmt_inr

NAVY, GRID, MUTED = colors.HexColor("#1F3864"), colors.HexColor("#D9DEE7"), colors.HexColor("#52514E")
_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
         "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _words_99(n: int) -> str:
    return _ONES[n] if n < 20 else (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else ""))


def _words(n: int) -> str:
    """Indian system: crore, lakh, thousand, hundred."""
    if n == 0:
        return "Zero"
    parts = []
    for div, name in ((10**7, "Crore"), (10**5, "Lakh"), (1000, "Thousand"), (100, "Hundred")):
        if n >= div:
            parts.append(f"{_words(n // div) if div == 10**7 else _words_99(n // div)} {name}")
            n %= div
    if n:
        parts.append(_words_99(n))
    return " ".join(parts)


def amount_in_words(v: Decimal) -> str:
    rupees, paise = int(v), int((v - int(v)) * 100)
    return f"Rupees {_words(rupees)}" + (f" and {_words_99(paise)} Paise" if paise else "") + " only"


def build_fee_invoice(prof, client, view, path: Path) -> Path:
    inv = view.inv
    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9, leading=12)
    small = ParagraphStyle("s", parent=body, fontSize=8, leading=10, textColor=MUTED)
    title = "TAX INVOICE" if prof.gstin else "BILL OF SUPPLY"
    story = [Paragraph(f"<b>{prof.name}</b>", ParagraphStyle("f", parent=ss["Title"], fontSize=15, textColor=NAVY,
                                                             alignment=0, spaceAfter=2)),
             Paragraph(prof.address.replace("\n", "<br/>"), body)]
    ids = " · ".join(x for x in (f"GSTIN {prof.gstin}" if prof.gstin else "", f"PAN {prof.pan}" if prof.pan else "",
                                 prof.email, prof.phone) if x)
    if ids:
        story.append(Paragraph(ids, small))
    story += [Spacer(1, 8), Paragraph(f"<b>{title}</b>" + ("" if prof.gstin else
                                                            " (the supplier is not registered under GST)"), body)]
    if inv.status == "cancelled":
        story.append(Paragraph("<font color='#C62828'><b>CANCELLED</b></font>", body))
    head = Table([[Paragraph(f"<b>Bill to</b><br/>{client.name}<br/>{(client.address or '').replace(chr(10), '<br/>')}"
                             f"<br/>GSTIN {client.gstin}<br/>State: {STATE_CODES.get(client.state_code, '')} "
                             f"({client.state_code})", body),
                   Paragraph(f"<b>Invoice no.</b> {inv.number}<br/><b>Date</b> {inv.invoice_date:%d-%m-%Y}<br/>"
                             + (f"<b>Due by</b> {inv.due_date:%d-%m-%Y}<br/>" if inv.due_date else "")
                             + (f"<b>Place of supply</b> {STATE_CODES.get(client.state_code, '')}" if prof.gstin
                                else ""), body)]], colWidths=[105 * mm, 75 * mm])
    head.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.4, GRID), ("INNERGRID", (0, 0), (-1, -1), 0.4, GRID),
                              ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [Spacer(1, 4), head, Spacer(1, 8)]
    rows = [["#", "Description" + (f" (SAC {inv.sac})" if inv.sac else ""), "Amount (Rs.)"]]
    for n, ln in enumerate(view.lines, start=1):
        rows.append([str(n), Paragraph(ln["text"], body), fmt_inr(Decimal(ln["amount"]))])
    rows.append(["", "Taxable value" if prof.gstin else "Total", fmt_inr(inv.taxable)])
    rate = Decimal(prof.gst_rate or 0)
    if inv.igst:
        rows.append(["", f"IGST @ {rate:g}%", fmt_inr(inv.igst)])
    if inv.cgst or inv.sgst:
        rows.append(["", f"CGST @ {rate / 2:g}%", fmt_inr(inv.cgst)])
        rows.append(["", f"SGST @ {rate / 2:g}%", fmt_inr(inv.sgst)])
    rows.append(["", "Invoice total", fmt_inr(inv.total)])
    t = Table(rows, colWidths=[10 * mm, 130 * mm, 40 * mm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, GRID), ("FONTSIZE", (0, 0), (-1, -1), 9),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF1F6")),
                           ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTNAME", (0, -1), (-1, -1),
                                                                            "Helvetica-Bold"),
                           ("ALIGN", (2, 0), (2, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [t, Spacer(1, 4), Paragraph(amount_in_words(inv.total), body)]
    if prof.gstin:
        story.append(Paragraph("Tax is not payable under reverse charge.", small))
    if prof.bank:
        story += [Spacer(1, 8), Paragraph("<b>Payment details</b><br/>" + prof.bank.replace("\n", "<br/>"), body)]
    if inv.notes:
        story += [Spacer(1, 6), Paragraph(inv.notes.replace("\n", "<br/>"), small)]
    story += [Spacer(1, 24), Paragraph(f"For {prof.name}<br/><br/><br/>Authorised signatory", body)]
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm,
                            bottomMargin=14 * mm, title=f"{inv.number} {client.name}")
    doc.build(story)
    return path
