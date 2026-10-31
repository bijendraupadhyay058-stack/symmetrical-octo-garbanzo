"""The GSTR-3B draft on one A4 page: the figures to enter on the portal and the cash to pay."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepInFrame, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..compliance.gstr3b_draft import HEADS
from ..core.money import ZERO, fmt_inr
from ..importers.gstr3b import TABLE4, TABLE31
from ..services.gstr3b_draft import Gstr3bDraft, state_label
from ..services.reminders import month_name

NAVY, GREY = colors.HexColor("#1F3864"), colors.HexColor("#5C6B80")
SHORT31 = {"31A": "(a) Outward taxable supplies (other than zero / nil / exempt)",
           "31B": "(b) Outward taxable supplies – zero rated", "31C": "(c) Other outward – nil rated, exempted",
           "31D": "(d) Inward supplies liable to reverse charge", "31E": "(e) Non-GST outward supplies"}
SHORT4 = {"4A1": "(A)(1) Import of goods", "4A2": "(A)(2) Import of services",
          "4A3": "(A)(3) Inward supplies under reverse charge", "4A4": "(A)(4) Inward supplies from ISD",
          "4A5": "(A)(5) All other ITC", "4B1": "(B)(1) Reversed – rules 38, 42, 43 & section 17(5)",
          "4B2": "(B)(2) Reversed – others", "4C": "(C) Net ITC available (A) − (B)",
          "4D1": "(D)(1) ITC reclaimed (reversed in 4(B)(2) earlier)",
          "4D2": "(D)(2) Ineligible – section 16(4) & place of supply"}


def _m(v) -> str:
    return fmt_inr(v) if v else "–"


def build_pdf(d: Gstr3bDraft, path: str | Path, firm: str = "", today: date | None = None) -> Path:
    today = today or date.today()
    ss = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=ss["Heading3"], textColor=NAVY, spaceBefore=5, spaceAfter=2, fontSize=10)
    small = ParagraphStyle("s", parent=ss["BodyText"], fontSize=7.5, leading=9.5, textColor=GREY)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=8, leading=10)

    def table(rows, widths):
        t = Table(rows, colWidths=widths)
        t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 7.5), ("GRID", (0, 0), (-1, -1), 0.3,
                                                                           colors.HexColor("#D9DEE7")),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF1F6")),
                               ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                               ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
        return t

    story = [Paragraph(f"<b>GSTR-3B draft – {month_name(d.period)}</b>", ParagraphStyle(
        "t", parent=ss["Title"], fontSize=14, textColor=NAVY, alignment=0, spaceAfter=1)),
        Paragraph(f"{d.client} · GSTIN {d.gstin}", body)]
    story.append(Paragraph("3.1 Outward supplies and inward supplies under reverse charge", h))
    rows = [["", "Taxable value", "IGST", "CGST", "SGST", "Cess"]]
    for code in TABLE31:
        v = d.t31[code]
        rows.append([SHORT31[code], _m(v.taxable), _m(v.igst), _m(v.cgst), _m(v.sgst), _m(v.cess)])
    story.append(table(rows, [76 * mm, 24 * mm, 22 * mm, 22 * mm, 22 * mm, 20 * mm]))
    if d.t32:
        story.append(Paragraph("3.2 Inter-state supplies to unregistered persons", h))
        story.append(table([["Place of supply", "Taxable value", "IGST"]] +
                           [[state_label(p), _m(t), _m(i)] for p, t, i in d.t32], [70 * mm, 30 * mm, 30 * mm]))
    story.append(Paragraph("4 Eligible ITC", h))
    rows = [["", "IGST", "CGST", "SGST", "Cess"]]
    for code in TABLE4:
        v = d.t4[code]
        rows.append([SHORT4[code], _m(v.igst), _m(v.cgst), _m(v.sgst), _m(v.cess)])
    story.append(table(rows, [100 * mm, 22 * mm, 22 * mm, 22 * mm, 20 * mm]))
    story.append(Paragraph(f"Basis: {d.t4_basis}", small))
    if d.t5["inter"] or d.t5["intra"]:
        story.append(Paragraph("5 Exempt, nil-rated and non-GST inward supplies", h))
        story.append(table([["", "Inter-state", "Intra-state"],
                            ["Purchases without tax", _m(d.t5["inter"]), _m(d.t5["intra"])]],
                           [70 * mm, 30 * mm, 30 * mm]))
    so = d.setoff
    story.append(Paragraph("6.1 Payment of tax", h))
    rows = [["Tax", "Payable", "Paid: IGST credit", "CGST credit", "SGST credit", "Cess credit", "Cash"]]
    for head in HEADS:
        paid = so.paid_by(head)
        rows.append([head.upper(), _m(so.liability[head] + so.rcm[head]),
                     *[_m(paid[c]) for c in HEADS], _m(so.cash[head])])
    rows.append(["Total", _m(sum((so.liability[h] + so.rcm[h] for h in HEADS), ZERO)),
                 *[_m(sum((so.paid_by(x)[c] for x in HEADS), ZERO)) for c in HEADS], _m(so.total_cash)])
    story.append(table(rows, [16 * mm, 26 * mm, 26 * mm, 24 * mm, 24 * mm, 22 * mm, 26 * mm]))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(f"<b>Cash to pay: Rs. {fmt_inr(so.total_cash)}</b> (reverse-charge tax is paid in cash). "
                           "Credit carried forward: " + ", ".join(f"{h.upper()} Rs. {fmt_inr(so.carried[h])}"
                                                                 for h in HEADS if so.carried[h]) + ".", body))
    for n in d.notes:
        story.append(Paragraph(f"• {n}", small))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(
        f"Draft prepared{' by ' + firm if firm else ''} on {today:%d-%m-%Y} from the data imported into FIN TAX PRO. "
        "ITC set-off as per section 49(5) and rule 88A (IGST credit first). Interest and late fee, if any, are not "
        "included. Check against the portal before filing.", small))
    out = Path(path)
    doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=10 * mm,
                            bottomMargin=10 * mm, title=f"GSTR-3B draft {d.period} – {d.client}")
    doc.build([KeepInFrame(doc.width, doc.height, story, mode="shrink")])
    return out
