"""Annual ITC workbook: GSTR-9 Table 8 working, month-wise ITC, document lists and claim register."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

from .. import TAGLINE
from ..importers.gstr3b import Gstr3bValues
from ..itc.annual import Table8
from .excel_report import _register_styles, _Sheet, _write_table, section_label


def _vals(v: Gstr3bValues) -> list:
    return [v.igst, v.cgst, v.sgst, v.cess, v.total]


def build_annual(client, t: Table8, claims, rules, gstr9=None) -> Workbook:
    wb = Workbook(write_only=True)
    _register_styles(wb)
    sh = _Sheet(wb, "Table 8 Summary", [64, 15, 15, 15, 13, 16])
    sh.banner(f"GSTR-9 Table 8 working – FY {t.fy}", TAGLINE, 6)
    for k, v in (("Client", f"{client.name} ({client.gstin})"), ("Financial year", t.fy),
                 ("GSTR-2B periods included in 8A", f"April {t.fy[:4]} to {t.cutoff}"),
                 ("Prepared on", f"{datetime.now():%d-%m-%Y %H:%M}")):
        sh.append([section_label(sh, k), v])
    sh.append([])
    basis = "portal Table 8A" if t.basis == "portal" else "GSTR-2B, computed"
    rows = [[f"8A ITC as per GSTR-2B ({basis}; B2B, B2BA, CDNR; excl. RCM, ISD, imports, ITC not available)",
             *_vals(t.a)],
            ["8B ITC availed in GSTR-3B Table 4(A)(5) of the year", *_vals(t.b)],
            ["8C ITC of the year availed in next year's periods (claim register)", *_vals(t.c)],
            ["8D Difference 8A − (8B + 8C)", *_vals(t.d)]]
    _write_table(sh, ["Table 8", "IGST", "CGST", "SGST", "Cess", "Total"], rows,
                 ["text", "money", "money", "money", "money", "money"], name="Table8", totals=False)
    sh.append([])
    notes = [
        "Positive 8D: ITC in GSTR-2B not availed – check whether it lapses after the Section 16(4) time limit.",
        "Negative 8D: more ITC availed than reflected in GSTR-2B – verify (Section 16(2)(aa)).",
    ]
    notes[:0] = t.basis_notes()
    if t.b_periods_missing:
        notes.append("GSTR-3B not imported for: " + ", ".join(t.b_periods_missing) + " – 8B is incomplete.")
    for n in notes:
        sh.append([sh.cell(n, "ftp_note")])

    m = _Sheet(wb, "Month-wise ITC", [10, 16, 16, 16, 16, 16, 16, 16])
    m.banner("Month-wise ITC", "Books by booking month, GSTR-2B by return period, GSTR-3B as imported", 8)
    _write_table(m, ["Month", "Books ITC", "GSTR-2B ITC", "3B 4(A)(5)", "3B 4(B) Reversed", "3B 4(C) Net",
                     "Claimed (register)", "3B − 2B"],
                 [[x.month, x.books_itc, x.gstr2b_itc, x.filed_4a5, x.filed_4b, x.filed_4c, x.claimed_register,
                   (x.filed_4a5 - x.gstr2b_itc) if x.filed_4a5 is not None else None] for x in t.months],
                 ["text", "money", "money", "money", "money", "money", "money", "money"])

    def docs_sheet(title, docs, note):
        d = _Sheet(wb, title, [18, 28, 12, 18, 12, 9, 15, 15])
        d.banner(title, note, 8)
        _write_table(d, ["Supplier GSTIN", "Supplier", "Type", "Invoice No", "Date", "Period", "Taxable", "ITC"],
                     [[r.supplier_gstin, r.supplier_name, r.doc_type.label, r.invoice_no, r.invoice_date, r.period,
                       r.signed("taxable"), r.signed("itc")] for r in docs],
                     ["text", "text", "text", "text", "date", "text", "money", "money"],
                     name=title.replace(" ", ""))

    docs_sheet("8A Docs Not in Books", t.docs_8a_not_in_books, "In GSTR-2B (Table 8A) but not in the purchase register")
    docs_sheet("Books Not in 8A", t.books_not_in_8a, "In the purchase register but not in Table 8A")
    if t.basis == "portal":
        docs_sheet("8A Not in GSTR-2B", t.portal_not_in_2b,
                   "In the portal's Table 8A but not in the GSTR-2B periods imported (e.g. filed late by the supplier)")
        docs_sheet("GSTR-2B Not in 8A", t.gstr2b_not_in_portal, "In the imported GSTR-2B but not in Table 8A")

    c = _Sheet(wb, "Claim Register", [9, 10, 18, 18, 12, 15, 15, 40, 18, 14])
    c.banner("ITC claim register", "Every claim, reversal and reclaim recorded for the year (audited)", 10)
    _write_table(c, ["Period", "Action", "Supplier GSTIN", "Invoice No", "Date", "Tax (doc)", "Amount", "Reason",
                     "Rule ref", "By"],
                 [[cl.period, cl.action, inv.supplier_gstin, inv.invoice_no, inv.invoice_date,
                   inv.igst + inv.cgst + inv.sgst + inv.cess, cl.igst + cl.cgst + cl.sgst + cl.cess, cl.reason,
                   cl.rule_ref, cl.user] for cl, inv in claims],
                 ["text", "text", "text", "text", "date", "money", "money", "wrap", "text", "text"])

    r = _Sheet(wb, "ITC Rules Applied", [22, 46, 52, 10, 9, 12, 12, 60])
    r.banner("ITC review rules", "Rules and settings in force when this workbook was prepared", 8)
    _write_table(r, ["Code", "Rule", "Reference", "Severity", "Enabled", "From", "To", "Keywords / GSTINs / parameters"],
                 [[x.code, x.title, x.reference, x.severity, "Yes" if x.enabled else "No", x.effective_from,
                   x.effective_to, ", ".join(x.keywords or x.gstins) or (str(x.params) if x.params else "")]
                  for x in rules],
                 ["text", "wrap", "wrap", "text", "text", "date", "date", "wrap"], totals=False)
    if gstr9 is not None:
        from .gstr9_sheets import gstr9_sheets

        gstr9_sheets(wb, gstr9)
    return wb


def export_annual(db, client_id: int, fy: str, out_dir: str | Path, cutoff: str | None = None,
                  portal_8a=None, user: str | None = None) -> Path:
    from ..services.clients import ClientService
    from ..services.common import audit
    from ..services.itc import ItcService
    from ..services.reconciliation import months_between

    itc = ItcService(db)
    client = ClientService(db).get(client_id)
    t = itc.annual(client_id, fy, cutoff, portal_8a)
    claims = itc.claim_register(client_id, months_between(f"{fy[:4]}-04", t.cutoff))
    from ..services.gstr9 import Gstr9Service

    wb = build_annual(client, t, claims, itc.rules(client_id), Gstr9Service(db).working(client_id, fy))
    out = Path(out_dir) / f"FINTAXPRO_GSTR9_Working_{client.gstin}_FY{fy}.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.xlsx")
    wb.save(tmp)
    tmp.replace(out)
    with db.session() as s:
        audit(s, "EXPORT", "annual", fy, {"file": str(out), "8A": str(t.a.total), "8D": str(t.d.total)}, user,
              client_id)
    return out
