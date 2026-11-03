from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from fintax_gst.cli import main
from fintax_gst.core.models import DocType, InvoiceRecord, Source
from fintax_gst.db.database import open_database
from fintax_gst.db.models import Gstr1Hsn
from fintax_gst.gstr9.expenses import read_expense_ledger, row_for
from fintax_gst.gstr9.working import build_gstr9
from fintax_gst.importers.gstr3b import Gstr3bValues as V
from fintax_gst.importers.pipeline import preview_file
from fintax_gst.itc.annual import fy_months
from fintax_gst.itc.table4 import ClaimAction
from fintax_gst.samples import CLIENT, EXPENSE_LEDGER
from fintax_gst.samples_outward import B2CS_UNDER_REPORTED, LATE_INVOICE, NEXT_AMEND_0005
from fintax_gst.services.auth import SETUP_SESSION, PermissionDenied, Session
from fintax_gst.services.clients import ClientService
from fintax_gst.services.common import ServiceError
from fintax_gst.services.gstr9 import Gstr9Service
from fintax_gst.services.gstr9c import Gstr9cService
from fintax_gst.services.imports import ImportService
from fintax_gst.services.security import SecurityService
from fintax_gst.services.sync import SyncService

D = Decimal
ADMIN = Session("admin", "admin", "Admin")


def _doc(no, taxable, tax, dt, period, amendment=False, original="", original_dt=None, doc=DocType.INVOICE):
    return InvoiceRecord(uid=no + period, source=Source.GSTR1, supplier_gstin="27AABCR1122A1Z7", doc_type=doc,
                         invoice_no=no, invoice_date=dt, taxable=D(taxable), igst=D(tax), period=period,
                         is_amendment=amendment, original_invoice_no=original, original_invoice_date=original_dt)


# ------------------------------------------------------------------ HSN
def test_hsn_import_both_formats(db, sample_files):
    april = preview_file(sample_files["gstr1_april_json"], Source.GSTR1)
    assert {h["segment"] for h in april.hsn_summary} == {"B2B", "B2C"}
    may = preview_file(sample_files["gstr1_may_json"], Source.GSTR1)
    assert [h["segment"] for h in may.hsn_summary] == [""]
    c = ClientService(db).create(**CLIENT)
    svc = ImportService(db)
    sf = svc.import_file(c.id, sample_files["gstr1_april_json"], Source.GSTR1)[0]
    with db.session() as s:
        assert s.scalar(select(func.count()).select_from(Gstr1Hsn)) == len(april.hsn_summary)
    svc.remove_import(c.id, sf.id, "tester")
    with db.session() as s:
        assert s.scalar(select(func.count()).select_from(Gstr1Hsn)) == 0


def test_table17_and_hsn_check(db, sample_files):
    c = ClientService(db).create(**CLIENT)
    for key in ("gstr1_april_json", "gstr1_may_json"):
        ImportService(db).import_file(c.id, sample_files[key], Source.GSTR1)
    w = Gstr9Service(db).working(c.id, "2025-26")
    assert {g["hsn"] for g in w.table17} == {"7318", "7326", "0713"}
    hsn_total, supplies = w.hsn_check
    assert hsn_total - supplies == B2CS_UNDER_REPORTED  # the B2C sale left out of B2CS is in the HSN summary
    assert any("HSN summary taxable value" in n for n in w.notes)


# ---------------------------------------------------------- Tables 10–14
def test_tables_10_to_14_from_next_year(db, sample_files):
    c = ClientService(db).create(**CLIENT)
    for key in ("gstr1_april_json", "gstr1_next_json"):
        ImportService(db).import_file(c.id, sample_files[key], Source.GSTR1)
    w = Gstr9Service(db).working(c.id, "2025-26")
    t10 = w.table10_14[0].gstr1
    assert t10.taxable == D(NEXT_AMEND_0005.taxable) - D("65000") + D(LATE_INVOICE.taxable)
    assert w.table10_14[4].gstr1.total == t10.total  # differential tax = 10 − 11
    docs = {i["document"]: i for i in w.next_year_items}
    assert docs[LATE_INVOICE.no]["table"] == "10" and "SGT/26-27/0001" not in docs  # next year's own invoice
    assert w.next_year_periods == ["2026-04"]
    # the next year's own invoice is not part of this year's Table 4
    assert w.row("4B").gstr1.taxable == D("369000")


def test_previous_year_amendment_and_claim_register():
    fy = "2025-26"
    orig = _doc("A-1", "1000", "180", date(2025, 4, 5), "2025-04")
    prev_amend = _doc("OLD-9", "900", "162", date(2025, 3, 20), "2025-05", True, "OLD-9", date(2025, 3, 20))
    late_cn = _doc("CN-7", "200", "36", date(2026, 3, 25), "2026-04", doc=DocType.CREDIT_NOTE)
    inv = _doc("P-1", "1000", "180", date(2026, 2, 10), "2026-02")
    actions = [("2026-05", ClaimAction(inv, "CLAIM", V(igst=D(180)))),
               ("2026-06", ClaimAction(inv, "REVERSE", V(igst=D(50)))),
               ("2026-12", ClaimAction(inv, "CLAIM", V(igst=D(10))))]  # after the cut-off – ignored
    w = build_gstr9(fy, fy_months(fy), [], [orig, prev_amend], [], {}, [], [late_cn], actions, "2026-11")
    status = {a["document"]: a["status"] for a in w.amendments}
    assert status["OLD-9"].startswith("relates to FY 2024-25") and w.row("4K").gstr1.total == 0
    assert not any("need the change from the original" in n for n in w.notes)
    rows = {r.code: r.gstr1 for r in w.table10_14}
    assert rows["11"].taxable == D(200) and rows["13"].igst == D(180) and rows["12"].igst == D(50)
    assert rows["14"].igst == D(-36)


# ------------------------------------------------------------ Table 14
def test_expense_ledger_keywords_and_reader(sample_files, tmp_path):
    assert row_for("Repairs to Machinery") == "14M" and row_for("Plant & Machinery") == "14O"
    assert row_for("Freight Outward") == "14B" and row_for("Audit Fees") == "14N"
    lines = read_expense_ledger(sample_files["expense_ledger"])
    assert len(lines) == len(EXPENSE_LEDGER)  # the grand-total line is skipped
    bad = tmp_path / "x.csv"
    bad.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(Exception):
        read_expense_ledger(bad)


def test_table14_import_and_statement(db, sample_files):
    c = ClientService(db).create(**CLIENT)
    svc = Gstr9cService(db)
    with pytest.raises(PermissionDenied):
        svc.import_expenses(c.id, "2025-26", sample_files["expense_ledger"], Session("v", "viewer"))
    preview = svc.import_expenses(c.id, "2025-26", sample_files["expense_ledger"], ADMIN, apply=False)
    assert preview and svc.inputs(c.id, "2025-26") == {}
    svc.import_expenses(c.id, "2025-26", sample_files["expense_ledger"], ADMIN)
    st = svc.statement(c.id, "2025-26")
    expected = sum(D(e) for _h, _v, _t, e in EXPENSE_LEDGER)
    assert st.table14_total == expected
    assert next(x for x in st.table14 if x.code == "14H").value == D("915000")
    assert st.table14_unreconciled == st.table14_claimed - expected
    assert any("14T" in n for n in st.notes)
    # a second import replaces the figures; rows no longer present are cleared
    small = sample_files["expense_ledger"].parent / "small.csv"
    small.write_text("Ledger,Amount,ITC\nOffice Rent,1000,180\n", encoding="utf-8")
    svc.import_expenses(c.id, "2025-26", small, ADMIN)
    st = svc.statement(c.id, "2025-26")
    assert st.table14_total == D(180) and next(x for x in st.table14 if x.code == "14A").value == 0
    empty = small.with_name("empty.csv")
    empty.write_text("Ledger,Amount\n", encoding="utf-8")
    with pytest.raises(ServiceError, match="no lines"):
        svc.import_expenses(c.id, "2025-26", empty, ADMIN)


def test_hsn_in_sync_and_purge(db, sample_files, tmp_path):
    c = ClientService(db).create(**CLIENT)
    ImportService(db).import_file(c.id, sample_files["gstr1_april_json"], Source.GSTR1)
    sync = SyncService(db)
    sync.authorise(c.id, "Proprietor", date.today() + timedelta(days=30), "Consent", ADMIN)
    pkg = sync.export_package(c.id, tmp_path / "cloud", "a-long-password", ADMIN)
    other = open_database(tmp_path / "o" / "o.db")
    try:
        cid = SyncService(other).import_package(pkg, "a-long-password", ADMIN)["client_id"]
        assert Gstr9Service(other).working(cid, "2025-26").table17
    finally:
        other.dispose()
    assert SecurityService(db).purge_client(c.id, CLIENT["gstin"], SETUP_SESSION)["gstr1_hsn"] > 0


def test_cli_phase8(tmp_path, sample_files, capsys):
    dbp = str(tmp_path / "p8.db")
    assert main(["--db", dbp, "client", "add", "--gstin", CLIENT["gstin"], "--name", CLIENT["name"]]) == 0
    for key in ("gstr1_april_json", "gstr1_next_json"):
        assert main(["--db", dbp, "import", "--client", CLIENT["gstin"], "--source", "gstr1",
                     "--file", str(sample_files[key])]) == 0
    capsys.readouterr()
    assert main(["--db", dbp, "gstr9", "--client", CLIENT["gstin"], "--fy", "2025-26"]) == 0
    out = capsys.readouterr().out
    assert "Table 17 HSN 7318" in out and "  10 " in out
    assert main(["--db", dbp, "gstr9c", "import-expenses", "--client", CLIENT["gstin"], "--fy", "2025-26",
                 "--file", str(sample_files["expense_ledger"]), "--preview"]) == 0
    assert "previewed – nothing saved" in capsys.readouterr().out
    assert main(["--db", dbp, "gstr9c", "import-expenses", "--client", CLIENT["gstin"], "--fy", "2025-26",
                 "--file", str(sample_files["expense_ledger"])]) == 0
    out = capsys.readouterr().out
    assert "saved to Table 14" in out and "14R" in out
