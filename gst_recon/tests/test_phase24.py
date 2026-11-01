"""Return preparation: GSTR-1, GSTR-3B, GSTR-9 and GSTR-9C in one place."""
import json
from datetime import date

import pytest

from fintax_gst.core.models import Source
from fintax_gst.samples import CLIENT
from fintax_gst.services.auth import SETUP_SESSION
from fintax_gst.services.clients import ClientService
from fintax_gst.services.common import ServiceError
from fintax_gst.services.imports import ImportService

from .test_phase4 import _full


def test_return_prep_gstr1_and_3b(db, sample_files, tmp_path):
    from openpyxl import load_workbook

    from fintax_gst.services.return_prep import MISSING, ReturnPrepService

    svc = ReturnPrepService(db)
    c, _inward, _outward = _full(db, sample_files)
    empty = svc.prepare("GSTR1", c.id, "2025-05")
    assert not empty.ready and empty.checklist[0].status == MISSING
    with pytest.raises(ServiceError, match="Not ready"):
        svc.files("GSTR1", c.id, "2025-05", tmp_path)
    g1 = svc.prepare("GSTR1", c.id, "2025-04")
    assert g1.ready and g1.figures and any(f[0].startswith("B2B") for f in g1.figures)
    files = svc.files("GSTR1", c.id, "2025-04", tmp_path / "g1", "accountant")
    js = json.loads(files[0].read_text(encoding="utf-8"))
    assert files[0].name == f"GSTR1_{c.gstin}_042025.json" and js["gstin"] == c.gstin and js["fp"] == "042025"
    g3 = svc.prepare("GSTR3B", c.id, "2025-04")
    assert g3.ready and any(f[0].startswith("6.1") for f in g3.figures)
    assert any("GSTR-1 of the month" in i.text and i.status == "warn" for i in g3.checklist)
    svc.mark_final("GSTR1", c.id, "2025-04", "manager", [p.name for p in files])
    g3 = svc.prepare("GSTR3B", c.id, "2025-04")
    assert any("GSTR-1 of the month" in i.text and i.status == "ok" for i in g3.checklist)
    f3 = svc.files("GSTR3B", c.id, "2025-04", tmp_path / "g3", "accountant", "Sharma & Co")
    assert {p.suffix for p in f3} == {".xlsx", ".pdf"}
    ws = load_workbook(f3[0])["GSTR-3B"]
    texts = [r[0].value for r in ws.iter_rows() if r[0].value]
    assert any(str(t).startswith("3.1 Details of outward") for t in texts) and any(str(t) == "6.1 Payment of tax"
                                                                                    for t in texts)
    # final, then the data changes -> marked as changed
    final = svc.prepare("GSTR1", c.id, "2025-04")
    assert final.final and not final.changed_since_final
    (tmp_path / "s.csv").write_text("GSTIN,Customer Name,Invoice No,Invoice Date,Taxable Value,CGST,SGST\n"
                                    "27AABCR1122A1Z7,Rajlaxmi,NEW/1,28-04-2025,1000,90,90\n", encoding="utf-8")
    ImportService(db).import_file(c.id, tmp_path / "s.csv", Source.SALES, "2025-04")
    assert svc.prepare("GSTR1", c.id, "2025-04").changed_since_final
    svc.reopen("GSTR1", c.id, "2025-04", "manager")
    assert svc.prepare("GSTR1", c.id, "2025-04").final is None


def test_return_prep_gstr9_and_9c(db, sample_files, tmp_path):
    from openpyxl import load_workbook

    from fintax_gst.services.gstr9c import Gstr9cService
    from fintax_gst.services.return_prep import ReturnPrepService

    c, _i, _o = _full(db, sample_files)
    svc = ReturnPrepService(db)
    g9 = svc.prepare("GSTR9", c.id, "2025-26")
    assert g9.ready and g9.figures and any("GSTR-3B of all 12 months" in i.text for i in g9.checklist)
    f9 = svc.files("GSTR9", c.id, "2025-26", tmp_path / "g9", "manager")
    assert any(p.suffix == ".json" for p in f9) and any(p.suffix == ".csv" for p in f9)
    c9 = svc.prepare("GSTR9C", c.id, "2025-26")
    assert not c9.ready and any("5A" in i.text for i in c9.checklist)
    Gstr9cService(db).set_input(c.id, "2025-26", "5A", "800000", "audited P&L", SETUP_SESSION)
    c9 = svc.prepare("GSTR9C", c.id, "2025-26")
    assert c9.ready and any(f[0].startswith("5A") for f in c9.figures)
    f9c = svc.files("GSTR9C", c.id, "2025-26", tmp_path / "g9c")
    assert load_workbook(f9c[0]).sheetnames[0] == "GSTR-9C Reconciliation"
    with pytest.raises(ServiceError):
        svc.prepare("GSTR9", c.id, "2025")
    assert date
