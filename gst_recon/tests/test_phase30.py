"""Phase 29: claims proposed from GSTR-3B, firm mapping template, annual return pack, classification on the web."""
import re
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from fintax_gst.samples import CLIENT
from fintax_gst.services.auth import SETUP_SESSION, AuthService
from fintax_gst.services.clients import ClientService
from fintax_gst.services.common import ServiceError

from .test_phase4 import ADMIN, _full

FY = "2025-26"


def _register(db, files):
    from fintax_gst.services.itc_register import ItcRegisterService

    c, inward, _o = _full(db, files)  # purchase register, GSTR-2B, GSTR-3B and the April reconciliation
    svc = ItcRegisterService(db)
    svc.build(c.id, FY, "a")
    return c, svc


def test_claims_proposed_from_reconciliation_and_gstr3b(db, sample_files):
    c, svc = _register(db, sample_files)
    props = svc.propose_claims(c.id, FY)
    assert props
    claimed = [p for p in props if p.claim == "claimed"]
    assert claimed and all(p.period == "2025-04" and "GSTR-2B of 2025-04" in p.why for p in claimed)
    missing = [p for p in props if p.claim == "not_claimed"]
    assert missing and all("not in GSTR-2B" in p.why for p in missing)
    # nothing is saved until the user confirms
    assert all(p.claim == "unknown" for v in svc.working(c.id, FY).txns for p in v.parts)
    check = svc.claim_check(c.id, FY, props)
    apr = next(r for r in check if r[0] == "2025-04")
    assert apr[2] == sum(p.tax for p in claimed) and apr[3] is not None and apr[4] == apr[2] - apr[3]
    n = svc.apply_claims(props, "partner")
    assert n == len(claimed) + len(missing)
    w = svc.working(c.id, FY)
    assert sum(1 for v in w.txns for p in v.parts if p.claim == "claimed" and p.claim_period == "2025-04") == len(claimed)
    # a blocked transaction is proposed as not claimed
    v = next(x for x in w.txns if x.parts[0].claim == "claimed")
    svc.set_claim([v.txn.id], "unknown", "a")
    svc.set_class([v.txn.id], "a", "food", status="blocked")
    p = next(x for x in svc.propose_claims(c.id, FY) if x.txn_id == v.txn.id)
    assert p.claim == "not_claimed" and "blocked" in p.why
    assert svc.propose_claims(ClientService(db).create(**{**CLIENT, "gstin": "27AAPFU0939F2ZU"}).id, FY) == []


def test_firm_template_and_client_priority(db, sample_files, tmp_path):
    from fintax_gst.services.bifurcation import BifurcationService
    from fintax_gst.services.mapping_master import MappingMasterService

    ms = MappingMasterService(db)
    ms.save(None, "Professional Fees", "Professional & consultancy", "services", "partner", eligibility="eligible")
    ms.save(None, "Salary", "Employee costs", "nogst", "partner")
    assert {e.m.ledger_key for e in ms.entries(None)} == {"professional fees", "salary"}
    c = ClientService(db).create(**CLIENT)
    ms.save(c.id, "Salary", "Indirect expenses – other", "services", "a")  # the client's own comes first
    bif = BifurcationService(db)
    bif.import_tb(c.id, FY, sample_files["trial_balance"], "a")
    bif.suggest_all(c.id, FY, "a")
    by = {v.ledger.name: v for v in bif.views(c.id, FY)}
    pf = by["Professional Fees"]
    assert pf.ledger.confidence == "medium" and "firm's mapping template" in pf.splits[0].remarks
    assert by["Salary"].ledger.confidence == "saved" and by["Salary"].splits[0].gst_class == "services"
    # switched-off firm entry no longer suggested; to_firm promotes a client entry
    fid = next(e.m.id for e in ms.entries(None) if e.m.ledger_key == "professional fees")
    ms.set_active([fid], False, "a", firm=True)
    assert not next(e for e in ms.entries(None) if e.m.ledger_key == "professional fees").m.active
    mine = next(e.m.id for e in ms.entries(c.id) if e.m.ledger_key == "salary")
    assert ms.to_firm(c.id, [mine], "a") == 1
    assert next(e.m for e in ms.entries(None) if e.m.ledger_key == "salary").gst_class == "services"
    out = ms.export_xlsx(None, tmp_path / "firm.xlsx")
    assert ms.import_xlsx(None, out, "a")[0] == 2
    with pytest.raises(ServiceError):
        ms.copy_from(c.id, None, "a")


def test_annual_return_pack(db, sample_files, tmp_path):
    from openpyxl import load_workbook

    from fintax_gst.services.annual_pack import AnnualPackService
    from fintax_gst.services.bifurcation import BifurcationService

    c, svc = _register(db, sample_files)
    BifurcationService(db).import_tb(c.id, FY, sample_files["trial_balance"], "a")
    empty = ClientService(db).create(**{**CLIENT, "name": "Empty Co", "gstin": "27AAPFU0939F2ZU"})
    rows, summary = AnnualPackService(db).run([c.id, empty.id], FY, tmp_path / "packs", "partner")
    r = {x.name: x for x in rows}
    full = r[CLIENT["name"]]
    assert full.txns > 10 and full.claims_proposable > 0 and full.ledgers == 7 and full.status == "Pending"
    names = {f.name for f in full.files}
    assert {f"ITC_classification_{c.gstin}_{FY}.xlsx", f"ITC_classification_{c.gstin}_{FY}.pdf",
            f"Ledger_bifurcation_{c.gstin}_{FY}.xlsx"} <= names
    assert any(n.endswith(".json") for n in names)
    assert any("claim(s) to confirm" in p for p in full.pending)
    assert r["Empty Co"].status == "Pending" and "no purchase register" in r["Empty Co"].pending[0]
    ws = load_workbook(summary).active
    assert ws["A1"].value == "Client" and ws.max_row == 3
    with pytest.raises(ServiceError):
        AnnualPackService(db).run([], FY, tmp_path, "a")


def test_web_classification_pages(db, sample_files):
    from fintax_gst.services.bifurcation import BifurcationService
    from fintax_gst.web.app import create_app

    c, svc = _register(db, sample_files)
    BifurcationService(db).import_tb(c.id, FY, sample_files["trial_balance"], "a")
    AuthService(db).create_user("admin", "Very#Strong123", "admin", by=SETUP_SESSION)
    AuthService(db).create_user("viewer1", "Very#Strong123", "viewer", by=ADMIN)
    app = create_app(db, secret=b"s" * 32)
    tc = TestClient(app)
    tc.post("/login", data={"username": "admin", "password": "Very#Strong123"})
    page = tc.get(f"/client/{c.id}/ledgers?fy={FY}").text
    assert "Ledger classification" in page and "Purchase Account" in page and "Not ready" in page
    csrf = re.search(r'name="csrf"\s+value="([0-9a-f]+)"', page).group(1)
    assert tc.post(f"/client/{c.id}/ledgers/action", data={"csrf": "bad", "fy": FY, "action": "suggest"}
                   ).status_code == 400
    r = tc.post(f"/client/{c.id}/ledgers/action", data={"csrf": csrf, "fy": FY, "action": "suggest"})
    assert r.status_code == 200 and "7 ledger(s) given a suggestion" in r.text
    lid = next(v.ledger.id for v in BifurcationService(db).views(c.id, FY) if v.ledger.name == "Salary")
    r = tc.post(f"/client/{c.id}/ledgers/action", data={"csrf": csrf, "fy": FY, "action": "approve", "ledger_id": lid})
    assert "Approved: Salary" in r.text
    lid2 = next(v.ledger.id for v in BifurcationService(db).views(c.id, FY) if v.ledger.name == "Freight Inward")
    r = tc.post(f"/client/{c.id}/ledgers/action", data={"csrf": csrf, "fy": FY, "action": "classify", "ledger_id": lid2,
                                                        "acct_class": "Freight & transportation", "gst_class": "services",
                                                        "eligibility": "eligible"})
    assert "Classified: Freight Inward" in r.text
    assert BifurcationService(db).view(lid2).state == "Approved"
    # ITC classification on the web
    itc = tc.get(f"/client/{c.id}/itc?fy={FY}&show=all").text
    assert "ITC classification" in itc and "Claim not verified" in itc
    tid = svc.working(c.id, FY).txns[0].txn.id
    r = tc.post(f"/client/{c.id}/itc/action", data={"csrf": csrf, "fy": FY, "show": "all", "action": "classify",
                                                    "txn_id": tid, "nature": "capital", "treatment": "fcm",
                                                    "status": "eligible"})
    assert "Classified:" in r.text
    r = tc.post(f"/client/{c.id}/itc/action", data={"csrf": csrf, "fy": FY, "show": "all", "action": "claim",
                                                    "txn_id": tid, "claim": "claimed", "period": "2025-04"})
    assert "Claim recorded" in r.text
    p = svc.view(tid).parts[0]
    assert (p.nature, p.status, p.claim, p.claim_period) == ("capital", "eligible", "claimed", "2025-04")
    r = tc.post(f"/client/{c.id}/itc/action", data={"csrf": csrf, "fy": FY, "action": "claim", "txn_id": tid,
                                                    "claim": "claimed", "period": ""})
    assert "Not saved" in r.text
    assert tc.post(f"/client/{c.id + 99}/itc/action", data={"csrf": csrf, "fy": FY, "action": "claim",
                                                            "txn_id": tid, "claim": "unknown"}).status_code == 404
    # a viewer sees the pages but cannot change anything
    tc.get("/logout")
    tc.cookies.clear()
    tc.post("/login", data={"username": "viewer1", "password": "Very#Strong123"})
    v_page = tc.get(f"/client/{c.id}/itc?fy={FY}&show=all").text
    assert "Record claim" not in v_page and "Save classification" not in v_page
    assert tc.post(f"/client/{c.id}/itc/action", data={"csrf": csrf, "fy": FY, "action": "claim", "txn_id": tid,
                                                       "claim": "unknown"}).status_code == 403
    _ = D
