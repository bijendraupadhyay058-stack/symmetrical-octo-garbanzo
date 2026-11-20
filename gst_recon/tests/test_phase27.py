"""Advanced ledger classification & bifurcation (trial balance from TallyPrime → GSTR-9 Table 6 / GSTR-9C Table 14)."""
import json
from decimal import Decimal as D

import pytest

from fintax_gst.samples import CLIENT
from fintax_gst.services.auth import SETUP_SESSION
from fintax_gst.services.clients import ClientService
from fintax_gst.services.common import ServiceError

FY = "2025-26"
L = D(100000)  # one lakh


def _setup(db, sample_files):
    from fintax_gst.services.bifurcation import BifurcationService

    c = ClientService(db).create(**CLIENT)
    svc = BifurcationService(db)
    svc.import_tb(c.id, FY, sample_files["trial_balance"], "accountant")
    ids = {v.ledger.name: v.ledger.id for v in svc.views(c.id, FY)}
    return c, svc, ids


def test_trial_balance_reader(sample_files, tmp_path):
    from fintax_gst.importers.trial_balance import read_trial_balance

    tb = read_trial_balance(sample_files["trial_balance"])
    names = {r.name: r for r in tb.rows}
    assert "Sundry Creditors" not in names and "Grand Total" not in names  # group heading and total skipped
    assert tb.total_debit == tb.total_credit == D(6400000) and not tb.warnings
    assert names["Purchase Account"].nature == "purchase" and names["Purchase Account"].closing == 30 * L
    assert names["Plant & Machinery"].nature == "asset" and names["Sales – Local"].closing == -25 * L
    assert names["Repairs & Maintenance"].parent == "Indirect Expenses"
    # a sub-group with its ledgers under it, and Dr / Cr closing balances in one column
    p = tmp_path / "tb.csv"
    p.write_text("Particulars,Closing Balance\nIndirect Expenses,\nOffice Expenses,15000 Dr\nPrinting,10000 Dr\n"
                 "Postage,5000 Dr\nCapital Account,\nCapital,15000 Cr\n", encoding="utf-8")
    tb = read_trial_balance(p)
    names = {r.name: r for r in tb.rows}
    assert "Office Expenses" not in names and names["Printing"].parent == "Office Expenses"
    assert names["Printing"].nature == "expense" and names["Capital"].closing == D(-15000) and tb.difference == 0
    # Tally XML trial balance report (debit balances negative)
    x = tmp_path / "tb.xml"
    x.write_text("<ENVELOPE><DSPACCNAME><DSPDISPNAME>Purchase Accounts</DSPDISPNAME></DSPACCNAME><DSPACCINFO>"
                 "<DSPCLDRAMT><DSPCLDRAMTA>-1000.00</DSPCLDRAMTA></DSPCLDRAMT><DSPCLCRAMT><DSPCLCRAMTA></DSPCLCRAMTA>"
                 "</DSPCLCRAMT></DSPACCINFO><DSPACCNAME><DSPDISPNAME>Purchase GST 18%</DSPDISPNAME></DSPACCNAME>"
                 "<DSPACCINFO><DSPCLDRAMT><DSPCLDRAMTA>-1000.00</DSPCLDRAMTA></DSPCLDRAMT><DSPCLCRAMT><DSPCLCRAMTA>"
                 "</DSPCLCRAMTA></DSPCLCRAMT></DSPACCINFO><DSPACCNAME><DSPDISPNAME>Capital Account</DSPDISPNAME>"
                 "</DSPACCNAME><DSPACCINFO><DSPCLDRAMT><DSPCLDRAMTA></DSPCLDRAMTA></DSPCLDRAMT><DSPCLCRAMT>"
                 "<DSPCLCRAMTA>1000.00</DSPCLCRAMTA></DSPCLCRAMT></DSPACCINFO><DSPACCNAME><DSPDISPNAME>Owner"
                 "</DSPDISPNAME></DSPACCNAME><DSPACCINFO><DSPCLDRAMT><DSPCLDRAMTA></DSPCLDRAMTA></DSPCLDRAMT>"
                 "<DSPCLCRAMT><DSPCLCRAMTA>1000.00</DSPCLCRAMTA></DSPCLCRAMT></DSPACCINFO></ENVELOPE>", encoding="utf-8")
    tb = read_trial_balance(x)
    assert [(r.name, r.nature, r.closing) for r in tb.rows] == [("Purchase GST 18%", "purchase", D(1000)),
                                                                 ("Owner", "other", D(-1000))]


def test_acceptance_test(db, sample_files):
    """The specification's acceptance test: ₹30L purchases, ₹3L repairs, ₹2L professional fees, ₹5L plant."""
    from fintax_gst.services.bifurcation import SplitIn

    c, svc, ids = _setup(db, sample_files)
    svc.save_splits(ids["Purchase Account"], [SplitIn(25 * L, "Trading goods", "inputs"),
                                              SplitIn(5 * L, "Raw materials", "inputs")], "accountant")
    svc.save_splits(ids["Repairs & Maintenance"], [SplitIn(2 * L, "Repairs & maintenance", "services"),
                                                   SplitIn(1 * L, "Stores & spares", "inputs")], "accountant")
    svc.save_splits(ids["Professional Fees"], [SplitIn(2 * L, "Professional & consultancy", "services")], "accountant")
    svc.save_splits(ids["Plant & Machinery"], [SplitIn(5 * L, "Plant & machinery", "capital")], "accountant")
    sm = svc.summary(c.id, FY)
    assert sm.by_gst["inputs"].value == 31 * L
    assert sm.by_gst["services"].value == 4 * L
    assert sm.by_gst["capital"].value == 5 * L
    assert sm.by_gst["inputs"].value + sm.by_gst["services"].value + sm.by_gst["capital"].value == 40 * L
    assert all(t.tax == 0 for t in sm.by_gst.values())  # classified values are not ITC entitlements
    assert not sm.table6  # no eligibility / GST given yet – nothing counts as ITC availed
    by = {v.ledger.name: v for v in sm.views}
    assert by["Purchase Account"].state == "Approved" and by["Purchase Account"].unallocated == 0
    assert by["Salary"].state == "Pending" and not sm.ready[0]
    # the trial balance itself is untouched by classification
    assert by["Purchase Account"].ledger.closing == 30 * L and sm.tb_debit == sm.tb_credit == D(6400000)


def test_splits_reconcile_and_gst_rules(db, sample_files):
    from fintax_gst.services.bifurcation import SplitIn

    c, svc, ids = _setup(db, sample_files)
    lid = ids["Repairs & Maintenance"]
    with pytest.raises(ServiceError, match="more than the ledger"):
        svc.save_splits(lid, [SplitIn(2 * L, "Repairs & maintenance", "services"),
                              SplitIn(2 * L, "Stores & spares", "inputs")], "accountant")
    v = svc.save_splits(lid, [SplitIn(2 * L, "Repairs & maintenance", "services", eligibility="eligible")], "a")
    assert v.state == "Partly classified" and v.unallocated == L and any("not classified" in w for w in v.warnings)
    with pytest.raises(ServiceError, match="where the GST"):
        svc.save_splits(lid, [SplitIn(3 * L, "Repairs & maintenance", "services", cgst=D(100))], "a")
    with pytest.raises(ServiceError, match="apportioned"):
        svc.save_splits(lid, [SplitIn(3 * L, "Repairs & maintenance", "services", cgst=D(100),
                                      gst_basis="apportioned")], "a")
    with pytest.raises(ServiceError, match="cannot carry GST"):
        svc.save_splits(ids["Salary"], [SplitIn(6 * L, "Employee costs", "nogst", cgst=D(1),
                                                gst_basis="entered")], "a")
    v = svc.save_splits(lid, [
        SplitIn(2 * L, "Repairs & maintenance", "services", eligibility="eligible", taxable=2 * L, cgst=D(18000),
                sgst=D(18000), gst_basis="entered", basis_note="AMC invoices"),
        SplitIn(L, "Stores & spares", "inputs", eligibility="eligible", taxable=L, cgst=D(9000), sgst=D(9000),
                gst_basis="apportioned", basis_note="pro rata of ledger GST, approved")], "a")
    assert v.state == "Approved" and v.gst["cgst"] == D(27000)
    assert any("apportioned" in w for w in v.warnings)
    sm = svc.summary(c.id, FY)
    assert sm.table6[("6B", "services")].cgst == D(18000) and sm.table6[("6B", "inputs")].sgst == D(9000)
    r14 = {r.code: r for r in sm.table14}
    assert r14["14M"].value == 2 * L and r14["14M"].gst == D(36000) and r14["14M"].availed == D(36000)
    # reverse, then the classification is gone but in the audit log
    assert svc.clear([lid], "a") == 1 and svc.view(lid).state == "Pending"
    trail = svc.audit_trail(c.id)
    assert {"LEDGER_CLASSIFY", "LEDGER_UNCLASSIFY"} <= {a.action for a in trail}


def test_suggestions_need_approval_and_are_remembered(db, sample_files, tmp_path):
    from fintax_gst.services.bifurcation import BifurcationService

    c, svc, ids = _setup(db, sample_files)
    n = svc.suggest_all(c.id, FY, "accountant")
    assert n == 7  # purchases, expenses and the fixed asset; duties / bank / capital / sales are not classified
    by = {v.ledger.name: v for v in svc.views(c.id, FY)}
    assert by["Plant & Machinery"].state == "Suggested (high)" and by["Plant & Machinery"].label("gst_class") == \
        "Capital goods"
    assert by["Electricity Charges"].label("gst_class") == "No GST (outside GST)"
    assert not by["HDFC Bank"].in_scope and by["HDFC Bank"].state == "Not for classification"
    sm = svc.summary(c.id, FY)
    assert sm.count("Suggested") == 7 and not sm.ready[0]
    assert svc.approve([ids["Salary"], ids["Professional Fees"]], "partner") == 2
    assert svc.view(ids["Salary"]).state == "Approved"
    # the approved mapping is suggested for the next year with confidence "saved"
    ClientService(db)  # same client, next year's trial balance
    svc2 = BifurcationService(db)
    nxt = tmp_path / "tb_next.csv"
    nxt.write_text("Particulars,Group,Debit,Credit\nProfessional Fees,Indirect Expenses,250000,\n"
                   "Capital,Capital Account,,250000\n", encoding="utf-8")
    svc2.import_tb(c.id, "2026-27", nxt, "a")
    svc2.suggest_all(c.id, "2026-27", "a")
    v = next(x for x in svc2.views(c.id, "2026-27") if x.ledger.name == "Professional Fees")
    assert v.ledger.confidence == "saved" and v.state == "Suggested (saved)" and not v.splits[0].approved
    assert svc2.years(c.id) == ["2025-26", "2026-27"]


def test_invoice_wise_gst_and_no_double_counting(db, sample_files):
    from fintax_gst.core.models import Source
    from fintax_gst.services.bifurcation import SplitIn
    from fintax_gst.services.imports import ImportService

    c, svc, ids = _setup(db, sample_files)
    ImportService(db).import_file(c.id, sample_files["books_april"], Source.BOOKS)
    inv = svc.invoices(c.id, FY)
    assert inv and all("taxable" in d for d in inv)
    first = [inv[0]["id"], inv[1]["id"]]
    p = svc.part_from_invoices(c.id, first, "Trading goods", "inputs", eligibility="eligible")
    assert p.gst_basis == "invoices" and p.taxable == inv[0]["taxable"] + inv[1]["taxable"]
    rest = 30 * L - p.amount
    svc.save_splits(ids["Purchase Account"], [p, SplitIn(rest, "Trading goods", "inputs", eligibility="eligible")],
                    "a")
    assert {d["id"] for d in svc.invoices(c.id, FY)}.isdisjoint(first)  # used invoices are not offered again
    with pytest.raises(ServiceError, match="already used"):
        svc.save_splits(ids["Freight Inward"], [svc.part_from_invoices(c.id, first[:1], "Freight & transportation",
                                                                       "services")], "a")
    sp = svc.view(ids["Purchase Account"]).splits[0]
    assert json.loads(sp.invoice_ids) == sorted(first)


def test_reimport_keeps_classification_and_fixed_asset_base(db, sample_files, tmp_path):
    from fintax_gst.services.bifurcation import SplitIn

    c, svc, ids = _setup(db, sample_files)
    svc.save_splits(ids["Professional Fees"], [SplitIn(2 * L, "Professional & consultancy", "services")], "a")
    with pytest.raises(ServiceError, match="already imported"):
        svc.import_tb(c.id, FY, sample_files["trial_balance"], "a")
    p = tmp_path / "tb2.csv"
    p.write_text("Particulars,Group,Opening Balance,Transactions Debit,Transactions Credit,Closing Balance\n"
                 "Professional Fees,Indirect Expenses,,250000,,250000 Dr\n"
                 "Plant & Machinery,Fixed Assets,400000 Dr,150000,50000,500000 Dr\n"
                 "Capital,Capital Account,,,,750000 Cr\n", encoding="utf-8")
    _sf, _tb, stats = svc.import_tb(c.id, FY, p, "a")
    assert stats["updated"] == 2 and stats["changed"] == 1 and stats["new"] == 1 and stats["removed"] >= 10
    by = {v.ledger.name: v for v in svc.views(c.id, FY)}
    pf = by["Professional Fees"]
    assert pf.splits and pf.unallocated == D(50000) and pf.state == "Partly classified"
    assert pf.ledger.status == "partial"
    plant = by["Plant & Machinery"]
    assert plant.ledger.base == D(150000) and "additions" in plant.ledger.base_note and plant.ledger.closing == 5 * L
    svc.set_base(plant.ledger.id, D(120000), "Additions per fixed asset register", "a")
    assert svc.view(plant.ledger.id).ledger.base == D(120000)
    with pytest.raises(ServiceError):
        svc.set_base(plant.ledger.id, D(1), "", "a")


def test_workbook_pdf_table14_and_gstr9_feed(db, sample_files, tmp_path):
    from openpyxl import load_workbook

    from fintax_gst.services.bifurcation import SplitIn
    from fintax_gst.services.gstr9c import Gstr9cService

    c, svc, ids = _setup(db, sample_files)
    gst = dict(gst_basis="entered", basis_note="invoices", eligibility="eligible")
    svc.save_splits(ids["Purchase Account"], [SplitIn(30 * L, "Trading goods", "inputs", taxable=30 * L,
                                                      cgst=D(270000), sgst=D(270000), **gst)], "a")
    svc.save_splits(ids["Repairs & Maintenance"], [SplitIn(3 * L, "Repairs & maintenance", "services", head_9c="14M",
                                                           taxable=3 * L, cgst=D(27000), sgst=D(27000), **gst)], "a")
    svc.save_splits(ids["Professional Fees"], [SplitIn(2 * L, "Professional & consultancy", "services",
                                                       taxable=2 * L, cgst=D(18000), sgst=D(18000), **gst)], "a")
    svc.save_splits(ids["Plant & Machinery"], [SplitIn(5 * L, "Plant & machinery", "capital", head_9c="14O",
                                                       taxable=5 * L, cgst=D(45000), sgst=D(45000), **gst)], "a")
    svc.save_splits(ids["Freight Inward"], [SplitIn(L, "Freight & transportation", "services", head_9c="14B",
                                                    eligibility="not_availed")], "a")
    with pytest.raises(ServiceError, match="Not sent"):
        svc.push_table14(c.id, FY, SETUP_SESSION)  # salary / electricity still pending
    svc.classify_whole([ids["Salary"]], "Employee costs", "nogst", "a", head_9c="14H", eligibility="na")
    svc.classify_whole([ids["Electricity Charges"]], "Electricity & utilities", "nogst", "a", head_9c="14C")
    sm = svc.summary(c.id, FY)
    ok, reasons = sm.ready
    assert ok, reasons  # no GSTR-3B imported, so no 6B comparison is required
    assert sm.table6_total("6B").tax == D(720000)
    n = svc.push_table14(c.id, FY, SETUP_SESSION)
    inputs = Gstr9cService(db).inputs(c.id, FY)
    assert n > 0 and inputs["14M-V"][0] == 3 * L and inputs["14M-E"][0] == D(54000) and inputs["14A-T"][0] == \
        D(540000)
    out = svc.export_xlsx(c.id, FY, tmp_path / "b.xlsx")
    wb = load_workbook(out)
    expected = {"Dashboard", "Original TallyPrime data", "Trial Balance Summary", "P&L Classification",
                "Purchase Bifurcation", "Expense Bifurcation", "Capital Goods Register", "Inputs Summary",
                "Input Services Summary", "ITC Eligibility & Reversals", "GSTR-2B Reconciliation",
                "GSTR-3B Reconciliation", "GSTR-9 Table-wise Working", "GSTR-9C Expense-wise ITC",
                "Differences & Exceptions", "Classification Audit Trail", "Classification", "Parts"}
    assert expected <= set(wb.sheetnames)
    cls = wb["Classification"]
    assert cls.cell(2, 15).value.startswith("=SUMIF(") and cls.cell(2, 16).value.startswith("=E2-O2")
    assert wb["Dashboard"]["A2"].value.startswith("Ready")
    assert svc.export_pdf(c.id, FY, tmp_path / "b.pdf").stat().st_size > 2000
    # GSTR-9 draft: 6B split only when GSTR-3B is imported and agrees
    assert svc.table6_split(c.id, FY) is None


def test_gstr9_draft_uses_the_split_when_it_agrees(db, sample_files, tmp_path):
    from fintax_gst.services.bifurcation import SplitIn
    from fintax_gst.services.gstr3b import Gstr3bService
    from fintax_gst.services.gstr9 import Gstr9Service

    c, svc, ids = _setup(db, sample_files)
    p = tmp_path / "3b.csv"
    p.write_text("Period,Table,IGST,CGST,SGST,Cess\n2025-04,4A5,0,315000,315000,0\n", encoding="utf-8")
    Gstr3bService(db).import_file(c.id, p)
    gst = dict(gst_basis="entered", basis_note="invoices", eligibility="eligible")
    svc.save_splits(ids["Purchase Account"], [SplitIn(30 * L, "Trading goods", "inputs", cgst=D(270000),
                                                      sgst=D(270000), **gst)], "a")
    svc.save_splits(ids["Plant & Machinery"], [SplitIn(5 * L, "Plant & machinery", "capital", cgst=D(45000),
                                                       sgst=D(45000), **gst)], "a")
    for name, acct in (("Repairs & Maintenance", "Repairs & maintenance"), ("Professional Fees",
                                                                           "Professional & consultancy"),
                       ("Freight Inward", "Freight & transportation")):
        svc.classify_whole([ids[name]], acct, "services", "a", eligibility="not_availed")
    svc.classify_whole([ids["Salary"], ids["Electricity Charges"]], "Employee costs", "nogst", "a")
    assert svc.summary(c.id, FY).difference_6b == {"igst": 0, "cgst": 0, "sgst": 0, "cess": 0}
    split = svc.table6_split(c.id, FY)
    assert split["ip"]["cgst"] == D(270000) and split["cg"]["sgst"] == D(45000) and split["is"]["cgst"] == 0
    js, mp = Gstr9Service(db).draft_json(c.id, FY, tmp_path / "g9")
    t6 = json.loads(js.read_text(encoding="utf-8"))["table6"]
    assert [x["itc_typ"] for x in t6["supp_non_rchrg"]] == ["ip", "cg", "is"]
    assert "split from the approved ledger bifurcation" in mp.read_text(encoding="utf-8")
