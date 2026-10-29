"""GSTR-9 Tables 4–7 and 9 sheets for the annual workbook."""
from __future__ import annotations

from decimal import Decimal

from ..gstr9.working import Gstr9Working, Row

HEADS = ["Taxable", "IGST", "CGST", "SGST", "Cess"]


def _v(v) -> list:
    return [v.taxable, v.igst, v.cgst, v.sgst, v.cess] if v is not None else [None] * 5


def _subtotal_style(rows):
    """Bold shading for sub-total rows, keeping the number format on amounts."""
    def style(r, _c, v, rows=rows):
        if r not in rows:
            return None
        return "ftp_money_bold" if isinstance(v, (int, float, Decimal)) else "ftp_total_label"
    return style


def gstr9_sheets(wb, w: Gstr9Working) -> None:
    from .excel_report import _Sheet, _write_table, section_label

    sub = {"4H", "4M", "4N", "5G", "5L", "5M", "5N", "6I", "6J", "7I", "7J"}
    sh = _Sheet(wb, "GSTR-9 Tables 4-5", [8, 70, 15, 13, 13, 13, 11, 15, 13, 13, 13, 11, 15, 13, 50])
    sh.ws.freeze_panes = "C5"
    sh.banner(f"GSTR-9 – Tables 4 and 5 – FY {w.fy}", "Returns: GSTR-1 of the year (4G from GSTR-3B 3.1(d)). "
              "Books: sales register. A working paper for review – not the return as filed.", 15)

    def rows(table: list[Row]):
        out = []
        for r in table:
            d = r.diff
            out.append([r.code, r.label, *_v(r.gstr1), *_v(r.books), d.taxable if d else None,
                        d.total if d else None, r.note])
        return out

    heads = ["Table", "Description"] + [f"Returns {h}" for h in HEADS] + [f"Books {h}" for h in HEADS] + \
        ["Books − Returns taxable", "Books − Returns tax", "Note"]
    kinds = ["text", "wrap"] + ["money"] * 12 + ["wrap"]
    t4 = rows(w.table4)
    _write_table(sh, heads, t4, kinds, name="Gstr9Table4", totals=False,
                 cell_styles=_subtotal_style({i for i, r in enumerate(w.table4) if r.code in sub}))
    sh.append([])
    _write_table(sh, heads, rows(w.table5), kinds, name="Gstr9Table5", totals=False,
                 cell_styles=_subtotal_style({i for i, r in enumerate(w.table5) if r.code in sub}))
    sh.append([])
    for n in w.notes:
        sh.append([sh.cell(n, "ftp_note")])

    it = _Sheet(wb, "GSTR-9 Tables 6-7-9", [8, 80, 15, 15, 15, 13, 15, 60])
    it.banner(f"GSTR-9 – Tables 6, 7 and 9 – FY {w.fy}", "Tables 6 and 7 from GSTR-3B Table 4 of the year's periods; "
              "Table 9 compares the tax payable per Table 4 with the tax declared in GSTR-3B.", 8)
    itc_rows = [[r.code, r.label, r.gstr1.igst, r.gstr1.cgst, r.gstr1.sgst, r.gstr1.cess, r.gstr1.total, r.note]
                for r in w.table6 + w.table7]
    sub_idx = {i for i, r in enumerate(w.table6 + w.table7) if r.code in sub}
    _write_table(it, ["Table", "Description", "IGST", "CGST", "SGST", "Cess", "Total", "Note"], itc_rows,
                 ["text", "wrap", "money", "money", "money", "money", "money", "wrap"], name="Gstr9Table67",
                 totals=False, cell_styles=_subtotal_style(sub_idx))
    it.append([])
    it.append([section_label(it, "TABLE 9 – TAX PAYABLE AND DECLARED")])
    t9 = []
    for head, payable, declared in w.table9:
        p = payable.total
        dd = declared.total if declared is not None else None
        t9.append([head, p, dd, (dd - p) if dd is not None else None])
    _write_table(it, ["Tax", "Payable per Table 4N", "Declared in GSTR-3B 3.1(a)+(b)+(d)", "Declared − Payable"], t9,
                 ["text", "money", "money", "money"], name="Gstr9Table9", totals=False)

    am = _Sheet(wb, "GSTR-9 Amendments", [9, 9, 18, 22, 22, 15, 15, 15, 9, 46])
    am.banner("GSTR-1 amendments of the year", "Change from the original where the original was imported; other "
                                                "amendments need the change entered manually", 10)
    arows = []
    for a in w.amendments:
        d = a["delta"]
        arows.append([a["period"], a["section"], a["party"], a["document"], a["original"], a["revised"].taxable,
                      d.taxable if d else None, d.total if d else None, a["row"], a["status"]])
    _write_table(am, ["Period", "Section", "Party / POS", "Document", "Original", "Revised taxable",
                      "Change taxable", "Change tax", "Row", "Status"], arows,
                 ["text", "text", "text", "text", "text", "money", "money", "money", "text", "wrap"],
                 name="Gstr9Amendments", totals=False)
