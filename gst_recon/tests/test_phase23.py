"""Phase 23: supplier GSTIN status and the data health check."""
from datetime import date
from decimal import Decimal as D

import pytest

from fintax_gst.core.models import Source
from fintax_gst.samples import CLIENT, gstin
from fintax_gst.services.clients import ClientService
from fintax_gst.services.common import ServiceError
from fintax_gst.services.imports import ImportService

ACT, CAN, SUS, CMP, NEW = (gstin("27", "AABCM1234K"), gstin("27", "AABCC2222K"), gstin("27", "AABCS3333K"),
                           gstin("27", "AABCP4444K"), gstin("27", "AABCN5555K"))


def _purchases(db, tmp_path, c):
    (tmp_path / "p.csv").write_text(
        "GSTIN,Supplier Name,Invoice No,Invoice Date,Taxable Value,CGST,SGST\n"
        f"{ACT},Active Co,A-1,05-04-2025,1000,90,90\n"
        f"{CAN},Closed Co,C-1,05-04-2025,1000,90,90\n"
        f"{CAN},Closed Co,C-2,20-05-2025,2000,180,180\n"
        f"{SUS},Paused Co,S-1,10-05-2025,1000,90,90\n"
        f"{CMP},Corner Store,P-1,12-05-2025,1000,90,90\n"
        f"{NEW},Never Checked,N-1,15-05-2025,500,45,45\n", encoding="utf-8")
    ImportService(db).import_file(c.id, tmp_path / "p.csv", Source.BOOKS)


def test_gstin_status(db, tmp_path):
    from openpyxl import Workbook

    from fintax_gst.services.gstin_status import GstinStatusService

    c = ClientService(db).create(**CLIENT)
    _purchases(db, tmp_path, c)
    svc = GstinStatusService(db)
    wb = Workbook()
    ws = wb.active
    ws.append(["GSTIN", "Legal Name", "Status", "Date of Cancellation", "Taxpayer Type", "Filing Frequency"])
    ws.append([ACT, "Active Co Pvt Ltd", "Active", "", "Regular", "Monthly"])
    ws.append([CAN, "Closed Co", "Cancelled", "01-05-2025", "Regular", ""])
    ws.append([SUS, "Paused Co", "Suspended", "", "Regular", ""])
    ws.append([CMP, "Corner Store", "Active", "", "Composition", "Quarterly"])
    ws.append(["27ABCDE1234F1Z9", "Bad", "Active", "", "", ""])
    wb.save(tmp_path / "status.xlsx")
    saved, problems = svc.import_file(tmp_path / "status.xlsx", "accountant")
    assert saved == 4 and len(problems) == 1
    # portal search JSON for one more
    (tmp_path / "search.json").write_text('{"gstin": "%s", "lgnm": "Active Co Pvt Ltd", "sts": "Active", '
                                          '"rgdt": "01/07/2017", "dty": "Regular"}' % ACT, encoding="utf-8")
    assert svc.import_file(tmp_path / "search.json")[0] == 1
    st = svc.get([ACT, CAN])
    assert st[CAN].cancelled_on == date(2025, 5, 1) and st[ACT].registered_on == date(2017, 7, 1)
    assert st[ACT].filing_frequency == "Monthly"  # not wiped by the later JSON without it
    flags = {f.gstin: f for f in svc.flags(c.id, today=date(2025, 6, 1))}
    assert flags[CAN].severity == "high" and flags[CAN].invoices == 1 and flags[CAN].itc == D(360)
    assert flags[SUS].severity == "high" and "hold" in flags[SUS].message
    assert flags[CMP].severity == "high" and "composition" in flags[CMP].message
    assert flags[NEW].severity == "info" and ACT not in flags
    stale = {f.gstin: f for f in svc.flags(c.id, today=date.today().replace(year=date.today().year + 1))}
    assert "check again" in stale[ACT].message
    out, n = svc.to_verify_csv(c.id, tmp_path / "verify.csv", today=date(2025, 6, 1))
    assert n == 1 and NEW in out.read_text(encoding="utf-8-sig")
    svc.save(NEW, "active", "accountant")
    assert NEW not in {f.gstin for f in svc.flags(c.id, today=date(2025, 6, 1))}
    with pytest.raises(ServiceError):
        svc.save("27ABCDE1234F1Z9", "Active")


# ------------------------------------------------------------------ data health (23B)
def test_health_check(db, sample_files, tmp_path):
    from fintax_gst.services.health import HealthService
    from fintax_gst.services.reconciliation import ReconciliationService

    from .test_phase4 import _full

    c, _inward, _outward = _full(db, sample_files)
    svc = HealthService(db)
    base = svc.check(c.id, "2025-26", date(2025, 6, 15))
    titles = [i.title for i in base.items]
    assert not any("not reconciled" in t for t in titles)  # April is reconciled both ways
    # add problems: a May register with a duplicate written differently, a bad GSTIN, a future date, odd tax
    (tmp_path / "may.csv").write_text(
        "GSTIN,Supplier Name,Invoice No,Invoice Date,Taxable Value,CGST,SGST\n"
        f"{ACT},Active Co,INV-12,05-05-2025,1000,90,90\n"
        f"{ACT},Active Co,INV/012,05-05-2025,1000,90,90\n"
        f"{ACT},Active Co,BIG-1,06-05-2025,100,90,90\n"
        f"{ACT},Active Co,FUT-1,05-05-2026,100,9,9\n", encoding="utf-8")
    ImportService(db).import_file(c.id, tmp_path / "may.csv", Source.BOOKS, "2025-05")
    rep = svc.check(c.id, "2025-26", date(2025, 6, 15))
    by = {i.area + ":" + i.title: i for i in rep.items}
    assert any(k.startswith("Duplicates:1 bill") for k in by)
    assert any(k.startswith("Dates:1 document(s) dated in the future") for k in by)
    assert any(k.startswith("Amounts:1 document(s) with impossible tax") for k in by)
    assert rep.score < base.score and rep.items[0].severity == "red"
    # a newer import for April makes the April run stale
    (tmp_path / "apr.csv").write_text("GSTIN,Supplier Name,Invoice No,Invoice Date,Taxable Value,CGST,SGST\n"
                                      f"{ACT},Active Co,LATE-1,20-04-2025,500,45,45\n", encoding="utf-8")
    ImportService(db).import_file(c.id, tmp_path / "apr.csv", Source.BOOKS, "2025-04")
    rep = svc.check(c.id, "2025-26", date(2025, 6, 15))
    stale = [i for i in rep.items if "older than the latest import" in i.title]
    assert stale and "2025-04" in stale[0].detail
    ReconciliationService(db).run(c.id, "2025-04")
    assert not [i for i in svc.check(c.id, "2025-26", date(2025, 6, 15)).items
                if "older than the latest import" in i.title]
    empty = svc.check(c.id, "2023-24")
    assert empty.items[0].title.startswith("Nothing imported")
    with pytest.raises(ServiceError):
        svc.check(999, "2025-26")
