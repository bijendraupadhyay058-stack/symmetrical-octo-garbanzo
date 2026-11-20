"""ITC classification & manual mapping (transaction level): tax ledgers, consolidation, rules, splits, workings."""
from datetime import date
from decimal import Decimal as D

import pytest

from fintax_gst.core.models import Source
from fintax_gst.samples import CLIENT, TAX_LEDGER_EXTRA, books_docs
from fintax_gst.services.clients import ClientService
from fintax_gst.services.common import ServiceError
from fintax_gst.services.imports import ImportService

FY = "2025-26"


def _setup(db, files, tax_ledgers: bool = True, gstr3b: bool = True):
    from fintax_gst.services.gstr3b import Gstr3bService
    from fintax_gst.services.itc_register import ItcRegisterService

    c = ClientService(db).create(**CLIENT)
    ImportService(db).import_file(c.id, files["books_april"], Source.BOOKS)
    if gstr3b:
        Gstr3bService(db).import_file(c.id, files["gstr3b_april_json"])
    svc = ItcRegisterService(db)
    if tax_ledgers:
        svc.import_tax_ledgers(c.id, FY, files["tax_ledgers"], "accountant")
    svc.build(c.id, FY, "accountant")
    return c, svc


def test_tax_ledger_reader(sample_files, tmp_path):
    from fintax_gst.importers.tax_ledger import head_of, read_tax_ledgers

    assert head_of("Input CGST 9%") == "cgst" and head_of("Input UTGST") == "sgst" and head_of("IGST Input") == "igst"
    assert head_of("Input Cess") == "cess" and head_of("Purchase") is None
    tl = read_tax_ledgers(sample_files["tax_ledgers"])
    assert set(tl.ledgers.values()) == {"cgst", "sgst", "igst"}
    assert {p.kind for p in tl.postings} == {"txn", "opening", "closing"}
    cg = sum(D(d.cgst) * (-1 if d.doc == "CRN" else 1) for d in books_docs())
    extra = sum(x[3] for x in TAX_LEDGER_EXTRA)
    assert tl.total("cgst") == cg + extra
    p = tmp_path / "Input IGST.csv"
    p.write_text("Date,Particulars,Vch Type,Vch No.,Amount\n01-04-2025,Supplier A,Purchase,7,1800 Dr\n"
                 ",Closing Balance,,,1800 Dr\n", encoding="utf-8")
    tl = read_tax_ledgers(p)
    assert [(x.head, x.kind, x.amount) for x in tl.postings] == [("igst", "txn", D(1800)), ("igst", "closing", D(1800))]


def test_consolidation_never_counts_cgst_and_sgst_twice(db, sample_files):
    c, svc = _setup(db, sample_files)
    w = svc.working(c.id, FY)
    docs = books_docs()
    regular = [v for v in w.views if v.txn.invoice_id]
    assert len(regular) == len(docs)  # one transaction per purchase-register document
    assert all(v.txn.match == "both" for v in regular)  # each matched to its CGST / SGST / IGST postings
    gta = next(v for v in w.views if v.txn.match == "taxledger")
    assert gta.txn.cgst == D(250) and gta.txn.sgst == D(250) and gta.parts[0].treatment == "rcm_unreg"
    adj = [v for v in w.views if v.is_adjustment]
    assert len(adj) == 1 and adj[0].tax == D(-10000) and not adj[0].parts
    ctl = {x.code: x for x in w.controls}
    assert ctl["C1"].status == "pass" and ctl["C4"].status == "pass" and ctl["C2"].status == "pass"
    # every posting is in exactly one transaction
    import json
    ids = [i for v in w.views for i in json.loads(v.txn.posting_ids)]
    assert len(ids) == len(set(ids))
    # rebuilding keeps the same transactions
    n = len(w.views)
    svc.build(c.id, FY, "a")
    assert len(svc.working(c.id, FY).views) == n


def test_no_silent_trading_and_priority_of_evidence(db, sample_files):
    from fintax_gst.services.bifurcation import BifurcationService, SplitIn

    c, svc = _setup(db, sample_files)
    w = svc.working(c.id, FY)
    # the sample register has no ledger names: nothing is assumed to be a trading purchase
    regular = [v for v in w.views if v.txn.invoice_id]
    assert all(v.parts[0].nature != "trading" for v in regular)
    assert w.unclassified >= len(regular) - 2
    # a ledger rule
    v = regular[0]
    with db.session() as s:
        from fintax_gst.db.models import ItcTxn
        for t in s.query(ItcTxn).filter(ItcTxn.id.in_([x.txn.id for x in regular[:3]])):
            t.ledger = "Purchase @18%"
    svc.add_rule(c.id, "ledger", "Purchase @18%", "a", nature="trading", status="eligible")
    w = svc.working(c.id, FY)
    got = {x.txn.id: x for x in w.views}
    assert all(got[x.txn.id].parts[0].nature == "trading" and got[x.txn.id].parts[0].basis == "rule"
               for x in regular[:3])
    # a manual classification wins over any rule, now and later
    svc.set_class([v.txn.id], "partner", "raw material per GRN", nature="raw")
    svc.add_rule(c.id, "gstin", v.txn.gstin, "a", nature="services")
    p = svc.view(v.txn.id).parts[0]
    assert p.nature == "raw" and p.basis == "manual"
    # supplier rule applies to the supplier's other transactions, but not to the hand-classified one
    others = [x for x in svc.working(c.id, FY).views if x.txn.gstin == v.txn.gstin and x.txn.id != v.txn.id]
    assert all(x.parts[0].nature in ("services", "trading") for x in others)
    # a rule for another year does not apply
    svc.add_rule(c.id, "keyword", "OSL", "a", nature="capital", fy="2024-25")
    assert not any(x.parts[0].nature == "capital" for x in svc.working(c.id, FY).views if x.parts)
    # a classification approved in Ledger classification is used for the ledger
    from fintax_gst.db.models import LedgerMapping
    with db.session() as s:
        s.add(LedgerMapping(client_id=c.id, ledger_key="freight inward", acct_class="Freight & transportation",
                            gst_class="services", gst_source="regular", eligibility="eligible"))
    with db.session() as s:
        t = s.query(ItcTxn).filter(ItcTxn.id == regular[5].txn.id).one()
        t.ledger = "Freight Inward"
    svc.classify_auto(c.id, FY)
    p = svc.view(regular[5].txn.id).parts[0]
    assert (p.nature, p.status, p.confidence) == ("services", "eligible", "high")
    _ = (BifurcationService, SplitIn)
    with pytest.raises(ServiceError):
        svc.add_rule(c.id, "ledger", "X", "a")  # a rule must set something
    assert len([r for r in svc.rules(c.id) if r.active]) == 3


def test_split_exact_undo_and_history(db, sample_files):
    from fintax_gst.services.itc_register import PartIn

    c, svc = _setup(db, sample_files)
    v = next(x for x in svc.working(c.id, FY).views if x.txn.invoice_id and x.txn.cgst and x.txn.taxable > 10000)
    t = v.txn
    with pytest.raises(ServiceError, match="must be equal"):
        svc.split(t.id, [PartIn(cgst=t.cgst, sgst=t.sgst, taxable=t.taxable - 1, nature="trading")], "a")
    parts = svc.proportional(t, [t.taxable * D("0.6"), t.taxable - t.taxable * D("0.6")])
    parts[0].nature, parts[1].nature = "trading", "capital"
    parts[0].status = parts[1].status = "eligible"
    out = svc.split(t.id, parts, "a", "invoice covers goods and a machine")
    assert len(out.parts) == 2 and sum(p.cgst for p in out.parts) == t.cgst
    assert out.label("nature") == "Split (2)"
    svc.set_class([t.id], "a", "all eligible", status="eligible")
    assert svc.undo(t.id, "a") and len(svc.view(t.id).parts) == 2  # back to the split
    assert svc.undo(t.id, "a") and len(svc.view(t.id).parts) == 1  # back to before the split
    actions = [h.action for h in svc.history(t.id)]
    assert actions.count("ITC_UNDO") == 2 and "ITC_UNDONE" in actions


def test_table6_rcm_imports_and_finalise(db, sample_files, tmp_path):
    from openpyxl import load_workbook

    c, svc = _setup(db, sample_files)
    w = svc.working(c.id, FY)
    regular = [v for v in w.views if v.txn.invoice_id]
    svc.set_class([v.txn.id for v in regular], "a", "bulk", nature="trading", status="eligible")
    gta = next(v for v in w.views if v.txn.match == "taxledger")
    svc.set_class([gta.txn.id], "a", "GTA", nature="services", status="eligible")
    svc.set_class([regular[0].txn.id], "a", "import of service", nature="services", treatment="import_s")
    # classified and eligible, but nothing claimed yet: Table 6 stays empty
    w = svc.working(c.id, FY)
    assert all(b.tax == 0 for r in w.table6.values() for b in r.values())
    assert any(x.code == "C8b" for x in w.controls)
    ids = [v.txn.id for v in regular if v.txn.id != regular[1].txn.id] + [gta.txn.id]
    svc.set_claim(ids, "claimed", "a", "2025-04", "GSTR-3B April")
    svc.set_claim([regular[1].txn.id], "not_claimed", "a")
    svc.set_claim([regular[2].txn.id], "reclaimed", "a", "2025-06")
    w = svc.working(c.id, FY)
    assert w.table6["6C"]["services"].tax == D(500)  # domestic RCM never in 6B
    assert w.table6["6F"]["services"].tax == regular[0].tax
    assert w.table6["6H"]["inputs"].tax == regular[2].tax
    total_6b = sum(x.tax for x in w.table6["6B"].values())
    assert total_6b == sum(v.tax for v in regular[3:])  # not claimed / reclaimed / import are not in 6B
    assert w.table6_3b["6B"] is not None and w.table12[0][0] == "12A"
    assert dict((r[0], r[2]) for r in w.table12)["12C"] == regular[1].tax  # eligible, not claimed
    assert any(r[0] == "Credit notes" for r in w.table13)
    ctl = {x.code: x for x in w.controls}
    assert ctl["C3"].status == "pass" and ctl["C6"].status == "warn"  # RCM ITC without 3.1(d) tax
    assert "C8b" not in ctl
    rec = svc.finalise(c.id, FY, "partner", "reviewed")
    assert rec["by"] == "partner" and svc.working(c.id, FY).final
    svc.reopen(c.id, FY, "partner")
    assert svc.working(c.id, FY).final is None
    out = svc.export_xlsx(c.id, FY, tmp_path / "itc.xlsx")
    wb = load_workbook(out)
    assert len(wb.sheetnames) == 19 and wb.sheetnames[0] == "Final ITC Summary"
    assert wb["GSTR-9 Table 6 Working"]["D2"].value.startswith("=SUMIFS(")
    assert wb["Consolidated ITC Register"].cell(1, 30).value == "ITC claim"
    assert svc.export_pdf(c.id, FY, tmp_path / "itc.pdf").stat().st_size > 2000


def test_ledger_control_fails_and_finalise_needs_a_reason(db, sample_files, tmp_path):
    from fintax_gst.services.itc_register import ItcRegisterService

    c = ClientService(db).create(**CLIENT)
    p = tmp_path / "Input CGST.csv"
    p.write_text("Date,Particulars,Vch Type,Vch No.,Debit,Credit\n,Opening Balance,,,0,\n"
                 "02-04-2025,Supplier A,Purchase,1,900,\n,Closing Balance,,,1000,\n", encoding="utf-8")
    svc = ItcRegisterService(db)
    svc.import_tax_ledgers(c.id, FY, p, "a")
    svc.build(c.id, FY, "a")
    w = svc.working(c.id, FY)
    c1 = next(x for x in w.controls if x.code == "C1")
    assert c1.status == "fail" and "≠ closing" in c1.detail
    with pytest.raises(ServiceError, match="Not finalised"):
        svc.finalise(c.id, FY, "a")
    rec = svc.finalise(c.id, FY, "a", override="closing balance includes a journal outside the year – checked")
    assert rec["override"] and rec["failed"]
    with pytest.raises(ServiceError, match="already imported"):
        svc.import_tax_ledgers(c.id, FY, p, "a")
    # removing the tax-ledger import removes its postings; the register follows on rebuild
    from fintax_gst.services.imports import ImportService as IS
    sf = next(f for f in IS(db).list_files(c.id) if f.source_type == "TAXLEDGER")
    IS(db).remove_import(c.id, sf.id, "a")
    svc.build(c.id, FY, "a")
    assert svc.working(c.id, FY).views == []
    _ = date
