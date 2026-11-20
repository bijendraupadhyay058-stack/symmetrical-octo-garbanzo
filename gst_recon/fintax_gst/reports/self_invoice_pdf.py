"""Self-invoices for reverse-charge purchases from unregistered suppliers (section 31(3)(f), rule 46)."""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..core.gstin import STATE_CODES
from ..core.models import fy_of
from ..core.money import fmt_inr
from .fee_invoice_pdf import amount_in_words

NAVY, GRID = colors.HexColor("#1F3864"), colors.HexColor("#D9DEE7")


def _t(text) -> str:
    return str(text or "").replace("₹", "Rs. ").replace("&", "&amp;").replace("<", "&lt;")


def build_self_invoices(client, lines, path: Path, first_number: int = 1, prefix: str = "SI") -> Path:
    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9, leading=12)
    small = ParagraphStyle("s", parent=body, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#52514E"))
    story = []
    for n, ln in enumerate(lines, start=first_number):
        d = ln.doc
        number = f"{prefix}/{fy_of(d.invoice_date)}/{n:04d}"
        story += [Paragraph(f"<b>{_t(client.name)}</b>", ParagraphStyle("t", parent=ss["Title"], fontSize=14,
                                                                        textColor=NAVY, alignment=0, spaceAfter=2)),
                  Paragraph(_t(client.address).replace("\n", "<br/>") + f"<br/>GSTIN {client.gstin}", body),
                  Spacer(1, 6),
                  Paragraph("<b>SELF-INVOICE</b> (tax payable on reverse charge – section 31(3)(f) of the CGST Act)",
                            body), Spacer(1, 4)]
        head = Table([[Paragraph(f"<b>Supplier (unregistered)</b><br/>{_t(d.supplier_name) or '—'}", body),
                       Paragraph(f"<b>Self-invoice no.</b> {number}<br/><b>Date</b> {d.invoice_date:%d-%m-%Y}<br/>"
                                 f"<b>Supplier's bill</b> {_t(d.invoice_no)}<br/><b>Place of supply</b> "
                                 f"{_t(d.place_of_supply) or STATE_CODES.get(client.state_code, '')}", body)]],
                     colWidths=[95 * mm, 85 * mm])
        head.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.4, GRID), ("INNERGRID", (0, 0), (-1, -1), 0.4, GRID),
                                  ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        rows = [["Description", "Taxable value", "IGST", "CGST", "SGST", "Cess"],
                [Paragraph(_t(d.description or ln.service or "Supply under reverse charge"), body), fmt_inr(d.taxable),
                 fmt_inr(d.igst), fmt_inr(d.cgst), fmt_inr(d.sgst), fmt_inr(d.cess)]]
        total = d.taxable + d.igst + d.cgst + d.sgst + d.cess
        t = Table(rows, colWidths=[70 * mm, 26 * mm, 21 * mm, 21 * mm, 21 * mm, 21 * mm])
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, GRID), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF1F6")),
                               ("ALIGN", (1, 0), (-1, -1), "RIGHT")]))
        story += [head, Spacer(1, 8), t, Spacer(1, 4),
                  Paragraph(f"Total Rs. {fmt_inr(total)} – {amount_in_words(total)}", body),
                  Paragraph(f"Tax payable on reverse charge: Rs. {fmt_inr(d.igst + d.cgst + d.sgst + d.cess)}", body),
                  Spacer(1, 30), Paragraph(f"For {_t(client.name)}<br/><br/><br/>Authorised signatory", body),
                  Spacer(1, 10), Paragraph("Draft prepared by FIN TAX PRO – check the number series continues from "
                                           "your last self-invoice before signing.", small), PageBreak()]
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm,
                            bottomMargin=14 * mm, title=f"Self-invoices {client.name}")
    doc.build(story[:-1])
    return path
