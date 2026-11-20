"""One-page monthly GST summary for the client (PDF).

Plain language, one A4 page: the month's ITC position (books, GSTR-2B, GSTR-3B), output tax, the
suppliers to follow up, the returns' status and what is still needed from the client. Every figure comes
from the data imported into FIN TAX PRO; the page says so and is a working summary, not a certificate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepInFrame, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..core.models import fy_of
from ..core.money import ZERO, fmt_inr
from ..db.database import Database
from ..engine.summary import dashboard, supplier_summary
from ..importers.parsing import parse_period
from ..services.common import ServiceError

NAVY, TEAL, GREY = colors.HexColor("#1F3864"), colors.HexColor("#00897B"), colors.HexColor("#5C6B80")
MAX_SUPPLIERS = 8


def _rs(v: Decimal | None) -> str:
    return "–" if v is None else "Rs. " + fmt_inr(v)


@dataclass
class _Month:
    """Everything one page needs, gathered once (firm-wide data is shared when many pages are made)."""

    work: object  # services.firm.FirmWork
    requests: dict  # client id -> ClientRequest


def _gather(db: Database, period: str, today: date) -> _Month:
    from ..services.firm import FirmService
    from ..services.reminders import ReminderService

    return _Month(FirmService(db).work(period, today),
                  {r.client_id: r for r in ReminderService(db).requests(period, only_needed=False)})


def build_client_report(db: Database, client_id: int, period: str, out_dir: str | Path, firm_name: str = "",
                        today: date | None = None, _month: _Month | None = None) -> Path:
    from ..services.compliance import ComplianceService
    from ..services.reconciliation import ReconciliationService

    p = parse_period(period)
    if not p:
        raise ServiceError(f"Invalid period {period} – use YYYY-MM")
    today = today or date.today()
    month = _month or _gather(db, p, today)
    work = next((c for c in month.work.clients if c.client_id == client_id), None)
    if work is None:
        raise ServiceError(f"Client {client_id} not found or not active")
    comp = ComplianceService(db).client_summary(client_id, fy_of(date(int(p[:4]), int(p[5:]), 1)), today)
    m = next(x for x in comp.months if x.period == p)
    lines = ReconciliationService(db).load(m.inward_run_id).result.lines if m.inward_run_id else []
    d = dashboard(lines) if lines else {}
    suppliers = [s for s in supplier_summary(lines, "exposure") if s.itc_at_risk > 0 or s.missing_in_2b]
    from ..services.reminders import month_name

    styles = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=styles["Heading2"], textColor=NAVY, spaceBefore=6, spaceAfter=3, fontSize=11.5)
    body = ParagraphStyle("b", parent=styles["BodyText"], fontSize=9, leading=11.5)
    small = ParagraphStyle("s", parent=body, fontSize=7.5, textColor=GREY, leading=9.5)
    title = ParagraphStyle("t", parent=styles["Title"], textColor=colors.white, fontSize=15, alignment=0,
                           spaceAfter=0)

    def table(rows, widths, head=True, money_cols=()):
        t = Table(rows, colWidths=widths)
        style = [("FONTSIZE", (0, 0), (-1, -1), 8.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                 ("TOPPADDING", (0, 0), (-1, -1), 2), ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D9DEE7")),
                 ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
        if head:
            style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF1F6")),
                      ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
        for c in money_cols:
            style.append(("ALIGN", (c, 1 if head else 0), (c, -1), "RIGHT"))
        t.setStyle(TableStyle(style))
        return t

    story = []
    band = Table([[Paragraph(f"GST summary – {month_name(p)}", title)],
                  [Paragraph(f"<font color='white'>{_esc(work.name)} · GSTIN {work.gstin}</font>", body)]],
                 colWidths=[180 * mm])
    band.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                              ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story += [band, Spacer(1, 3 * mm)]

    story.append(Paragraph("Purchases and input tax credit (ITC)", h))
    if lines:
        rows = [["", "Amount"], ["ITC as per your purchase register", _rs(m.itc_books)],
                ["ITC available as per GSTR-2B", _rs(m.itc_2b)],
                ["ITC claimed in GSTR-3B", _rs(m.itc_3b) if m.itc_3b is not None else "GSTR-3B not imported"],
                ["Difference (register – GSTR-2B)", _rs(m.itc_books - m.itc_2b)],
                ["ITC at risk (not yet in GSTR-2B / differences)", _rs(d.get("itc_at_risk", ZERO))]]
        story.append(table(rows, [120 * mm, 60 * mm], money_cols=(1,)))
        story.append(Paragraph(
            f"{d.get('fully_matched', 0)} invoice(s) fully matched ({d.get('match_percentage', 0)} %); "
            f"{d.get('missing_in_gstr2b', 0)} in your register but not in GSTR-2B; {d.get('missing_in_books', 0)} in "
            f"GSTR-2B but not in your register; {d.get('pending_cases', 0)} still under review.", body))
    else:
        story.append(Paragraph("Not reconciled yet for this month." + (
            " Purchase register received." if m.purchase_docs else " Purchase register not received.") + (
            " GSTR-2B downloaded." if m.gstr2b_docs else ""), body))

    if m.sales_docs or m.output_gstr1 is not None or m.output_3b is not None:
        story.append(Paragraph("Sales and output tax", h))
        rows = [["", "Output tax"], ["As per your sales register", _rs(m.output_sales)],
                ["As reported in GSTR-1", _rs(m.output_gstr1)], ["As paid in GSTR-3B", _rs(m.output_3b)]]
        story.append(table(rows, [120 * mm, 60 * mm], money_cols=(1,)))

    if suppliers:
        story.append(Paragraph("Suppliers to follow up", h))
        rows = [["Supplier", "GSTIN", "Not in GSTR-2B", "ITC at risk"]]
        for s in suppliers[:MAX_SUPPLIERS]:
            rows.append([Paragraph(_esc((s.name or s.gstin)[:48]), body), s.gstin, str(s.missing_in_2b),
                         _rs(s.itc_at_risk)])
        story.append(table(rows, [70 * mm, 38 * mm, 32 * mm, 40 * mm], money_cols=(2, 3)))
        if len(suppliers) > MAX_SUPPLIERS:
            story.append(Paragraph(f"…and {len(suppliers) - MAX_SUPPLIERS} more supplier(s) – details in the "
                                   "reconciliation report.", small))
        story.append(Paragraph("Please ask these suppliers to file or correct their GSTR-1; the credit is available "
                               "only once it appears in your GSTR-2B.", small))

    story.append(Paragraph("Returns", h))
    rows = [["Return", "Due date", "Status"]]
    for r in work.returns:
        state = r.state(today)
        rows.append([r.return_type + (" (optional)" if r.optional else ""), f"{r.due:%d-%m-%Y}",
                     f"Filed on {r.filed_on:%d-%m-%Y}" + (" (late)" if state == "filed late" else "")
                     if r.filed_on else {"overdue": "Not filed – overdue"}.get(state, "Not filed yet")])
    story.append(table(rows, [60 * mm, 40 * mm, 80 * mm]))

    req = month.requests.get(client_id)
    if req is not None and req.needed:
        story.append(Paragraph("We need from you", h))
        items = list(req.documents)
        if req.clarify:
            items.append(f"Clarification on {len(req.clarify)} invoice(s) – list sent separately")
        if req.correct:
            items.append(f"Correction of {len(req.correct)} entr(ies) in your books – list sent separately")
        story += [Paragraph(f"• {_esc(i)}", body) for i in items]
    if work.notices_open:
        story.append(Paragraph(f"<b>Open GST notice(s): {work.notices_open}</b>" + (
            f" – reply due {work.next_reply_due:%d-%m-%Y}" if work.next_reply_due else ""), body))

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        f"Prepared {('by ' + _esc(firm_name) + ' ') if firm_name else ''}on {today:%d-%m-%Y} from the data imported "
        "into FIN TAX PRO (purchase / sales registers, GSTR-2B, GSTR-1, GSTR-3B). A working summary for discussion – "
        "not a certificate. Amounts in rupees.", small))

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{work.gstin}_{p}_GST_summary.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm,
                            bottomMargin=12 * mm, title=f"GST summary {p} – {work.name}", author=firm_name or "")
    # one page: if a month is unusually busy, the content is scaled down rather than spilling over
    doc.build([KeepInFrame(doc.width, doc.height, story, mode="shrink")])
    return path


def build_reports(db: Database, period: str, out_dir: str | Path, client_ids: list[int] | None = None,
                  firm_name: str = "", today: date | None = None, progress=None, cancel=None) -> list[Path]:
    """One page per client (all active clients, or ``client_ids``)."""
    p = parse_period(period)
    if not p:
        raise ServiceError(f"Invalid period {period} – use YYYY-MM")
    today = today or date.today()
    month = _gather(db, p, today)
    ids = [c.client_id for c in month.work.clients if client_ids is None or c.client_id in client_ids]
    out = []
    for i, cid in enumerate(ids, start=1):
        if cancel:
            cancel.check()
        if progress:
            progress(int(100 * i / max(len(ids), 1)), f"Client {i} of {len(ids)}")
        out.append(build_client_report(db, cid, p, out_dir, firm_name, today, month))
    return out


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
