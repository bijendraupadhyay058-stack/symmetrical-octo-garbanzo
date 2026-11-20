from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from fintax_gst.cli import main
from fintax_gst.core.models import Source
from fintax_gst.db.database import open_database
from fintax_gst.db.models import AuditLog, Gstr9cInput
from fintax_gst.importers.gstr3b import preview_gstr3b
from fintax_gst.importers.pipeline import preview_file
from fintax_gst.samples import CLIENT, SAMPLE_INTEREST
from fintax_gst.samples_outward import ADVANCE_MAY
from fintax_gst.services.auth import SETUP_SESSION, PermissionDenied, Session
from fintax_gst.services.clients import ClientService
from fintax_gst.services.common import ServiceError
from fintax_gst.services.gstr3b import Gstr3bService
from fintax_gst.services.gstr9 import Gstr9Service
from fintax_gst.services.gstr9c import Gstr9cService
from fintax_gst.services.imports import ImportService
from fintax_gst.services.outward import OutwardService
from fintax_gst.services.security import SecurityService
from fintax_gst.services.sync import SyncService

D = Decimal
ADMIN = Session("admin", "admin", "Admin")


def _client(db, files, books=True):
    c = ClientService(db).create(**CLIENT)
    svc = ImportService(db)
    keys = [("sales_april", Source.SALES), ("gstr1_april_json", Source.GSTR1), ("gstr1_may_json", Source.GSTR1)]
    if books:
        keys.append(("books_april", Source.BOOKS))
    for key, src in keys:
        svc.import_file(c.id, files[key], src)
    Gstr3bService(db).import_file(c.id, files["gstr3b_april_json"])
    return c


# ------------------------------------------------------------ advances
def test_gstr1_advances_and_liability(db, sample_files):
    p = preview_file(sample_files["gstr1_may_json"], Source.GSTR1)
    at = [s for s in p.outward_summary if s["section"] == "AT"]
    assert len(at) == 1 and at[0]["taxable"] == ADVANCE_MAY and at[0]["cgst"] == ADVANCE_MAY * D("0.09")
    assert not any("'at'" in w for w in p.file_warnings)
    c = _client(db, sample_files)
    [w] = OutwardService(db).liability(c.id, ["2025-05"])
    assert w.row("31A").gstr1.total == D("30000") * D("0.18") + ADVANCE_MAY * D("0.18")
    assert all(s.segment != "Nil / exempt / non-GST" or s.gstr1.total == 0 for s in w.segments)
    g9 = Gstr9Service(db).working(c.id, "2025-26")
    assert g9.row("4F").gstr1.taxable == ADVANCE_MAY and g9.advances_imported


# ------------------------------------------------------------ payments
def test_gstr3b_table61_json_and_template(sample_files, tmp_path):
    pv = preview_gstr3b(sample_files["gstr3b_april_json"])
    t = pv.entries["2025-04"]
    assert t["61INT"].total == D(SAMPLE_INTEREST) and t["61ITC"].total == t["31A"].total + t["31B"].total
    assert "61CASH" not in t  # nothing paid in cash
    tpl = tmp_path / "3b.csv"
    tpl.write_text("Period,Table,IGST,CGST,SGST,Cess\n2025-05,6.1 cash,100,50,50,0\n2025-05,61ITC,0,10,10,0\n"
                   "2025-05,6.1 fee,0,25,25,0\n", encoding="utf-8")
    t5 = preview_gstr3b(tpl).entries["2025-05"]
    assert t5["61CASH"].total == D(200) and t5["61FEE"].total == D(50) and t5["61ITC"].cgst == D(10)


def test_gstr9_table9_paid(db, sample_files):
    c = _client(db, sample_files)
    w = Gstr9Service(db).working(c.id, "2025-26")
    igst = w.table9[0]
    assert igst.paid_cash == 0 and igst.paid_itc == igst.declared and igst.paid == igst.declared
    assert igst.unpaid == igst.payable - igst.paid
    assert w.interest_paid == D(SAMPLE_INTEREST)
    assert not any("6.1" in n and "not imported:" in n for n in w.notes)


# --------------------------------------------------------------- GSTR-9C
def test_gstr9c_defaults_inputs_and_reasons(db, sample_files):
    c = _client(db, sample_files)
    svc = Gstr9cService(db)
    st = svc.statement(c.id, "2025-26")
    five_a = st.line("5A")
    assert five_a.source.startswith("default") and five_a.amount == D("761000")
    assert st.line("5Q").amount == Gstr9Service(db).working(c.id, "2025-26").row("5N").gstr1.taxable
    assert st.line("5R").amount == st.line("5Q").amount - st.line("5P").amount
    assert st.line("7E").amount == st.line("7A").amount - st.line("7B").amount - st.line("7C").amount - \
        st.line("7D").amount
    assert st.line("12A").source.startswith("default") and st.line("12A").amount == svc.books_itc(c.id, "2025-26")
    assert st.line("12F").amount == st.line("12E").amount - st.line("12D").amount
    assert any("Defaults used for 5A" in n for n in st.notes)
    assert {r.rate for r in st.table9} >= {"18%", "Credit/debit notes"}

    with pytest.raises(PermissionDenied):
        svc.set_input(c.id, "2025-26", "5A", "1", "", Session("v", "viewer"))
    with pytest.raises(ServiceError):
        svc.set_input(c.id, "2025-26", "5Z", "1", "", ADMIN)
    with pytest.raises(ServiceError):
        svc.set_input(c.id, "2025-26", "5A", "abc", "", ADMIN)
    with pytest.raises(ServiceError):
        svc.set_input(c.id, "2025-26", "R6", "10", "", ADMIN)
    svc.set_input(c.id, "2025-26", "5A", "8,00,000", "AFS note 21", ADMIN)
    svc.set_input(c.id, "2025-26", "5H", "15000", "Unbilled at 31-03", ADMIN)
    svc.set_input(c.id, "2025-26", "12B", "2000", "", ADMIN)
    svc.set_input(c.id, "2025-26", "R6", None, "Advance received in May", ADMIN)
    st = svc.statement(c.id, "2025-26")
    assert st.line("5A").source == "entered" and st.line("5P").amount == D("785000")
    assert st.line("12D").amount == svc.books_itc(c.id, "2025-26") + 2000
    assert st.reasons["R6"] == "Advance received in May"
    assert not any("record the reasons (Reasons for un-reconciled turnover" in n for n in st.notes)
    svc.set_input(c.id, "2025-26", "5A", None, "", ADMIN)  # clearing restores the default
    assert svc.statement(c.id, "2025-26").line("5A").source.startswith("default")
    with db.session() as s:
        assert s.query(AuditLog).filter(AuditLog.action == "GSTR9C_INPUT").count() == 5


def test_gstr9c_in_sync_and_purge(db, sample_files, tmp_path):
    c = _client(db, sample_files, books=False)
    Gstr9cService(db).set_input(c.id, "2025-26", "5A", "900000", "AFS", ADMIN)
    sync = SyncService(db)
    sync.authorise(c.id, "Proprietor", date.today() + timedelta(days=30), "Consent", ADMIN)
    pkg = sync.export_package(c.id, tmp_path / "cloud", "a-long-password", ADMIN)
    other = open_database(tmp_path / "o" / "o.db")
    try:
        cid = SyncService(other).import_package(pkg, "a-long-password", ADMIN)["client_id"]
        assert Gstr9cService(other).inputs(cid, "2025-26")["5A"] == (D("900000"), "AFS")
    finally:
        other.dispose()
    counts = SecurityService(db).purge_client(c.id, CLIENT["gstin"], SETUP_SESSION)
    assert counts["gstr9c_inputs"] == 1
    with db.session() as s:
        assert s.scalars(select(Gstr9cInput)).first() is None


def test_cli_gstr9c(tmp_path, sample_files, capsys):
    dbp = str(tmp_path / "c9.db")
    assert main(["--db", dbp, "client", "add", "--gstin", CLIENT["gstin"], "--name", CLIENT["name"]]) == 0
    for src, key in (("sales", "sales_april"), ("gstr1", "gstr1_april_json")):
        assert main(["--db", dbp, "import", "--client", CLIENT["gstin"], "--source", src,
                     "--file", str(sample_files[key])]) == 0
    capsys.readouterr()
    assert main(["--db", dbp, "gstr9c", "set", "--client", CLIENT["gstin"], "--fy", "2025-26", "--item", "5a",
                 "--amount", "750000", "--note", "AFS"]) == 0
    out = capsys.readouterr().out
    assert "5A recorded" in out and "7,50,000.00" in out and "entered" in out
    assert main(["--db", dbp, "gstr9c", "--client", CLIENT["gstin"], "--fy", "2025-26",
                 "--out", str(tmp_path / "o")]) == 0
    assert main(["--db", dbp, "gstr9c", "set", "--client", CLIENT["gstin"], "--fy", "2025-26",
                 "--item", "XX", "--amount", "1"]) == 1
