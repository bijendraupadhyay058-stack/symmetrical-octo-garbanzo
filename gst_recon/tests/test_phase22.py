"""Phase 22: tax audit clause 44 and books check; appeals and litigation tracker."""
from datetime import date
from decimal import Decimal as D

import pytest

from fintax_gst.core.models import Source
from fintax_gst.samples import CLIENT, gstin
from fintax_gst.services.clients import ClientService
from fintax_gst.services.common import ServiceError
from fintax_gst.services.imports import ImportService


# ------------------------------------------------------------------ clause 44 (22A)
def test_clause44(db, tmp_path):
    from openpyxl import load_workbook

    from fintax_gst.services.rcm import RcmService
    from fintax_gst.services.tax_audit import TaxAuditService

    c = ClientService(db).create(**CLIENT)
    reg, comp, ex = gstin("27", "AABCM1234K"), gstin("27", "AAFFC4321K"), gstin("27", "AABCE5555K")
    (tmp_path / "p.csv").write_text(
        "GSTIN,Supplier Name,Invoice No,Invoice Date,Taxable Value,CGST,SGST\n"
        f"{reg},Mahalaxmi,M-1,05-04-2025,100000,9000,9000\n"
        f"{reg},Mahalaxmi,M-2,06-04-2025,5000,0,0\n"
        f"{comp},Corner Store,C-1,07-04-2025,20000,0,0\n"
        f"{ex},Fresh Vegetables,V-1,08-04-2025,8000,0,0\n", encoding="utf-8")
    ImportService(db).import_file(c.id, tmp_path / "p.csv", Source.BOOKS)
    RcmService(db).add_entry(c.id, date(2025, 4, 1), "Landlord", "30000", "18")
    svc = TaxAuditService(db)
    r = svc.clause44(c.id, "2025-26")
    assert set(r.suggested_composition) == {comp, ex}
    assert (r.exempt, r.composition, r.other_registered, r.unregistered) == (D(33000), D(0), D(100000), D(30000))
    svc.save_settings(c.id, "2025-26", "2,50,000", [comp], "auditor")
    r = svc.clause44(c.id, "2025-26")
    assert (r.exempt, r.composition, r.registered_total) == (D(13000), D(20000), D(133000))
    assert r.not_in_registers == D(250000) - D(163000)
    with pytest.raises(ServiceError):
        svc.save_settings(c.id, "2025-26", "abc")
    out = svc.export_xlsx(r, c.name, c.gstin, tmp_path / "c44.xlsx")
    ws = load_workbook(out)["Clause 44"]
    assert ws["B3"].value == 250000 and ws["B8"].value == 133000


def test_books_check(db, sample_files):
    from fintax_gst.services.tax_audit import TaxAuditService

    from .test_phase4 import _full

    c, _i, _o = _full(db, sample_files)
    rows = TaxAuditService(db).books_check(c.id, "2025-26")
    april = rows[0]
    assert april["period"] == "2025-04" and len(rows) == 1
    assert april["itc_books"] and april["itc_3b"] is not None and april["itc_diff"] == april["itc_3b"] - april[
        "itc_books"]
    assert april["output_diff"] is not None


# ------------------------------------------------------------------ litigation (22B)
def test_litigation_rules():
    from fintax_gst.compliance.litigation import limitation, pre_deposit

    lim = limitation("APPEAL", date(2025, 11, 30))
    assert lim.last_date == date(2026, 2, 28) and lim.condonable_to == date(2026, 3, 30)
    assert limitation("TRIBUNAL", date(2025, 1, 31)).last_date == date(2025, 4, 30)
    assert limitation("COURT", date(2025, 1, 1)).last_date == date(2025, 6, 30)
    amt, basis = pre_deposit("APPEAL", D(1000000), D(100000))
    assert amt == D(100000) + D(90000) and "tax admitted in full" in basis
    big, basis = pre_deposit("APPEAL", D(5000000000))
    assert big == D(200000000) and "capped" in basis
    pen, basis = pre_deposit("APPEAL", D(0), penalty=D(50000))
    assert pen == D(5000) and "penalty" in basis


def test_litigation_tracker(db, tmp_path):
    from openpyxl import load_workbook

    from fintax_gst.services.auth import SETUP_SESSION
    from fintax_gst.services.litigation import LitigationService
    from fintax_gst.services.notices import NoticeService
    from fintax_gst.services.tasks import TaskService

    cs = ClientService(db)
    c = cs.create(**CLIENT)
    cs.update(c.id, "admin", staff="rahul")
    nid = NoticeService(db).add(c.id, SETUP_SESSION, form="ASMT-10", reference="ZD2711250012345",
                                notice_date=date(2025, 11, 1), period_from="2021-04", period_to="2022-03",
                                amount=D("1500000"))
    svc = LitigationService(db)
    case = svc.from_notice(nid, "manager")
    assert case.stage == "SCN" and case.tax == D(1500000) and case.notice_id == nid
    with pytest.raises(ServiceError, match="already exists"):
        svc.from_notice(nid, "manager")
    # order received: demand confirmed with interest and penalty
    case = svc.update(case.id, "manager", event="DRC-07 received", stage="ORDER", form="DRC-07",
                      order_date=date(2025, 12, 10), interest="600000", penalty="150000")
    w = svc.working(case)
    assert w["demand"] == D(2250000) and w["next_step"] == "APPEAL"
    assert w["limitation"].last_date == date(2026, 3, 10) and w["pre_deposit"] == D(150000)
    alerts = svc.alerts(today=date(2026, 3, 1))
    assert {a.kind for a in alerts} == {"limitation", "pre-deposit"}
    assert "file the appeal by 10-03-2026" in alerts[0].text
    late = svc.alerts(today=date(2026, 3, 20))
    assert "passed" in [a for a in late if a.kind == "limitation"][0].text
    assert svc.make_tasks("manager", today=date(2026, 3, 1)) == 2
    assert svc.make_tasks("manager", today=date(2026, 3, 1)) == 0  # never twice
    assert {t.task.assignee for t in TaskService(db).tasks()} == {"rahul"}
    # pre-deposit paid and appeal filed: no more time-limit alert; hearing alert instead
    svc.update(case.id, "manager", event="APL-01 filed", stage="APPEAL", form="APL-01", pre_deposit_paid="150000",
               pre_deposit_ref="DRC-03 AD2702260001", appeal_filed_on=date(2026, 2, 20), appeal_ref="AD2702260099")
    svc.add_event(case.id, date(2026, 4, 15), "hearing", "Personal hearing before the Appellate Authority",
                  "manager")
    alerts = svc.alerts(today=date(2026, 4, 10))
    assert [a.kind for a in alerts] == ["hearing"]
    ev = [e.text for e in svc.events(case.id)]
    assert any(t.startswith("Case opened") for t in ev) and "Stage: Order received (appeal not yet filed)" in ev
    assert "APL-01 filed" in ev and "Personal hearing before the Appellate Authority" in ev
    with pytest.raises(ServiceError):
        svc.update(case.id, "manager", status="MAYBE")
    out = svc.export_xlsx(tmp_path / "cases.xlsx")
    assert load_workbook(out)["Cases"].max_row == 2
    NoticeService(db).delete(nid, SETUP_SESSION)  # the case stays
    assert svc.cases(c.id)[0].notice_id is None
    svc.delete(case.id, "manager")
    assert not svc.cases(c.id)
