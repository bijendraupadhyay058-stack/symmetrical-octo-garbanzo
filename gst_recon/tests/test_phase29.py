"""ITC claim kept apart from classification and eligibility; GSTR-9C Table 14 always prepared; Ledger Mapping Master."""
from decimal import Decimal as D

import pytest

from fintax_gst.core.models import Source
from fintax_gst.samples import CLIENT
from fintax_gst.services.clients import ClientService
from fintax_gst.services.common import ServiceError
from fintax_gst.services.imports import ImportService

from .test_phase28 import _setup

FY = "2025-26"


def test_capital_goods_classified_is_not_itc_claimed(db, sample_files):
    c, svc = _setup(db, sample_files)
    v = next(x for x in svc.working(c.id, FY).views if x.txn.invoice_id and x.txn.cgst)
    svc.set_class([v.txn.id], "a", "machine", nature="capital", status="eligible")
    w = svc.working(c.id, FY)
    p = svc.view(v.txn.id).parts[0]
    assert (p.nature, p.status, p.claim) == ("capital", "eligible", "unknown")
    assert w.table6["6B"]["capital"].tax == 0  # classification + eligibility alone put nothing in Table 6
    r14 = {r[0]: r for r in w.table14}["14O"]
    assert r14[4] == v.tax and r14[5] == 0  # eligible ITC shown, claimed ITC nil
    with pytest.raises(ServiceError, match="period"):
        svc.set_claim([v.txn.id], "claimed", "a")
    svc.set_claim([v.txn.id], "claimed", "a", "2025-04", "per GSTR-3B")
    p = svc.view(v.txn.id).parts[0]
    assert (p.nature, p.status, p.claim, p.claim_period) == ("capital", "eligible", "claimed", "2025-04")
    assert svc.working(c.id, FY).table6["6B"]["capital"].tax == v.tax
    # changing the classification later does not touch the claim
    svc.set_class([v.txn.id], "a", "really goods", nature="trading")
    p = svc.view(v.txn.id).parts[0]
    assert p.claim == "claimed" and svc.working(c.id, FY).table6["6B"]["inputs"].tax >= v.tax
    # claimed in the next year's GSTR-3B: not Table 6 of this year, but 12C / 8C
    svc.set_claim([v.txn.id], "claimed", "a", "2026-05")
    w = svc.working(c.id, FY)
    assert w.table6["6B"]["inputs"].tax == 0 and dict((r[0], r[2]) for r in w.table12)["12C"] == v.tax


def test_ineligible_but_claimed_fails_a_control(db, sample_files):
    c, svc = _setup(db, sample_files)
    v = next(x for x in svc.working(c.id, FY).views if x.txn.invoice_id and x.txn.cgst)
    svc.set_class([v.txn.id], "a", "staff food", nature="services", status="blocked")
    svc.set_claim([v.txn.id], "claimed", "a", "2025-04")
    w = svc.working(c.id, FY)
    c8 = next(x for x in w.controls if x.code == "C8")
    assert c8.status == "fail" and c8.critical and w.inelig_claimed == v.tax
    assert any(r[0].startswith("Ineligible ITC that was claimed") for r in w.table13)
    assert not w.can_finalise[0]
    svc.set_claim([v.txn.id], "reversed", "a", "2025-04", "reversed in 4(B)(1)")
    w = svc.working(c.id, FY)
    assert w.table7["reversed"].tax == v.tax


def test_claim_comes_from_the_claim_register(db, sample_files):
    from fintax_gst.services.itc import ItcService
    from fintax_gst.services.itc_register import ItcRegisterService

    c = ClientService(db).create(**CLIENT)
    ImportService(db).import_file(c.id, sample_files["books_april"], Source.BOOKS)
    from fintax_gst.db.models import Invoice
    with db.session() as s:
        inv = s.query(Invoice).filter(Invoice.client_id == c.id, Invoice.doc_type == "INV").first()
        iid = inv.id
    ItcService(db).claim(c.id, [iid], "2025-04", "a")
    svc = ItcRegisterService(db)
    svc.build(c.id, FY, "a")
    p = next(v for v in svc.working(c.id, FY).views if v.txn.invoice_id == iid).parts[0]
    assert (p.claim, p.claim_period) == ("claimed", "2025-04")


def test_table14_status_is_recorded_per_year(db, sample_files):
    from fintax_gst.services.annual_rules import set_note, table14_status

    assert "05/2026" in table14_status(db, "2025-26") and "regardless" in table14_status(db, "2025-26")
    assert "05/2026" in table14_status(db, "2027-28")  # "onwards"
    assert "check the year's notification" in table14_status(db, "2023-24")
    set_note(db, "2023-24", "Optional for FY 2023-24 – as per the user's reading", "partner")
    assert table14_status(db, "2023-24").startswith("Optional for FY 2023-24")
    c, svc = _setup(db, sample_files, tax_ledgers=False, gstr3b=False)
    assert "05/2026" in svc.working(c.id, FY).table14_status


def test_ledger_mapping_master(db, sample_files, tmp_path):
    from fintax_gst.services.bifurcation import BifurcationService
    from fintax_gst.services.mapping_master import MappingMasterService

    c = ClientService(db).create(**CLIENT)
    other = ClientService(db).create(**{**CLIENT, "name": "Group Co", "gstin": "27AAPFU0939F2ZU"})
    ms = MappingMasterService(db)
    bif = BifurcationService(db)
    bif.import_tb(c.id, FY, sample_files["trial_balance"], "a")
    ids = {v.ledger.name: v.ledger.id for v in bif.views(c.id, FY)}
    # an approval in Ledger classification fills the master
    bif.classify_whole([ids["Professional Fees"]], "Professional & consultancy", "services", "a", head_9c="14N",
                       eligibility="eligible")
    es = {e.m.ledger_key: e for e in ms.entries(c.id)}
    assert es["professional fees"].m.source == "approved" and es["professional fees"].tb_years == [FY]
    assert es["professional fees"].nature == "Input services"
    # added by hand, edited, switched off: not suggested any more
    ms.save(c.id, "Repairs & Maintenance", "Repairs & maintenance", "services", "a", head_9c="14M",
            eligibility="eligible")
    ms.save(c.id, "Plant & Machinery", "Plant & machinery", "capital", "a", head_9c="14O", eligibility="eligible")
    m = next(e.m for e in ms.entries(c.id) if e.m.ledger_key == "plant & machinery")
    ms.set_active([m.id], False, "a")
    with pytest.raises(ServiceError):
        ms.save(c.id, "X", "Trading goods", "bad", "a")
    res = ms.apply(c.id, FY, "a")
    by = {v.ledger.name: v for v in bif.views(c.id, FY)}
    assert by["Repairs & Maintenance"].ledger.confidence == "saved"
    assert by["Plant & Machinery"].ledger.confidence != "saved"  # switched off
    assert by["Professional Fees"].state == "Approved" and res["ledgers"] >= 1
    # an approval does not bring a switched-off mapping back
    bif.classify_whole([ids["Plant & Machinery"]], "Plant & machinery", "capital", "a")
    assert not next(e.m for e in ms.entries(c.id) if e.m.ledger_key == "plant & machinery").active
    # Excel round trip and copy to a group company
    out = ms.export_xlsx(c.id, tmp_path / "master.xlsx")
    n, errors = ms.import_xlsx(other.id, out, "a")
    assert n == 3 and not errors
    assert len(ms.entries(other.id)) == 3
    ms.save(c.id, "Freight Inward", "Freight & transportation", "services", "a", "rcm_reg")
    copied, kept = ms.copy_from(other.id, c.id, "a")
    assert copied == 1 and kept == 2  # only Freight is new; the group company's own entries are kept
    with pytest.raises(ServiceError):
        ms.copy_from(c.id, c.id, "a")


def test_itc_ledger_rule_goes_to_the_master_and_is_reused(db, sample_files):
    from fintax_gst.db.models import ItcTxn
    from fintax_gst.services.mapping_master import MappingMasterService

    c, svc = _setup(db, sample_files)
    regular = [v for v in svc.working(c.id, FY).views if v.txn.invoice_id]
    with db.session() as s:
        for t in s.query(ItcTxn).filter(ItcTxn.id.in_([x.txn.id for x in regular[:2]])):
            t.ledger = "Audit Fees"
    svc.add_rule(c.id, "ledger", "Audit Fees", "a", nature="services", status="eligible")
    m = next(e.m for e in MappingMasterService(db).entries(c.id) if e.m.ledger_key == "audit fees")
    assert m.gst_class == "services" and m.eligibility == "eligible"
    # next year: the rule is switched off, the master still classifies the ledger
    for r in svc.rules(c.id):
        svc.delete_rule(r.id, "a")
    svc.classify_auto(c.id, FY)
    p = svc.view(regular[0].txn.id).parts[0]
    assert p.nature == "services" and p.confidence == "high" and "approved as" in p.reason


def test_migration_moves_claim_states_out_of_eligibility(db):
    from fintax_gst.db.database import _migration_29
    from fintax_gst.db.models import ItcPart, ItcTxn

    c = ClientService(db).create(**CLIENT)
    with db.session() as s:
        t = ItcTxn(client_id=c.id, financial_year=FY, igst=D(0), cgst=D(9), sgst=D(9), cess=D(0))
        s.add(t)
        s.flush()
        for st in ("reclaimed", "not_claimed", "reversal", "eligible"):
            s.add(ItcPart(client_id=c.id, txn_id=t.id, igst=D(0), cgst=D(9), sgst=D(9), cess=D(0), status=st))
    with db.engine.begin() as conn:
        _migration_29(conn)
    with db.session() as s:
        got = sorted((p.status, p.claim) for p in s.query(ItcPart))
    assert got == [("eligible", "not_claimed"), ("eligible", "reclaimed"), ("eligible", "unknown"),
                   ("reversal_req", "unknown")]
