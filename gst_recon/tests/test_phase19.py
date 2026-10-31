"""Phase 19: ITC claim plan and the year-end closing pack."""
from datetime import date
from decimal import Decimal as D

import pytest

from fintax_gst.core.models import DocType
from fintax_gst.services.common import ServiceError

from .conftest import GSTIN_A, GSTIN_B, rec


def _b(no, period, dt, db_id, tax="90", **kw):
    r = rec("B", no, dt, cgst=tax, sgst=tax, period=period, **kw)
    r.db_id = db_id
    return r


# ------------------------------------------------------------------ claim plan (19A)
def test_claim_plan_buckets_across_months():
    from fintax_gst.itc.claim_plan import BARRED, CHECK, CLAIM, HOLD, WRITTEN_OFF, build_plan

    books = [
        _b("A-1", "2025-04", "2025-04-05", 1),                    # in April 2B
        _b("A-2", "2025-04", "2025-04-08", 2),                    # supplier reports it only in June
        _b("A-3", "2025-04", "2025-04-09", 3),                    # never reported
        _b("A-4", "2025-05", "2025-05-02", 4),                    # 2B shows less tax
        _b("A-5", "2025-05", "2025-05-03", 5),                    # open blocked-credit flag
        _b("A-6", "2025-05", "2025-05-04", 6),                    # already claimed
        _b("A-7", "2025-05", "2025-05-05", 7),                    # written off
        _b("OLD-1", "2024-04", "2024-04-10", 8),                  # FY 2024-25, limit 30-11-2025
        _b("CN-1", "2025-06", "2025-06-02", 9, doc=DocType.CREDIT_NOTE),
    ]
    g = [rec("G", "A-1", "2025-04-05", period="2025-04"), rec("G", "a/2", "2025-04-08", period="2025-06"),
         rec("G", "A-4", "2025-05-02", cgst="50", sgst="50", period="2025-05"),
         rec("G", "A-5", "2025-05-03", period="2025-05"), rec("G", "A-6", "2025-05-04", period="2025-05"),
         rec("G", "CN-1", "2025-06-02", period="2025-06", doc=DocType.CREDIT_NOTE),
         rec("G", "Z-9", "2025-06-01", period="2025-06", gstin=GSTIN_B),       # not in books
         rec("G", "A-9", "2025-07-01", period="2025-07")]                      # after the month: ignored
    plan = build_plan("2025-06", books, g, claimed={6}, flags={5: "Blocked credit – motor vehicle"},
                      written_off={7: "supplier closed"}, as_of=date(2025, 12, 5))
    by = {ln.doc.invoice_no: ln for ln in plan.lines}
    assert "A-6" not in by
    assert by["A-1"].bucket == CLAIM and "carried forward from 2025-04" in by["A-1"].reason
    assert by["A-2"].bucket == CLAIM and by["A-2"].gstr2b_period == "2025-06"
    assert by["A-3"].bucket == HOLD and by["A-3"].months_pending == 2 and by["A-3"].days_left == 360
    assert by["A-4"].bucket == CHECK and "GSTR-2B shows tax ₹100.00" in by["A-4"].reason
    assert by["A-5"].bucket == CHECK and "motor vehicle" in by["A-5"].reason
    assert by["A-7"].bucket == WRITTEN_OFF and by["A-7"].reason == "supplier closed"
    assert by["OLD-1"].bucket == BARRED  # 30-11-2025 has passed on 05-12-2025
    assert by["CN-1"].bucket == CLAIM and by["CN-1"].itc == D(-180) and by["CN-1"].deadline is None
    assert [x.invoice_no for x in plan.not_in_books] == ["Z-9"]
    assert plan.total(CLAIM) == D(180)  # A-1 + A-2 (360) less the credit note (180)
    # in May the June-reported invoice is still on hold
    may = build_plan("2025-05", books, g, set(), {}, {}, date(2025, 6, 10))
    assert {ln.doc.invoice_no: ln.bucket for ln in may.lines}["A-2"] == HOLD
    near = build_plan("2025-06", books, [], set(), {}, {}, date(2025, 10, 15))
    assert "follow up now" in {ln.doc.invoice_no: ln for ln in near.lines}["OLD-1"].reason
    assert GSTIN_A


def test_claim_plan_service(db, sample_files, tmp_path):
    from openpyxl import load_workbook

    from fintax_gst.itc.claim_plan import CLAIM, HOLD, WRITTEN_OFF
    from fintax_gst.services.claim_plan import ClaimPlanService
    from fintax_gst.services.itc import ItcService

    from .test_phase4 import _full

    c, inward, _outward = _full(db, sample_files)
    svc = ClaimPlanService(db)
    plan = svc.build(c.id, "2025-04", date(2025, 5, 15))
    assert plan.bucket(CLAIM) and plan.bucket(HOLD)
    assert any("not yet in GSTR-2B" in ln.reason for ln in plan.bucket(HOLD))
    ids = [ln.doc.db_id for ln in plan.bucket(CLAIM)]
    res = svc.record_claims(c.id, "2025-04", ids, "accountant", date(2025, 5, 15))
    assert sorted(res.claimed) == sorted(ids)
    after = svc.build(c.id, "2025-04", date(2025, 5, 15))
    assert not after.bucket(CLAIM)
    hold = after.bucket(HOLD)[0].doc.db_id
    with pytest.raises(ServiceError, match="cannot be claimed"):
        svc.record_claims(c.id, "2025-04", [hold], as_of=date(2025, 5, 15))
    with pytest.raises(ServiceError, match="reason"):
        svc.write_off(c.id, [hold], " ")
    svc.write_off(c.id, [hold], "supplier has stopped business", "manager")
    assert [ln.doc.db_id for ln in svc.build(c.id, "2025-04", date(2025, 5, 15)).bucket(WRITTEN_OFF)] == [hold]
    assert svc.undo_write_off(c.id, [hold], "manager") == 1
    assert ItcService(db).claim_register(c.id, ["2025-04"])
    out = svc.export_xlsx(after, c.name, tmp_path / "plan.xlsx")
    wb = load_workbook(out)
    assert wb.sheetnames == ["Summary", "Documents", "Not in books"] and wb["Documents"].max_row == len(after.lines) + 1
