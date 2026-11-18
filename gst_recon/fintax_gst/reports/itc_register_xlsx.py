"""ITC classification workbook (19 sheets): the original Tally postings, the consolidated register with every part's
nature / GST treatment / ITC status, the filtered registers, GSTR-2B and GSTR-3B reconciliation, GSTR-9 Tables 6–8,
GSTR-9C Tables 12–14, mapping rules, the manual adjustment history, exceptions and the final ITC summary. Table 6 is
built with SUMIFS over the register so a change in the register recalculates it."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from ..ledgers.itc_classes import AVAILED, GOODS, NATURES, RCM, SCOPES, STATUSES, TREATMENTS

HEAD_FILL = PatternFill("solid", fgColor="1F3864")
RED = PatternFill("solid", fgColor="FFCDD2")
AMBER = PatternFill("solid", fgColor="FFF3C4")
GREEN = PatternFill("solid", fgColor="C8E6C9")
MONEY = "#,##,##0.00;[Red]-#,##,##0.00"
TYPE = {"inputs": "Inputs", "services": "Input services", "capital": "Capital goods"}


def _f(v):
    return None if v is None else float(v)


def _sheet(wb, title, head, widths=()):
    ws = wb.create_sheet(title[:31])
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = HEAD_FILL
    ws.freeze_panes = "A2"
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    return ws


def _finish(ws, money: str = ""):
    if ws.max_row > 1:
        ws.auto_filter.ref = f"A1:{get_column_letter(ws.max_column)}{ws.max_row}"
    for col in money.split(",") if money else []:
        for c in ws[col][1:]:
            c.number_format = MONEY


def build_workbook(svc, client_id: int, fy: str, path: Path) -> Path:
    from ..services.itc_register import T6_ROWS, TREAT_ROW, _type

    w = svc.working(client_id, fy)
    wb = Workbook()
    summary = wb.active
    summary.title = "Final ITC Summary"

    # 1 original postings
    with svc.db.session() as s:
        from sqlalchemy import select

        from ..db.models import AuditLog, LedgerMapping, TaxPosting

        posts = list(s.scalars(select(TaxPosting).where(TaxPosting.client_id == client_id,
                                                        TaxPosting.financial_year == fy).order_by(TaxPosting.id)))
        history = list(s.scalars(select(AuditLog).where(AuditLog.client_id == client_id, AuditLog.action.in_([
            "ITC_CLASSIFY", "ITC_SPLIT", "ITC_UNDO", "ITC_UNDONE", "ITC_RULE_ADD", "ITC_RULE_OFF", "ITC_FINALISE",
            "ITC_REOPEN", "ITC_TXN_REMOVED"])).order_by(AuditLog.id)))
        maps = list(s.scalars(select(LedgerMapping).where(LedgerMapping.client_id == client_id)))
        s.expunge_all()
    imp = _sheet(wb, "Import Data", ["Tax ledger", "Head", "Kind", "Date", "Vch type", "Vch no", "Particulars",
                                     "Amount (Dr +, Cr −)", "Source row"], (22, 7, 9, 12, 14, 12, 36, 18, 22))
    for p in posts:
        imp.append([p.ledger, p.head.upper(), p.kind, p.entry_date, p.voucher_type, p.voucher_no, p.particulars,
                    _f(p.amount), p.row_ref])
    if not posts:
        imp.append(["(input tax ledgers not imported – the register is built from the purchase register)"])
    _finish(imp, "H")

    # 2 consolidated register (one row per part)
    reg = _sheet(wb, "Consolidated ITC Register",
                 ["Txn", "Part", "Date", "Period", "Vch type", "Vch no", "Supplier", "GSTIN", "Invoice no",
                  "Invoice date", "Ledger", "HSN/SAC", "Nature", "GST treatment", "ITC status", "GSTR-9 row", "Type",
                  "Availed", "Taxable value", "IGST", "CGST", "SGST/UTGST", "Cess", "Total tax", "Basis", "Confidence",
                  "Source match", "Reason", "Source reference"],
                 (7, 5, 11, 8, 12, 10, 28, 17, 16, 11, 24, 10, 20, 22, 20, 7, 13, 7, 15, 12, 12, 12, 10, 13, 9, 11,
                  10, 40, 30))
    for v in w.views:
        if v.is_adjustment:
            continue
        t = v.txn
        for i, p in enumerate(v.parts or [None], start=1):
            r = reg.max_row + 1
            if p is None:
                reg.append([t.id, i, t.voucher_date, t.period, t.voucher_type, t.voucher_no, t.party, t.gstin,
                            t.invoice_no, t.invoice_date, t.ledger, t.hsn, "(none)"])
                continue
            typ = _type(p.nature)
            reg.append([t.id, i, t.voucher_date, t.period, t.voucher_type, t.voucher_no, t.party, t.gstin, t.invoice_no,
                        t.invoice_date, t.ledger, t.hsn, NATURES[p.nature], TREATMENTS.get(p.treatment, p.treatment),
                        STATUSES[p.status], TREAT_ROW.get(p.treatment or "fcm", "6B"), TYPE.get(typ, "—"),
                        "Yes" if p.status in AVAILED else "No", _f(p.taxable), _f(p.igst), _f(p.cgst), _f(p.sgst),
                        _f(p.cess), f"=SUM(T{r}:W{r})", p.basis, p.confidence, t.match, p.reason, t.source_ref])
    last = max(reg.max_row, 2)
    reg.conditional_formatting.add(f"M2:M{last}", FormulaRule(formula=['M2="Unclassified – review"'], fill=RED))
    reg.conditional_formatting.add(f"Z2:Z{last}", FormulaRule(formula=['OR(Z2="low",Z2="manual")'], fill=AMBER))
    dv = DataValidation(type="list", formula1='"' + ",".join(NATURES.values()) + '"', allow_blank=True)
    reg.add_data_validation(dv)
    dv.add(f"M2:M{last}")
    _finish(reg, "S,T,U,V,W,X")

    def rng(col):
        return f"'Consolidated ITC Register'!${col}$2:${col}${last}"

    # 3-8 filtered registers
    def filtered(title, keep):
        ws = _sheet(wb, title, ["Date", "Supplier", "GSTIN", "Invoice no", "Ledger", "Nature", "GST treatment",
                                "ITC status", "Taxable value", "IGST", "CGST", "SGST", "Cess", "Total tax"],
                    (11, 28, 17, 16, 24, 20, 22, 20, 15, 12, 12, 12, 10, 13))
        for v in w.txns:
            for p in v.parts:
                if keep(v, p):
                    r = ws.max_row + 1
                    ws.append([v.txn.voucher_date, v.txn.party, v.txn.gstin, v.txn.invoice_no, v.txn.ledger,
                               NATURES[p.nature], TREATMENTS.get(p.treatment, p.treatment), STATUSES[p.status],
                               _f(p.taxable), _f(p.igst), _f(p.cgst), _f(p.sgst), _f(p.cess), f"=SUM(J{r}:M{r})"])
        r = ws.max_row
        ws.append(["Total", "", "", "", "", "", "", "", *(f"=SUBTOTAL(9,{c}2:{c}{max(r, 2)})" for c in "IJKLMN")])
        ws.cell(r + 1, 1).font = Font(bold=True)
        _finish(ws, "I,J,K,L,M,N")

    filtered("Trading Purchase ITC", lambda v, p: p.nature == "trading")
    filtered("Raw Material & Other Goods", lambda v, p: p.nature in ("raw", "other_goods"))
    filtered("Input Services", lambda v, p: p.nature == "services")
    filtered("Capital Goods", lambda v, p: p.nature == "capital")
    filtered("RCM Transactions", lambda v, p: p.treatment in RCM or p.treatment == "import_s")
    filtered("Ineligible & Reversed ITC", lambda v, p: p.status in ("blocked", "reversal", "temp_reversed"))

    # 9 GSTR-2B reconciliation (month by month)
    from ..services.return_compare import ReturnCompareService

    comp = ReturnCompareService(svc.db).compare("3B_2B", client_id, fy)
    m2b = _sheet(wb, "GSTR-2B Reconciliation", ["Month", "ITC in the register (books)", "ITC in GSTR-2B",
                                                "ITC claimed in GSTR-3B", "Books − 2B", "3B − 2B"],
                 (12, 22, 18, 22, 16, 16))
    reg_month: dict[str, Decimal] = {}
    for v in w.txns:
        reg_month[v.txn.period] = reg_month.get(v.txn.period, Decimal(0)) + v.tax
    for row in comp.rows:
        r = m2b.max_row + 1
        m2b.append([row.label, _f(sum((reg_month.get(m, Decimal(0)) for m in row.months), Decimal(0))),
                    _f(row.right.total) if row.right is not None else None,
                    _f(row.left.total) if row.left is not None else None,
                    f'=IF(C{r}="","",B{r}-C{r})', f'=IF(OR(C{r}="",D{r}=""),"",D{r}-C{r})'])
    m2b.conditional_formatting.add(f"E2:F{m2b.max_row}", FormulaRule(formula=['AND(E2<>"",ABS(E2)>1)'], fill=AMBER))
    _finish(m2b, "B,C,D,E,F")

    # 10 GSTR-3B reconciliation (Table 6 rows vs GSTR-3B Table 4)
    r3b = _sheet(wb, "GSTR-3B Reconciliation", ["Row", "Register IGST", "Register CGST", "Register SGST",
                                                "Register cess", "GSTR-3B IGST", "GSTR-3B CGST", "GSTR-3B SGST",
                                                "GSTR-3B cess", "Difference (total)"], (44,) + (14,) * 9)
    for row, label in T6_ROWS.items():
        ours = {h: sum((getattr(b, h) for b in w.table6[row].values()), Decimal(0)) for h in ("igst", "cgst", "sgst",
                                                                                               "cess")}
        b3 = w.table6_3b.get(row)
        r = r3b.max_row + 1
        r3b.append([label, *(_f(ours[h]) for h in ("igst", "cgst", "sgst", "cess")),
                    *((_f(b3[h]) for h in ("igst", "cgst", "sgst", "cess")) if b3 else (None,) * 4),
                    f'=IF(F{r}="","",SUM(B{r}:E{r})-SUM(F{r}:I{r}))'])
    r3b.append([])
    r3b.append(["6C and 6D are compared together with GSTR-3B 4(A)(3); differences are shown, never adjusted."])
    r3b.conditional_formatting.add(f"J2:J{r3b.max_row}", FormulaRule(formula=['AND(J2<>"",ABS(J2)>1)'], fill=RED))
    _finish(r3b, "B,C,D,E,F,G,H,I,J")

    # 11 GSTR-9 Table 6 working (formulas over the register)
    t6 = _sheet(wb, "GSTR-9 Table 6 Working", ["Row", "Category", "Taxable value", "IGST", "CGST", "SGST/UTGST",
                                               "Cess", "Total ITC"], (46, 16, 16, 14, 14, 14, 12, 15))
    for row, label in T6_ROWS.items():
        first = t6.max_row + 1
        cats = ("inputs", "services", "capital")
        for typ in cats:
            r = t6.max_row + 1
            if row == "6H":
                cells = [f'=SUMIFS({rng(c)},{rng("O")},"{STATUSES["reclaimed"]}",{rng("Q")},"{TYPE[typ]}")'
                         for c in "STUVW"]
            else:
                cells = [f'=SUMIFS({rng(c)},{rng("P")},"{row}",{rng("Q")},"{TYPE[typ]}",{rng("R")},"Yes")'
                         for c in "STUVW"]
            t6.append([label, TYPE[typ], *cells, f"=SUM(D{r}:G{r})"])
        r = t6.max_row + 1
        t6.append([f"{row} total", "", *(f"=SUM({c}{first}:{c}{r - 1})" for c in "CDEFGH")])
        t6.cell(r, 1).font = Font(bold=True)
    t6.append([])
    t6.append(["Only parts with ITC status Eligible / Reclaimed / Partially eligible count as availed. Domestic RCM "
               "is in 6C / 6D (never 6B); import of services in 6F."])
    _finish(t6, "C,D,E,F,G,H")

    # 12 Tables 7 and 8
    t78 = _sheet(wb, "GSTR-9 Tables 7 and 8", ["Row", "Particulars", "IGST", "CGST", "SGST", "Cess", "Total"],
                 (10, 52, 14, 14, 14, 12, 15))
    for key, b in w.table7.items():
        r = t78.max_row + 1
        t78.append(["7 (working)", b.label, _f(b.igst), _f(b.cgst), _f(b.sgst), _f(b.cess), f"=SUM(C{r}:F{r})"])
    if w.table8 is not None:
        t8 = w.table8
        for code, label, v in (("8A", "ITC as per GSTR-2B (Table 8A)", t8.a), ("8B", "ITC as per 6B and 6H", t8.b),
                               ("8C", "ITC of the year availed in the next year", t8.c),
                               ("8D", "Difference A − (B + C)", t8.d)):
            r = t78.max_row + 1
            t78.append([code, label, _f(v.igst), _f(v.cgst), _f(v.sgst), _f(v.cess), f"=SUM(C{r}:F{r})"])
    else:
        t78.append(["8", "Table 8 not available (GSTR-2B / GSTR-3B not imported)"])
    _finish(t78, "C,D,E,F,G")

    # 13-15 GSTR-9C
    t12 = _sheet(wb, "GSTR-9C Table 12", ["Row", "Particulars", "Amount", "Source"], (7, 60, 18, 30))
    for code, label, amount, src in w.table12:
        t12.append([code, label, _f(amount), src])
    t12.append([])
    t12.append(["", "Book figures are the register's; enter the figure per the audited accounts in GSTR-3B & annual → "
                "GSTR-9C if it differs. Input tax ledger balances alone are not the books' ITC."])
    _finish(t12, "C")
    t13 = _sheet(wb, "GSTR-9C Table 13 Differences", ["Possible reason", "Amount", "Evidence", "Explanation"],
                 (48, 16, 30, 60))
    for label, amount, why in w.table13:
        t13.append([label, _f(amount), why, ""])
    _finish(t13, "B")
    t14 = _sheet(wb, "GSTR-9C Table 14", ["Row", "Expense head", "Value", "Total tax", "Eligible ITC availed"],
                 (7, 46, 16, 16, 18))
    for code, label, val, tax, elig in w.table14:
        t14.append([code, label, _f(val), _f(tax), _f(elig)])
    r = t14.max_row
    t14.append(["", "Total", *(f"=SUM({c}2:{c}{max(r, 2)})" for c in "CDE")])
    t14.append([])
    t14.append(["", "Working prepared even where the year's instructions let Table 14 be left blank – check the "
                "notification for the year."])
    _finish(t14, "C,D,E")

    # 16 rules
    rl = _sheet(wb, "Ledger Mapping Rules", ["Rule", "Applies to", "Value", "and ledger", "Nature", "GST treatment",
                                             "ITC status", "Year", "Active", "By", "Note"],
                (7, 26, 28, 22, 20, 22, 20, 9, 7, 12, 30))
    for r_ in svc.rules(client_id):
        rl.append([r_.id, SCOPES.get(r_.scope, r_.scope), r_.value, r_.value2, NATURES.get(r_.nature, ""),
                   TREATMENTS.get(r_.treatment, ""), STATUSES.get(r_.status, ""), r_.financial_year or "every year",
                   "yes" if r_.active else "no", r_.created_by, r_.note])
    for m in maps:
        rl.append(["ledger", "Ledger classification (approved)", m.ledger_key, "", m.acct_class, m.gst_source,
                   m.eligibility, "every year", "yes", m.approved_by, f"GST class {m.gst_class}"])
    _finish(rl)

    # 17 history
    hi = _sheet(wb, "Manual Adjustment History", ["When (UTC)", "User", "Action", "Transaction", "Reason", "Before",
                                                  "After"], (19, 14, 16, 12, 30, 50, 50))
    for a in history:
        d = json.loads(a.details_json or "{}")
        hi.append([a.at, a.user, a.action, a.entity_id, d.get("reason", ""), json.dumps(d.get("before", ""))[:1000],
                   json.dumps(d.get("after", ""))[:1000]])
    _finish(hi)

    # 18 exceptions
    ex = _sheet(wb, "Unclassified & Exceptions", ["Kind", "Date", "Supplier", "Invoice / voucher", "Tax", "Detail"],
                (26, 11, 30, 18, 14, 70))
    for v in w.views:
        t = v.txn
        kinds = []
        if v.is_adjustment:
            kinds.append(("Set-off / adjustment posting", "kept out of the purchases"))
        if t.match == "taxledger":
            kinds.append(("Tax ledger only", "no purchase-register document – check the posting"))
        if t.match == "differs":
            kinds.append(("Tax differs", f"tax ledger {t.ledger_tax_json}"))
        for p in v.parts:
            if p.nature == "unclassified":
                kinds.append(("Unclassified", p.reason))
            elif p.basis == "auto" and p.confidence in ("low", "manual"):
                kinds.append(("Low confidence", p.reason))
            if p.status == "pending":
                kinds.append(("ITC status pending", "verify eligibility / claim"))
        for kind, detail in kinds:
            ex.append([kind, t.voucher_date, t.party, t.invoice_no or t.voucher_no, _f(v.tax), detail])
    for c in w.controls:
        if c.status != "pass":
            ex.append([f"Control {c.code}", None, c.title, "", None, c.detail])
    _finish(ex, "E")

    # 19 summary (first sheet)
    summary.append([f"{w.client} ({w.gstin}) – ITC classification & reconciliation, FY {w.fy}"])
    summary["A1"].font = Font(bold=True, size=13)
    summary.append(["FINAL – " + f"{w.final['by']} on {w.final['on']}" if w.final else "Not final (working paper)"])
    summary.append([])
    summary.append(["ITC overview", "IGST", "CGST", "SGST/UTGST", "Cess", "Total"])
    for c in summary[4]:
        c.font = Font(bold=True)
    if posts:
        r = summary.max_row + 1
        summary.append(["Input tax ledgers (vouchers)", *(_f(w.postings_total[h]) for h in ("igst", "cgst", "sgst",
                                                                                           "cess")),
                        f"=SUM(B{r}:E{r})"])
    for label, keys, dim in (("ITC as per books (register)", list(STATUSES), "status"),
                             ("Eligible ITC (eligible / reclaimed / partial)", list(AVAILED), "status"),
                             ("ITC reversed / reversal required", ["reversal", "temp_reversed"], "status"),
                             ("Ineligible / blocked", ["blocked"], "status"),
                             ("Not yet claimed", ["not_claimed"], "status"),
                             ("Pending verification", ["pending"], "status")):
        b = w.total(dim, keys)
        r = summary.max_row + 1
        summary.append([label, _f(b.igst), _f(b.cgst), _f(b.sgst), _f(b.cess), f"=SUM(B{r}:E{r})"])
    b3 = {h: sum((v[h] for v in w.table6_3b.values() if v), Decimal(0)) for h in ("igst", "cgst", "sgst", "cess")}
    if any(w.table6_3b.values()):
        r = summary.max_row + 1
        summary.append(["ITC claimed in GSTR-3B (Table 4A + 4D1)", *(_f(b3[h]) for h in ("igst", "cgst", "sgst",
                                                                                          "cess")),
                        f"=SUM(B{r}:E{r})"])
    summary.append([])
    summary.append(["Classification overview", "Count", "Taxable", "Total tax"])
    for c in summary[summary.max_row]:
        c.font = Font(bold=True)
    for k, b in w.by_nature.items():
        summary.append([NATURES[k], b.count, _f(b.taxable), _f(b.tax)])
    rcm = w.total("treatment", list(RCM))
    imp_ = w.total("treatment", ["import_g", "import_s"])
    summary.append(["RCM ITC (overlay)", rcm.count, _f(rcm.taxable), _f(rcm.tax)])
    summary.append(["Import ITC (overlay)", imp_.count, _f(imp_.taxable), _f(imp_.tax)])
    summary.append([])
    summary.append(["Controls", "Status", "Detail"])
    for c in summary[summary.max_row]:
        c.font = Font(bold=True)
    for c in w.controls:
        summary.append([f"{c.code} {c.title}", c.status.upper(), c.detail])
        summary.cell(summary.max_row, 2).fill = GREEN if c.status == "pass" else RED if c.status == "fail" else AMBER
    for row in summary.iter_rows(min_row=5, min_col=2, max_col=6):
        for c in row:
            if isinstance(c.value, (float, str)) and not (isinstance(c.value, str) and not c.value.startswith("=")):
                c.number_format = MONEY
    summary.column_dimensions["A"].width = 50
    for col in "BCDEF":
        summary.column_dimensions[col].width = 16
    summary.append([])
    summary.append(["Working papers for the professional's review – FIN TAX PRO does not file returns. Differences are "
                    "shown, never adjusted."])
    _ = GOODS  # (goods natures are summed as 'Inputs' in Table 6)
    wb.save(path)
    return path
