"""Ledger bifurcation workbook: the trial balance as imported, the classification of every ledger with live formulas
(classified = sum of its parts, unallocated = amount − classified), the purchase / expense / capital goods / inputs /
input services summaries, ITC eligibility, GSTR-2B and GSTR-3B reconciliation, the GSTR-9 Table 6 and GSTR-9C
Table 14 workings (SUMIFS over the parts), exceptions and the classification audit trail."""
from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from ..ledgers.classify import ACCT_CLASSES, ELIGIBILITY, GST_CLASSES, GST_SOURCES

HEAD_FILL = PatternFill("solid", fgColor="1F3864")
RED = PatternFill("solid", fgColor="FFCDD2")
AMBER = PatternFill("solid", fgColor="FFF3C4")
MONEY = "#,##,##0.00;[Red]-#,##,##0.00"


def _f(v):
    return None if v is None else float(v)


def _sheet(wb, title, head, widths=None):
    ws = wb.create_sheet(title)
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = HEAD_FILL
    ws.freeze_panes = "A2"
    for i, w in enumerate(widths or [], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    return ws


def _finish(ws, money_cols: str = ""):
    if ws.max_row > 1:
        ws.auto_filter.ref = f"A1:{get_column_letter(ws.max_column)}{ws.max_row}"
    for col in money_cols:
        for c in ws[col][1:]:
            c.number_format = MONEY


def build_workbook(svc, client_id: int, fy: str, path: Path) -> Path:
    sm = svc.summary(client_id, fy)
    wb = Workbook()
    dash = wb.active
    dash.title = "Dashboard"

    # ---------------- parts (the base of every formula)
    parts = _sheet(wb, "Parts", ["Ledger id", "Ledger", "Nature", "Accounting classification", "Accounting group",
                                 "GST classification", "GSTR-9 row", "Source", "GSTR-9C head", "ITC eligibility",
                                 "Amount", "Taxable value", "IGST", "CGST", "SGST", "Cess", "GST total", "GST basis",
                                 "Basis note", "Approved by", "Remarks"],
                   [9, 34, 9, 30, 16, 22, 9, 18, 9, 24, 15, 15, 12, 12, 12, 10, 13, 16, 30, 14, 40])
    from ..services.bifurcation import T6_ROW

    for v in sm.views:
        for sp in v.splits:
            n = parts.max_row + 1
            parts.append([v.ledger.id, v.ledger.name, v.ledger.nature, sp.acct_class,
                          ACCT_CLASSES.get(sp.acct_class, "Other"), GST_CLASSES.get(sp.gst_class, sp.gst_class),
                          T6_ROW.get(sp.gst_source, "6B"), GST_SOURCES.get(sp.gst_source, sp.gst_source),
                          sp.head_9c, ELIGIBILITY.get(sp.eligibility, sp.eligibility), _f(sp.amount), _f(sp.taxable),
                          _f(sp.igst), _f(sp.cgst), _f(sp.sgst), _f(sp.cess), f"=SUM(M{n}:P{n})",
                          {"invoices": "Invoices", "entered": "Entered", "apportioned": "Apportioned"}.get(
                              sp.gst_basis, "Not given"), sp.basis_note,
                          sp.approved_by if sp.approved else "(suggested – not approved)", sp.remarks])
    _finish(parts, "KLMNOPQ")
    last = max(parts.max_row, 2)

    def rng(col):
        return f"Parts!${col}$2:${col}${last}"

    # ---------------- original data
    orig = _sheet(wb, "Original TallyPrime data", ["Ledger", "Group (under)", "Primary group", "Opening balance",
                                                   "Debit (year)", "Credit (year)", "Closing balance (Dr +, Cr −)"],
                  [36, 28, 22, 16, 16, 16, 20])
    for v in sm.views:
        lg = v.ledger
        orig.append([lg.name, lg.parent, lg.primary_group, _f(lg.opening), _f(lg.debit), _f(lg.credit),
                     _f(lg.closing)])
    n = orig.max_row
    orig.append(["Total debit balances", "", "", "", "", "", f'=SUMIF(G2:G{n},">0")'])
    orig.append(["Total credit balances", "", "", "", "", "", f'=-SUMIF(G2:G{n},"<0")'])
    orig.append(["Difference (must be nil)", "", "", "", "", "", f"=G{n + 1}-G{n + 2}"])
    for r in range(n + 1, n + 4):
        orig.cell(r, 1).font = Font(bold=True)
    orig.conditional_formatting.add(f"G{n + 3}", FormulaRule(formula=[f"ABS(G{n + 3})>1"], fill=RED))
    _finish(orig, "DEFG")

    # ---------------- trial balance summary
    tbs = _sheet(wb, "Trial Balance Summary", ["Nature", "Primary group", "Ledgers", "Debit balances",
                                               "Credit balances", "Net"], [12, 28, 10, 18, 18, 18])
    groups: dict[tuple[str, str], list] = {}
    for v in sm.views:
        groups.setdefault((v.ledger.nature, v.ledger.primary_group or v.ledger.parent), []).append(v.ledger.closing)
    for (nat, grp), vals in sorted(groups.items()):
        r = tbs.max_row + 1
        tbs.append([nat, grp, len(vals), _f(sum(x for x in vals if x > 0)), _f(-sum(x for x in vals if x < 0)),
                    f"=D{r}-E{r}"])
    r = tbs.max_row
    tbs.append(["Total", "", f"=SUM(C2:C{r})", f"=SUM(D2:D{r})", f"=SUM(E2:E{r})", f"=D{r + 1}-E{r + 1}"])
    tbs.cell(r + 1, 1).font = Font(bold=True)
    _finish(tbs, "DEF")

    # ---------------- classification (the 15 columns), with formulas
    cls = _sheet(wb, "Classification", ["Ledger id", "Original Tally ledger", "Parent group", "Original ledger amount",
                                        "Amount to classify", "Accounting classification", "GST ITC classification",
                                        "GSTR-9C head", "Taxable value", "IGST", "CGST", "SGST/UTGST", "Cess",
                                        "ITC eligibility", "Classified amount", "Unallocated balance",
                                        "Status", "Remarks / verification"],
                 [9, 34, 24, 16, 16, 28, 20, 9, 15, 12, 12, 12, 10, 22, 16, 16, 18, 50])
    for v in sm.views:
        if not v.in_scope:
            continue
        r = cls.max_row + 1
        lg = v.ledger
        cls.append([lg.id, lg.name, lg.parent or lg.primary_group, _f(lg.closing), _f(lg.base),
                    v.label("acct_class"), v.label("gst_class"), v.label("head_9c"),
                    f"=SUMIF({rng('A')},A{r},{rng('L')})", f"=SUMIF({rng('A')},A{r},{rng('M')})",
                    f"=SUMIF({rng('A')},A{r},{rng('N')})", f"=SUMIF({rng('A')},A{r},{rng('O')})",
                    f"=SUMIF({rng('A')},A{r},{rng('P')})", v.label("eligibility"),
                    f"=SUMIF({rng('A')},A{r},{rng('K')})", f"=E{r}-O{r}", v.state,
                    "; ".join([lg.base_note] * bool(lg.base_note) + v.warnings + [lg.remarks] * bool(lg.remarks))])
    r = cls.max_row
    cls.append(["", "Total", "", f"=SUBTOTAL(9,D2:D{r})", f"=SUBTOTAL(9,E2:E{r})", "", "", "",
                *(f"=SUBTOTAL(9,{c}2:{c}{r})" for c in "IJKLM"), "", f"=SUBTOTAL(9,O2:O{r})",
                f"=SUBTOTAL(9,P2:P{r})"])
    cls.cell(r + 1, 2).font = Font(bold=True)
    cls.conditional_formatting.add(f"P2:P{r}", FormulaRule(formula=["ABS(P2)>0.5"], fill=RED))
    cls.conditional_formatting.add(f"Q2:Q{r}", FormulaRule(formula=['LEFT(Q2,9)="Suggested"'], fill=AMBER))
    _finish(cls, "DEIJKLMOP")

    # ---------------- P&L classification
    pl = _sheet(wb, "P&L Classification", ["Ledger", "Group", "Nature", "Amount (Dr +, Cr −)",
                                           "Accounting classification", "GST classification"], [36, 26, 10, 18, 30, 22])
    for v in sm.views:
        if v.ledger.nature in ("income", "purchase", "expense"):
            pl.append([v.ledger.name, v.ledger.parent or v.ledger.primary_group, v.ledger.nature,
                       _f(v.ledger.closing), v.label("acct_class") or ("(income)" if v.ledger.nature == "income"
                                                                        else "(not classified)"),
                       v.label("gst_class")])
    _finish(pl, "D")

    # ---------------- filtered views of the parts
    def part_sheet(title, keep):
        ws = _sheet(wb, title, ["Ledger", "Accounting classification", "GST classification", "Source",
                                "ITC eligibility", "Amount", "Taxable value", "IGST", "CGST", "SGST", "Cess",
                                "GST basis", "Remarks"], [34, 30, 22, 18, 22, 15, 15, 12, 12, 12, 10, 18, 40])
        for v in sm.views:
            for sp in v.splits:
                if keep(v, sp):
                    ws.append([v.ledger.name, sp.acct_class, GST_CLASSES.get(sp.gst_class), GST_SOURCES.get(
                        sp.gst_source), ELIGIBILITY.get(sp.eligibility, sp.eligibility), _f(sp.amount), _f(sp.taxable),
                        _f(sp.igst), _f(sp.cgst), _f(sp.sgst), _f(sp.cess), sp.gst_basis or "not given",
                        sp.remarks])
        r = ws.max_row
        ws.append(["Total", "", "", "", "", *(f"=SUBTOTAL(9,{c}2:{c}{max(r, 2)})" for c in "FGHIJK")])
        ws.cell(r + 1, 1).font = Font(bold=True)
        _finish(ws, "FGHIJK")

    part_sheet("Purchase Bifurcation", lambda v, sp: v.ledger.nature == "purchase")
    part_sheet("Expense Bifurcation", lambda v, sp: v.ledger.nature == "expense")
    part_sheet("Capital Goods Register", lambda v, sp: sp.gst_class == "capital"
               or ACCT_CLASSES.get(sp.acct_class) == "Fixed assets")
    part_sheet("Inputs Summary", lambda v, sp: sp.gst_class == "inputs")
    part_sheet("Input Services Summary", lambda v, sp: sp.gst_class == "services")

    # ---------------- ITC eligibility
    el = _sheet(wb, "ITC Eligibility & Reversals", ["ITC eligibility", "GST classification", "Amount", "GST total",
                                                    "GSTR-9 Table 7 row"], [26, 24, 16, 16, 26])
    from ..services.bifurcation import T7_ROW

    for ek, elabel in ELIGIBILITY.items():
        for gk, glabel in GST_CLASSES.items():
            if gk in ("nogst", "excluded"):
                continue
            r = el.max_row + 1
            el.append([elabel, glabel, f'=SUMIFS({rng("K")},{rng("J")},A{r},{rng("F")},B{r})',
                       f'=SUMIFS({rng("Q")},{rng("J")},A{r},{rng("F")},B{r})', T7_ROW.get(ek, "")])
    _finish(el, "CD")

    # ---------------- GSTR-2B / 3B reconciliation (from the imported returns)
    from ..services.return_compare import ReturnCompareService

    rc = ReturnCompareService(svc.db)
    for title, kind in (("GSTR-2B Reconciliation", "3B_2B"), ("GSTR-3B Reconciliation", "1_3B")):
        comp = rc.compare(kind, client_id, fy)
        a, b = comp.sides
        ws = _sheet(wb, title, ["Month", f"{a} tax", f"{b} tax", "Difference", "Status"], [14, 16, 16, 16, 26])
        for row in comp.rows:
            r = ws.max_row + 1
            ws.append([row.label, _f(row.left.total) if row.left is not None else None,
                       _f(row.right.total) if row.right is not None else None,
                       f'=IF(OR(B{r}="",C{r}=""),"",B{r}-C{r})', row.status(a, b)])
        ws.conditional_formatting.add(f"D2:D{ws.max_row}", FormulaRule(formula=['AND(D2<>"",ABS(D2)>1)'], fill=RED))
        ws.append([])
        ws.append([f"{comp.title}: GSTR-3B Table 4(A) ITC against GSTR-2B" if kind == "3B_2B" else
                   f"{comp.title}: GSTR-1 tax against GSTR-3B Table 3.1(a)+(b)"])
        _finish(ws, "BCD")

    # ---------------- GSTR-9 Table 6 working
    t6 = _sheet(wb, "GSTR-9 Table-wise Working", ["GSTR-9 row", "GST ITC category", "Taxable value", "IGST", "CGST",
                                                  "SGST", "Cess", "Total ITC"], [48, 20, 16, 14, 14, 14, 12, 16])
    from ..services.bifurcation import T6_LABEL

    for row, label in T6_LABEL.items():
        rows = []
        cats = [("Inputs", "inputs"), ("Input services", "services"), ("Capital goods", "capital")]
        if row == "6E":
            cats = [c for c in cats if c[1] != "services"]
        if row == "6F":
            cats = [c for c in cats if c[1] == "services"]
        for clabel, _g in cats:
            r = t6.max_row + 1
            cells = []
            for col in "LMNOP":
                f = (f'SUMIFS({rng(col)},{rng("G")},"{row}",{rng("F")},"{clabel}",{rng("J")},"Eligible")'
                     f'+SUMIFS({rng(col)},{rng("G")},"{row}",{rng("F")},"{clabel}",{rng("J")},"Reclaimed")')
                cells.append("=" + f)
            t6.append([label, clabel, *cells, f"=SUM(D{r}:G{r})"])
            rows.append(r)
        r = t6.max_row + 1
        t6.append([f"{row} total", "", *(f"=SUM({c}{rows[0]}:{c}{rows[-1]})" for c in "CDEFGH")])
        t6.cell(r, 1).font = Font(bold=True)
    if sm.itc_3b_4a5 is not None:
        r6b = next(i for i in range(2, t6.max_row + 1) if t6.cell(i, 1).value == "6B total")
        t6.append([])
        r = t6.max_row + 1
        t6.append(["GSTR-3B 4(A)(5) for the year (6B as filed)", "", None,
                   *(_f(sm.itc_3b_4a5[h]) for h in ("igst", "cgst", "sgst", "cess")), f"=SUM(D{r}:G{r})"])
        t6.append(["Difference: 6B per classification − GSTR-3B", "", None,
                   *(f"={c}{r6b}-{c}{r}" for c in "DEFGH")])
        t6.conditional_formatting.add(f"D{r + 1}:H{r + 1}", FormulaRule(formula=[f"ABS(D{r + 1})>1"], fill=RED))
    t6.append([])
    t6.append(["Only ITC classified as Eligible / Reclaimed counts as availed. Values come from the GST of each part "
               "(invoices or approved apportionment) – a part without GST adds nothing."])
    _finish(t6, "CDEFGH")

    # ---------------- GSTR-9C Table 14
    from ..gstr9.expenses import TABLE14

    t14 = _sheet(wb, "GSTR-9C Expense-wise ITC", ["Row", "Expense head", "Expense / purchase value", "GST charged",
                                                  "Eligible ITC", "Ineligible ITC", "ITC actually availed",
                                                  "ITC reversed", "Difference", "Explanation"],
                 [7, 44, 18, 15, 15, 15, 16, 14, 14, 50])
    rows14 = {r.code: r for r in sm.table14}
    for code, label in TABLE14:
        r = t14.max_row + 1
        x = rows14[code]
        excl = f'{rng("F")},"<>{GST_CLASSES["excluded"]}"'
        t14.append([code, label, f'=SUMIFS({rng("K")},{rng("I")},A{r},{excl})',
                    f'=SUMIFS({rng("Q")},{rng("I")},A{r},{excl})', _f(x.eligible), _f(x.ineligible), _f(x.availed),
                    _f(x.reversed), f"=D{r}-G{r}-H{r}-F{r}", "; ".join(x.explanation)])
    r = t14.max_row
    t14.append(["", "Total", *(f"=SUM({c}2:{c}{r})" for c in "CDEFGHI")])
    t14.cell(r + 1, 2).font = Font(bold=True)
    t14.append([])
    from ..services.bifurcation import TABLE14_STATUS

    t14.append(["", TABLE14_STATUS])
    _finish(t14, "CDEFGHI")

    # ---------------- exceptions
    ex = _sheet(wb, "Differences & Exceptions", ["Severity", "Ledger", "Exception"], [10, 36, 90])
    for sev, ledger, text in sm.exceptions:
        ex.append([sev, ledger, text])
        ex.cell(ex.max_row, 1).fill = RED if sev == "red" else AMBER
    _finish(ex)

    # ---------------- audit trail
    au = _sheet(wb, "Classification Audit Trail", ["When (UTC)", "User", "Action", "Ledger", "Details"],
                [19, 14, 20, 34, 100])
    for a in svc.audit_trail(client_id):
        d = json.loads(a.details_json or "{}")
        au.append([a.at, a.user, a.action, d.get("ledger", ""), json.dumps(d, ensure_ascii=False)[:2000]])
    _finish(au)

    # ---------------- dashboard
    dash.append([f"{sm.client} ({sm.gstin}) – ledger classification & bifurcation, FY {sm.fy}"])
    dash["A1"].font = Font(bold=True, size=13)
    ok, reasons = sm.ready
    dash.append(["Ready for GSTR-9 / 9C working" if ok else "NOT READY – " + "; ".join(reasons)])
    dash["A2"].font = Font(bold=True, color="1B5E20" if ok else "B71C1C")
    dash.append([])
    dash.append(["Purchase and expense summary", "Amount"])
    for grp in ("Purchases", "Direct expenses", "Indirect expenses", "Fixed assets"):
        dash.append([grp, f'=SUMIFS({rng("K")},{rng("E")},"{grp}")'])
    for label in ("Trading goods", "Raw materials", "Exempt / non-GST purchases"):
        dash.append([f"  of which {label}", f'=SUMIFS({rng("K")},{rng("D")},"{label}")'])
    dash.append([])
    dash.append(["GST classification", "Amount", "GST total", "ITC availed (eligible / reclaimed)"])
    for gk, glabel in GST_CLASSES.items():
        r = dash.max_row + 1
        dash.append([glabel, f'=SUMIFS({rng("K")},{rng("F")},A{r})', f'=SUMIFS({rng("Q")},{rng("F")},A{r})',
                     f'=SUMIFS({rng("Q")},{rng("F")},A{r},{rng("J")},"Eligible")'
                     f'+SUMIFS({rng("Q")},{rng("F")},A{r},{rng("J")},"Reclaimed")'])
    dash.append([])
    dash.append(["Review indicators", "Count / amount"])
    for label, val in (("Ledgers imported", len(sm.views)), ("Ledgers to classify", len(sm.in_scope)),
                       ("Ledgers approved", sm.count("Approved")), ("Ledgers suggested, not approved",
                                                                    sm.count("Suggested")),
                       ("Ledgers pending", sm.count("Pending")), ("Parts with eligible ITC but no GST",
                                                                  sm.missing_gst),
                       ("Unallocated amount", _f(sm.unallocated))):
        dash.append([label, val])
    for row in dash.iter_rows(min_row=4, min_col=2, max_col=4):
        for c in row:
            c.number_format = MONEY
    dash.column_dimensions["A"].width = 46
    for col in "BCD":
        dash.column_dimensions[col].width = 20
    dash.append([])
    dash.append(["Classified values are accounting classifications, not ITC entitlements. ITC comes only from GST "
                 "on invoices or an apportionment the user approved. Working paper – FIN TAX PRO files nothing."])
    wb.save(path)
    return path
