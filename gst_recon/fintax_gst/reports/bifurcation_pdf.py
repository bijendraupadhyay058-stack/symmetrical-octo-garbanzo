"""Ledger bifurcation review PDF: readiness, summaries by accounting group and GST class, GSTR-9 Table 6 and
GSTR-9C Table 14 workings and the exceptions – for the accountant's / CA's review."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..core.money import fmt_inr
from ..ledgers.classify import GST_CLASSES

NAVY = colors.HexColor("#1F3864")


def _t(text: str) -> str:
    return text.replace("₹", "Rs. ").replace("&", "&amp;").replace("<", "&lt;")


def _m(v) -> str:
    return "" if v is None else fmt_inr(v)


def _table(head, rows, widths):
    t = Table([head] + rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                           ("FONTSIZE", (0, 0), (-1, -1), 7.5), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                           ("ALIGN", (1, 1), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def build_pdf(sm, path: Path, firm: str = "") -> Path:
    from ..services.bifurcation import T6_LABEL, TABLE14_STATUS

    st = getSampleStyleSheet()
    h = st["Heading2"]
    h.keepWithNext = True
    body = st["BodyText"]
    body.fontSize = 8.5
    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm, title=f"Ledger bifurcation {sm.fy}")
    ok, reasons = sm.ready
    story = [Paragraph(_t(f"{sm.client} ({sm.gstin}) – Ledger classification &amp; bifurcation, FY {sm.fy}"),
                       st["Title"]),
             Paragraph(_t(f"{firm + ' · ' if firm else ''}Prepared {date.today():%d-%m-%Y} · working paper for review; "
                          "nothing is filed by FIN TAX PRO."), body), Spacer(1, 4),
             Paragraph(_t("<b>Ready for GSTR-9 / 9C working</b>" if ok else "<b>NOT READY</b> – " + "; ".join(reasons)),
                       body), Spacer(1, 6)]
    story.append(Paragraph("Review indicators", h))
    story.append(_table(["Indicator", "Value"], [
        ["Ledgers imported", str(len(sm.views))], ["Ledgers to classify", str(len(sm.in_scope))],
        ["Approved", str(sm.count("Approved"))], ["Suggested, not approved", str(sm.count("Suggested"))],
        ["Pending", str(sm.count("Pending"))], ["Parts with eligible ITC but no GST", str(sm.missing_gst)],
        ["Unallocated amount", _t("Rs. " + _m(sm.unallocated))],
        ["Trial balance debit / credit", _t(f"Rs. {_m(sm.tb_debit)} / Rs. {_m(sm.tb_credit)}")]],
        [90 * mm, 60 * mm]))
    story.append(Paragraph("By accounting group and GST classification", h))
    rows = [[g, _m(t.value)] for g, t in sorted(sm.by_group.items())]
    rows += [[f"GST: {t.label}", _m(t.value), _m(t.tax)] for t in sm.by_gst.values() if t.value]
    story.append(_table(["Classification", "Amount", "GST"], [r + [""] * (3 - len(r)) for r in rows],
                        [90 * mm, 40 * mm, 40 * mm]))
    story.append(Paragraph("GSTR-9 Table 6 – ITC availed by category (from the classified parts)", h))
    rows = []
    for (row, g), t in sorted(sm.table6.items()):
        rows.append([T6_LABEL.get(row, row), GST_CLASSES[g], _m(t.taxable), _m(t.igst), _m(t.cgst), _m(t.sgst),
                     _m(t.cess), _m(t.tax)])
    d = sm.difference_6b
    if d is not None:
        rows.append(["6B: difference from GSTR-3B 4(A)(5)", "", "", *(_m(d[x]) for x in ("igst", "cgst", "sgst",
                                                                                           "cess")), _m(sum(d.values()))])
    story.append(_table(["Row", "Category", "Taxable", "IGST", "CGST", "SGST", "Cess", "Total"], rows or [["–"] * 8],
                        [80 * mm, 28 * mm, 26 * mm, 24 * mm, 24 * mm, 24 * mm, 20 * mm, 26 * mm]))
    story.append(Paragraph("GSTR-9C Table 14 – ITC on expenses", h))
    rows = [[r.code + " " + r.label[:40], _m(r.value), _m(r.gst), _m(r.eligible), _m(r.ineligible), _m(r.availed),
             _m(r.reversed), _m(r.difference)] for r in sm.table14 if r.value or r.gst]
    story.append(_table(["Head", "Value", "GST charged", "Eligible", "Ineligible", "Availed", "Reversed",
                         "Difference"], rows or [["–"] * 8],
                        [80 * mm, 26 * mm, 24 * mm, 24 * mm, 24 * mm, 24 * mm, 22 * mm, 24 * mm]))
    story.append(Paragraph(_t(TABLE14_STATUS), body))
    if sm.exceptions:
        story.append(Paragraph("Differences and exceptions", h))
        story.append(_table(["", "Ledger", "Exception"], [[s.upper(), Paragraph(_t(lg), body), Paragraph(_t(x), body)]
                                                          for s, lg, x in sm.exceptions[:300]],
                            [14 * mm, 70 * mm, 180 * mm]))
    doc.build(story)
    return path
