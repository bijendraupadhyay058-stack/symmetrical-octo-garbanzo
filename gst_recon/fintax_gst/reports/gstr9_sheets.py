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

    it = _Sheet(wb, "GSTR-9 Tables 6-7-9", [10, 80, 18, 18, 18, 16, 16, 60])
    it.banner(f"GSTR-9 – Tables 6, 7 and 9 – FY {w.fy}", "Tables 6 and 7 from GSTR-3B Table 4 of the year's periods; "
              "Table 9 compares the tax payable per Table 4 with the tax declared in GSTR-3B.", 8)
    itc_rows = [[r.code, r.label, r.gstr1.igst, r.gstr1.cgst, r.gstr1.sgst, r.gstr1.cess, r.gstr1.total, r.note]
                for r in w.table6 + w.table7]
    sub_idx = {i for i, r in enumerate(w.table6 + w.table7) if r.code in sub}
    _write_table(it, ["Table", "Description", "IGST", "CGST", "SGST", "Cess", "Total", "Note"], itc_rows,
                 ["text", "wrap", "money", "money", "money", "money", "money", "wrap"], name="Gstr9Table67",
                 totals=False, cell_styles=_subtotal_style(sub_idx))
    it.append([])
    it.append([section_label(it, "TABLE 9 – TAX PAYABLE, DECLARED AND PAID")])
    t9 = [[x.head, x.payable, x.declared, x.paid_cash, x.paid_itc, x.paid, x.unpaid] for x in w.table9]
    t9.append(["Interest", None, None, w.interest_paid, None, w.interest_paid, None])
    t9.append(["Late fee", None, None, w.late_fee_paid, None, w.late_fee_paid, None])
    _write_table(it, ["Tax", "Payable per Table 4N", "Declared in GSTR-3B 3.1(a)+(b)+(d)", "Paid in cash (6.1)",
                      "Paid through ITC (6.1)", "Total paid", "Payable − Paid"], t9,
                 ["text", "money", "money", "money", "money", "money", "money"], name="Gstr9Table9", totals=False)

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


def gstr9c_sheet(wb, st) -> None:
    """GSTR-9C Part A Tables 5, 7, 9 and 12 with the source of every figure."""
    from ..gstr9.reconciliation_9c import REASON_ITEMS
    from .excel_report import _Sheet, _write_table, section_label

    sh = _Sheet(wb, "GSTR-9C Reconciliation", [8, 80, 18, 46])
    sh.banner(f"GSTR-9C reconciliation statement – FY {st.fy}",
              "Figures marked 'default' are stand-ins from the registers – replace them with the audited figures "
              "before certifying. A working paper for review.", 4)
    sub = {"5P", "5R", "7E", "7G", "12D", "12F"}

    def lines(title, rows, name):
        sh.append([section_label(sh, title)])
        idx = {i for i, x in enumerate(rows) if x.code in sub}
        _write_table(sh, ["Table", "Description", "Amount", "Source"],
                     [[x.code, x.label, x.amount, x.source] for x in rows], ["text", "wrap", "money", "wrap"],
                     name=name, totals=False, cell_styles=_subtotal_style(idx))
        sh.append([])

    lines("TABLE 5 – RECONCILIATION OF GROSS TURNOVER", st.table5, "Gstr9cTable5")
    lines("TABLE 7 – RECONCILIATION OF TAXABLE TURNOVER", st.table7, "Gstr9cTable7")
    lines("TABLE 12 – RECONCILIATION OF NET INPUT TAX CREDIT", st.table12, "Gstr9cTable12")

    t9 = _Sheet(wb, "GSTR-9C Table 9", [24, 16, 15, 15, 15, 13])
    t9.banner(f"GSTR-9C Table 9 – rate-wise tax – FY {st.fy}", "Books: sales register by rate. Paid: GSTR-9 Table 9 "
              "(GSTR-3B Table 6.1).", 6)
    rows = [[r.rate, r.taxable, r.cgst, r.sgst, r.igst, r.cess] for r in st.table9]
    tot = st.table9_total
    rows.append(["9P Total amount to be paid as per tables above", None, tot["cgst"], tot["sgst"], tot["igst"],
                 tot["cess"]])
    p = st.table9_paid
    rows.append(["9Q Total amount paid as declared in GSTR-9", None, p.get("cgst"), p.get("sgst"), p.get("igst"),
                 p.get("cess")])
    u = st.table9_unreconciled
    rows.append(["9R Un-reconciled payment of amount", None, u.get("cgst"), u.get("sgst"), u.get("igst"),
                 u.get("cess")])
    n = len(rows)
    _write_table(t9, ["Rate / item", "Taxable value", "CGST", "SGST/UTGST", "IGST", "Cess"], rows,
                 ["text", "money", "money", "money", "money", "money"], name="Gstr9cTable9", totals=False,
                 cell_styles=_subtotal_style({n - 3, n - 1}))
    t9.append([])
    t9.append([section_label(t9, "INTEREST, LATE FEE, PENALTY AND OTHERS (ENTERED)")])
    _write_table(t9, ["Item", "Amount"], [[k, v] for k, v in st.table9_other.items()], ["text", "money"],
                 name="Gstr9cTable9Other", totals=False)

    sh.append([section_label(sh, "REASONS FOR UN-RECONCILED DIFFERENCES")])
    _write_table(sh, ["Table", "Description", "Reason", ""],
                 [[k[1:], label, st.reasons.get(k) or "", ""] for k, label in REASON_ITEMS.items()],
                 ["text", "wrap", "wrap", "text"], name="Gstr9cReasons", totals=False)
    sh.append([])
    for note in st.notes:
        sh.append([sh.cell(note, "ftp_note")])
