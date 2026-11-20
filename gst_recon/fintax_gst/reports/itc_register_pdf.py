"""ITC classification review PDF: overview, Table 6 against GSTR-3B, 9C Table 12, possible reasons (Table 13) and
the controls."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..core.money import fmt_inr
from ..ledgers.itc_classes import NATURES

NAVY = colors.HexColor("#1F3864")


def _t(text: str) -> str:
    return str(text).replace("₹", "Rs. ").replace("&", "&amp;").replace("<", "&lt;")


def _m(v) -> str:
    return "" if v is None else fmt_inr(v)


def _table(head, rows, widths):
    t = Table([head] + rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                           ("FONTSIZE", (0, 0), (-1, -1), 7.5), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                           ("ALIGN", (1, 1), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def build_pdf(w, path: Path, firm: str = "") -> Path:
    from ..services.itc_register import T6_ROWS

    st = getSampleStyleSheet()
    h = st["Heading2"]
    h.keepWithNext = True
    body = st["BodyText"]
    body.fontSize = 8.5
    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm, title=f"ITC classification {w.fy}")
    story = [Paragraph(_t(f"{w.client} ({w.gstin}) – ITC classification &amp; reconciliation, FY {w.fy}"),
                       st["Title"]),
             Paragraph(_t(f"{firm + ' · ' if firm else ''}Prepared {date.today():%d-%m-%Y} · "
                          + (f"FINAL – {w.final['by']} on {w.final['on']}" if w.final else "working paper, not final")
                          + " · nothing is filed by FIN TAX PRO."), body), Spacer(1, 6)]
    story.append(Paragraph("Classification overview", h))
    story.append(_table(["Nature", "Transactions", "Taxable", "Tax"],
                        [[NATURES[k], str(b.count), _m(b.taxable), _m(b.tax)] for k, b in w.by_nature.items()],
                        [70 * mm, 30 * mm, 40 * mm, 40 * mm]))
    from ..ledgers.itc_classes import CLAIMS, STATUSES

    story.append(Paragraph("Eligibility and claim (kept apart)", h))
    elig, claims = list(STATUSES), list(CLAIMS)
    rows = []
    for i in range(max(len(elig), len(claims))):
        a = elig[i] if i < len(elig) else None
        b = claims[i] if i < len(claims) else None
        rows.append([STATUSES[a] if a else "", _m(w.by_status[a].tax) if a else "", "",
                     CLAIMS[b] if b else "", _m(w.by_claim[b].tax) if b and b in w.by_claim else ""])
    story.append(_table(["ITC eligibility", "Tax", "", "ITC claim (GSTR-3B)", "Tax"], rows,
                        [70 * mm, 30 * mm, 8 * mm, 70 * mm, 30 * mm]))
    story.append(Paragraph("GSTR-9 Table 6 (ITC claimed) against GSTR-3B", h))
    rows = []
    for row, label in T6_ROWS.items():
        ours = sum((b.tax for b in w.table6[row].values()), Decimal(0))
        b3 = w.table6_3b.get(row)
        theirs = sum(b3.values(), Decimal(0)) if b3 else None
        rows.append([label, _m(w.table6[row]["inputs"].tax), _m(w.table6[row]["services"].tax),
                     _m(w.table6[row]["capital"].tax), _m(ours), _m(theirs),
                     "" if theirs is None else _m(ours - theirs)])
    story.append(_table(["Row", "Inputs", "Input services", "Capital goods", "Register", "GSTR-3B", "Difference"],
                        rows, [80 * mm, 26 * mm, 26 * mm, 26 * mm, 28 * mm, 28 * mm, 28 * mm]))
    story.append(Paragraph(_t("6C and 6D together are compared with GSTR-3B 4(A)(3)."), body))
    story.append(Paragraph("GSTR-9C Table 12", h))
    story.append(_table(["Row", "Particulars", "Amount", "Source"],
                        [[c, Paragraph(_t(lbl), body), _m(a), s] for c, lbl, a, s in w.table12],
                        [14 * mm, 120 * mm, 34 * mm, 50 * mm]))
    story.append(Paragraph(_t("GSTR-9C Table 14: " + w.table14_status), body))
    if w.table13:
        story.append(Paragraph("Possible reasons for differences (Table 13)", h))
        story.append(_table(["Reason", "Amount", "Evidence"], [[r, _m(a), e] for r, a, e in w.table13],
                            [110 * mm, 34 * mm, 70 * mm]))
    story.append(Paragraph("Controls", h))
    story.append(_table(["Control", "Status", "Detail"],
                        [[Paragraph(_t(f"{c.code} {c.title}"), body), c.status.upper(), Paragraph(_t(c.detail), body)]
                         for c in w.controls], [80 * mm, 18 * mm, 160 * mm]))
    doc.build(story)
    return path
