"""Interest (section 50) and late fee (section 47) working as an Excel workbook."""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from ..services.interest import HEADS, KINDS, InterestWorking
from .excel_report import _register_styles, _Sheet, _write_table, section_label


def build_interest_workbook(client, w: InterestWorking) -> Workbook:
    wb = Workbook(write_only=True)
    _register_styles(wb)
    sh = _Sheet(wb, "Interest & Late Fee", [10, 12, 12, 12, 8, 12, 12, 40, 13, 13, 13, 13, 13, 13])
    sh.banner(f"Interest and late fee working – {client.name} ({client.gstin}) – FY {w.fy}, as of "
              f"{w.as_of:%d-%m-%Y}",
              "Section 50 interest at 18% p.a.; section 47 late fees with the notified caps. A working paper – the "
              "amounts levied by the portal are the ones to pay.", 14)
    sh.append([section_label(sh, "RETURNS FILED LATE")])
    _write_table(sh, ["Return", "Period", "Due", "Filed", "Days", "Late fee CGST", "Late fee SGST/UTGST",
                      "Late fee basis", "Cash paid (6.1)", "Interest IGST", "Interest CGST", "Interest SGST",
                      "Interest paid (6.1)", "Late fee paid (6.1)"],
                 [[r.return_type, r.period, r.due, r.filed, r.days, r.fee_cgst, r.fee_sgst, r.fee_basis,
                   r.cash.total if r.cash is not None else None, r.interest.get("igst"), r.interest.get("cgst"),
                   r.interest.get("sgst"), r.interest_paid, r.fee_paid] for r in w.late],
                 ["text", "text", "date", "date", "int", "money", "money", "wrap", "money", "money", "money",
                  "money", "money", "money"], name="LateReturns")
    sh.append([])
    sh.append([section_label(sh, "TAX SHORT PAID AND ITC ABOVE GSTR-2B")])
    _write_table(sh, ["Kind", "Period", "Head", "Amount", "From", "To", "Days", "Interest", "Status", "Basis",
                      "Reference"],
                 [[KINDS[e.kind], e.period, e.head.upper(), e.amount, e.start, e.end, e.days, e.interest, e.status,
                   e.basis, e.reference] for e in w.exposures],
                 ["wrap", "text", "text", "money", "date", "date", "int", "money", "text", "wrap", "text"],
                 name="Exposures")
    sh.append([])
    sh.append([section_label(sh, "DRC-03 SUMMARY – NOT YET PAID")])
    d = w.drc03()
    _write_table(sh, ["Head", "Tax", "Interest", "Late fee"],
                 [[h.upper(), d[h]["tax"], d[h]["interest"], d[h]["fee"]] for h in HEADS],
                 ["text", "money", "money", "money"], name="Drc03")
    sh.append([])
    for n in w.notes:
        sh.append([sh.cell(n, "ftp_note")])
    return wb


def export_interest(db, client_id: int, fy: str, out_dir, as_of=None, user: str | None = None) -> Path:
    from ..services.clients import ClientService
    from ..services.common import audit
    from ..services.interest import InterestService

    client = ClientService(db).get(client_id)
    w = InterestService(db).working(client_id, fy, as_of)
    out = Path(out_dir) / f"FINTAXPRO_Interest_LateFee_{client.gstin}_FY{fy}.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.xlsx")
    build_interest_workbook(client, w).save(tmp)
    tmp.replace(out)
    with db.session() as s:
        audit(s, "EXPORT", "interest_working", f"{client_id}:{fy}", {"file": str(out), "as_of": w.as_of}, user,
              client_id)
    return out
