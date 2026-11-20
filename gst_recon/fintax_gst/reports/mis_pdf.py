"""GST MIS pack for a client's management: KPIs, four charts and the monthly table (A4, two pages)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..core.money import ZERO, fmt_inr

# validated categorical order (blue, orange, aqua) – three series at most per chart; text stays in ink colours
SERIES = [colors.HexColor("#2A78D6"), colors.HexColor("#EB6834"), colors.HexColor("#1BAF7A")]
INK, MUTED, GRID = colors.HexColor("#0B0B0B"), colors.HexColor("#52514E"), colors.HexColor("#E3E2DE")
NAVY = colors.HexColor("#1F3864")


def _lakh(v: Decimal | None) -> float | None:
    return None if v is None else float(v) / 100000.0


def _nice_step(span: float) -> float:
    import math

    raw = max(span, 1e-9) / 4
    mag = 10 ** math.floor(math.log10(raw))
    return next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)


def _axis_style(chart, values: list[float]) -> None:
    vals = [v for v in values if v is not None]
    hi = max(vals + [0.0])
    lo = min(vals + [0.0])
    if hi == lo:
        hi = lo + 1.0  # all zero: a plain 0–1 scale instead of repeated labels
    step = _nice_step(hi - lo)
    import math

    chart.valueAxis.valueMin = math.floor(lo / step) * step
    chart.valueAxis.valueMax = math.ceil(hi / step) * step
    chart.valueAxis.valueStep = step
    decimals = 0 if step >= 1 else (1 if step >= 0.1 else 2)
    chart.valueAxis.labelTextFormat = f"%.{decimals}f"
    for axis in (chart.valueAxis, chart.categoryAxis):
        axis.labels.fontSize = 6.5
        axis.labels.fontName = "Helvetica"
        axis.labels.fillColor = MUTED
        axis.strokeColor = GRID
    chart.valueAxis.visibleGrid = True
    chart.valueAxis.gridStrokeColor = GRID
    chart.valueAxis.gridStrokeWidth = 0.4


def _title(d: Drawing, text: str) -> None:
    d.add(String(0, d.height - 10, text, fontName="Helvetica-Bold", fontSize=8.5, fillColor=INK))


def line_chart(title: str, labels: list[str], series: list[tuple[str, list[float | None]]], w=180 * mm,
               h=62 * mm) -> Drawing:
    d = Drawing(w, h)
    _title(d, title)
    ch = HorizontalLineChart()
    ch.x, ch.y, ch.width, ch.height = 30, 26, w - 40, h - 48
    ch.data = [[v if v is not None else 0 for v in vals] for _n, vals in series]
    ch.categoryAxis.categoryNames = labels
    _axis_style(ch, [v for _n, vals in series for v in vals if v is not None])
    for i in range(len(series)):
        ch.lines[i].strokeColor = SERIES[i]
        ch.lines[i].strokeWidth = 1.5
        ch.lines[i].symbol = None
    ch.joinedLines = 1
    d.add(ch)
    if len(series) > 1:
        lg = Legend()
        lg.x, lg.y, lg.fontSize, lg.fillColor, lg.fontName = 30, 8, 7, INK, "Helvetica"
        lg.alignment, lg.columnMaximum, lg.dx, lg.dy, lg.deltax = "right", 1, 8, 6, 90
        lg.colorNamePairs = [(SERIES[i], n) for i, (n, _v) in enumerate(series)]
        d.add(lg)
    return d


def bar_chart(title: str, labels: list[str], values: list[float | None], w=88 * mm, h=58 * mm) -> Drawing:
    d = Drawing(w, h)
    _title(d, title)
    ch = VerticalBarChart()
    ch.x, ch.y, ch.width, ch.height = 28, 18, w - 34, h - 34
    ch.data = [[v if v is not None else 0 for v in values]]
    ch.categoryAxis.categoryNames = labels
    _axis_style(ch, [v for v in values if v is not None])
    ch.bars[0].fillColor = SERIES[0]
    ch.bars[0].strokeColor = None
    ch.barSpacing, ch.groupSpacing = 2, 4
    d.add(ch)
    if not any(values):
        d.add(String(ch.x + ch.width / 2, ch.y + ch.height / 2, "None in these months", textAnchor="middle",
                     fontName="Helvetica", fontSize=7.5, fillColor=MUTED))
    return d


def hbar_chart(title: str, labels: list[str], values: list[float], w=180 * mm, h: float | None = None) -> Drawing:
    h = h or 40 + 16 * max(len(values), 1)  # thin bars: the height follows the number of suppliers
    d = Drawing(w, h)
    _title(d, title)
    ch = HorizontalBarChart()
    ch.x, ch.y, ch.width, ch.height = 120, 14, w - 130, h - 30
    ch.data = [list(reversed(values)) or [0]]
    ch.categoryAxis.categoryNames = list(reversed(labels)) or ["–"]
    _axis_style(ch, values)
    ch.bars[0].fillColor = SERIES[0]
    ch.bars[0].strokeColor = None
    ch.barSpacing = 2
    ch.groupSpacing = 6
    d.add(ch)
    return d


def build_mis_pdf(mis, path: Path, firm: str = "", today: date | None = None) -> Path:
    today = today or date.today()
    ss = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=ss["Heading3"], textColor=NAVY, fontSize=10, spaceBefore=6, spaceAfter=3)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=8.5, leading=11)
    small = ParagraphStyle("s", parent=body, fontSize=7.5, leading=9.5, textColor=MUTED)
    rows = mis.active or mis.months
    labels = [m.label for m in rows]
    story = [Paragraph(f"<b>GST MIS – {mis.fy}</b>", ParagraphStyle("t", parent=ss["Title"], fontSize=15,
                                                                    textColor=NAVY, alignment=0, spaceAfter=2)),
             Paragraph(f"{mis.client} · GSTIN {mis.gstin}" + (f" · prepared by {firm}" if firm else "")
                       + f" · {today:%d-%m-%Y}", body), Spacer(1, 4)]
    kpis = [("Sales (taxable)", mis.total("sales")), ("Output tax", mis.total("output_tax")),
            ("ITC claimed", mis.total("itc_claimed")), ("Cash paid", mis.total("cash_paid")),
            ("ITC at risk", mis.total("itc_at_risk"))]
    kt = Table([[Paragraph(f"<font size=7 color='#52514E'>{k}</font><br/><b>Rs. {fmt_inr(v)}</b>", body)
                 for k, v in kpis]], colWidths=[36 * mm] * 5)
    kt.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.4, GRID), ("INNERGRID", (0, 0), (-1, -1), 0.4, GRID),
                            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story += [kt, Spacer(1, 6)]
    if not rows:
        story.append(Paragraph("No data imported for this year yet.", body))
    else:
        story.append(line_chart("ITC by month (Rs. lakh)", labels, [
            ("As per books", [_lakh(m.itc_books) for m in rows]), ("GSTR-2B", [_lakh(m.itc_2b) for m in rows]),
            ("Claimed in GSTR-3B", [_lakh(m.itc_claimed) for m in rows])]))
        pair = Table([[bar_chart("Sales by month (Rs. lakh)", labels, [_lakh(m.sales) for m in rows]),
                       bar_chart("Cash paid by month (Rs. lakh)", labels, [_lakh(m.cash_paid) for m in rows])]],
                     colWidths=[90 * mm, 90 * mm])
        story += [Spacer(1, 4), pair]
    if mis.suppliers:
        story.append(Spacer(1, 4))
        story.append(hbar_chart("Suppliers with the most ITC at risk (Rs.)", [n[:28] for n, *_ in mis.suppliers],
                                [float(a) for _n, _g, a, _d in mis.suppliers]))
    story.append(PageBreak())
    story.append(Paragraph("Month by month (Rs.)", h))
    head = ["Month", "Sales", "Output tax", "ITC books", "ITC 2B", "ITC claimed", "ITC at risk", "Cash paid"]
    data = [head]
    for m in rows:
        data.append([m.label] + ["–" if v is None else fmt_inr(v) for v in (
            m.sales, m.output_tax, m.itc_books, m.itc_2b, m.itc_claimed, m.itc_at_risk, m.cash_paid)])
        if m.cash_estimated:
            data[-1][-1] += " *"
    data.append(["Total"] + [fmt_inr(mis.total(a)) for a in ("sales", "output_tax", "itc_books", "itc_2b",
                                                              "itc_claimed", "itc_at_risk", "cash_paid")])
    t = Table(data, colWidths=[16 * mm] + [23 * mm] * 7, repeatRows=1)
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 7.5), ("GRID", (0, 0), (-1, -1), 0.3, GRID),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF1F6")),
                           ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                           ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"), ("ALIGN", (1, 0), (-1, -1), "RIGHT")]))
    story.append(t)
    if mis.suppliers:
        story.append(Paragraph("Suppliers with ITC at risk", h))
        st = Table([["Supplier", "GSTIN", "ITC at risk", "Docs not in 2B"]] + [
            [n[:40], g, fmt_inr(a), str(d)] for n, g, a, d in mis.suppliers], colWidths=[70 * mm, 40 * mm,
                                                                                     30 * mm, 25 * mm])
        st.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 7.5), ("GRID", (0, 0), (-1, -1), 0.3, GRID),
                                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("ALIGN", (2, 0), (-1, -1), "RIGHT")]))
        story.append(st)
    notes = list(mis.notes) + (["* cash paid estimated"] if any(m.cash_estimated for m in rows) else [])
    if notes:
        story.append(Spacer(1, 6))
        story += [Paragraph(f"• {n}", small) for n in notes]
    story.append(Spacer(1, 6))
    story.append(Paragraph("Prepared from the GST data imported for the client (returns, GSTR-2B, books). A working "
                           "summary for management, not a statutory return.", small))
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm,
                            bottomMargin=12 * mm, title=f"GST MIS {mis.client} {mis.fy}")
    doc.build(story)
    return path


__all__ = ["build_mis_pdf", "ZERO"]
