"""Workbook sheets for outward runs: GSTR-1 vs GSTR-3B Table 3.1 liability, GSTR-1 section totals."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..outward.liability import LiabilityWorking


@dataclass
class OutwardReportData:
    workings: list[LiabilityWorking] = field(default_factory=list)
    summaries: dict[str, list[dict]] = field(default_factory=dict)  # period -> GSTR-1 section totals


def liability_sheet(wb, data: OutwardReportData) -> None:
    from .excel_report import _Sheet, _write_table, section_label

    sh = _Sheet(wb, "GSTR-1 vs GSTR-3B", [9, 52, 15, 15, 15, 15, 15, 15, 15, 15])
    sh.ws.freeze_panes = "C5"
    sh.banner("GSTR-1 vs GSTR-3B Table 3.1", "Output tax declared in GSTR-1 and the sales register compared "
                                             "with GSTR-3B as filed. A working paper for review.", 10)
    workings = data.workings
    rows = []
    for w in workings:
        for r in w.rows:
            f = r.filed
            rows.append([w.period, f"{r.code} {r.label}", r.gstr1.taxable, r.gstr1.total, r.sales.taxable,
                         r.sales.total, f.taxable if f else None, f.total if f else None, r.diff_filed_gstr1,
                         r.diff_sales_gstr1])
    _write_table(sh, ["Period", "GSTR-3B Table 3.1 row", "GSTR-1 Taxable", "GSTR-1 Tax", "Sales Taxable",
                      "Sales Tax", "3B Taxable", "3B Tax", "3B − GSTR-1", "Sales − GSTR-1"], rows,
                 ["text", "wrap", "money", "money", "money", "money", "money", "money", "money", "money"],
                 name="LiabilityWorking", totals=False)
    sh.append([])
    sh.append([section_label(sh, "SEGMENTS – SALES REGISTER VS GSTR-1")])
    srows = [[w.period, s.segment, s.sales.taxable, s.sales.total, s.gstr1.taxable, s.gstr1.total, s.diff]
             for w in workings for s in w.segments]
    _write_table(sh, ["Period", "Segment", "Sales Taxable", "Sales Tax", "GSTR-1 Taxable", "GSTR-1 Tax",
                      "Difference"], srows, ["text", "text", "money", "money", "money", "money", "money"],
                 name="LiabilitySegments", totals=False)
    sh.append([])
    sh.append([section_label(sh, "CLASSIFIED DIFFERENCES")])
    frows = [[w.period, f.kind.title(), f.severity.upper(), f.text, f.amount] for w in workings for f in w.findings]
    _write_table(sh, ["Period", "Type", "Severity", "Finding", "Amount"], frows,
                 ["text", "text", "text", "wrap", "money"], name="LiabilityFindings", totals=False)


def gstr1_sections_sheet(wb, data: OutwardReportData) -> None:
    from .excel_report import _Sheet, _write_table

    sh = _Sheet(wb, "GSTR-1 Section Totals", [9, 10, 18, 8, 8, 10, 15, 14, 14, 14, 12])
    sh.ws.freeze_panes = "C5"
    sh.banner("GSTR-1 section totals", "B2B, B2C, exports, notes, nil/exempt and amendments as filed. "
                                       "Amendments revise earlier periods and are not added to the totals.", 11)
    rows = [[p, s["section"], s.get("supply", ""), s.get("pos", ""), s.get("rate"), s.get("doc_count"),
             s["taxable"], s["igst"], s["cgst"], s["sgst"], s["cess"]]
            for p in sorted(data.summaries) for s in sorted(data.summaries[p], key=lambda x: (x["section"],
                                                                                              x.get("supply", "")))]
    _write_table(sh, ["Period", "Section", "Supply", "POS", "Rate", "Docs", "Taxable", "IGST", "CGST", "SGST",
                      "Cess"], rows, ["text", "text", "text", "text", "money", "int", "money", "money", "money",
                                      "money", "money"], name="Gstr1Sections", totals=False)
