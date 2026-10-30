"""Phase 11: interest and late fees."""
from datetime import date
from decimal import Decimal

import pytest

from fintax_gst.cli import main
from fintax_gst.compliance.interest import gstr9_late_fee, interest, late_fee
from fintax_gst.core.models import Source
from fintax_gst.samples import CLIENT
from fintax_gst.services.auth import SETUP_SESSION, PermissionDenied, Session
from fintax_gst.services.clients import ClientService
from fintax_gst.services.common import ServiceError
from fintax_gst.services.gstr3b import Gstr3bService
from fintax_gst.services.gstr9c import Gstr9cService
from fintax_gst.services.imports import ImportService
from fintax_gst.services.interest import InterestService

AS_OF = date(2025, 10, 31)


def test_interest_and_late_fee_rules():
    assert interest(Decimal("100000"), date(2025, 5, 20), date(2025, 6, 19)) == (30, Decimal("1479.45"))
    assert interest(Decimal("100000"), date(2025, 5, 20), date(2025, 5, 20))[1] == 0  # paid on the due date
    assert interest(Decimal("-5"), date(2025, 5, 20), date(2025, 6, 19))[1] == 0
    due = date(2025, 5, 20)
    fee = late_fee("2025-04", due, date(2025, 6, 9), False, Decimal("12000000"))
    assert (fee.days, fee.cgst, fee.sgst) == (20, 500, 500)
    assert late_fee("2025-04", due, date(2025, 9, 9), False, Decimal("12000000")).cgst == 1000  # ≤ 1.5 cr cap
    assert late_fee("2025-04", due, date(2025, 12, 9), False, Decimal("40000000")).cgst == 2500
    assert late_fee("2025-04", due, date(2026, 3, 9), False, Decimal("90000000")).cgst == 5000
    assert late_fee("2025-04", due, date(2026, 3, 9), True, None).cgst == 250  # nil return
    assert late_fee("2025-04", due, date(2025, 6, 9), True, None).cgst == 200  # 20 days × ₹10
    assert late_fee("2021-05", due, date(2025, 6, 9), False, None) is None  # before June 2021: not computed
    g9 = gstr9_late_fee("2024-25", date(2025, 12, 31), date(2026, 1, 30), Decimal("30000000"), Decimal("31000000"))
    assert (g9.days, g9.cgst) == (30, 750)  # ₹25/day, cap 0.02% of 3.1 cr = 6,200
    assert gstr9_late_fee("2024-25", date(2025, 12, 31), date(2026, 12, 30), Decimal("30000000"),
                          Decimal("31000000")).cgst == 6200
    assert gstr9_late_fee("2024-25", date(2025, 12, 31), date(2026, 1, 30), Decimal("15000000"), Decimal(0)) is None
    assert gstr9_late_fee("2021-22", date(2022, 12, 31), date(2023, 1, 30), None, Decimal(0)) is None


def _client(db, files):
    c = ClientService(db).create(**CLIENT)
    svc = ImportService(db)
    for key, src in (("books_april", Source.BOOKS), ("gstr2b_april_json", Source.GSTR2B),
                     ("sales_april", Source.SALES), ("gstr1_april_json", Source.GSTR1)):
        svc.import_file(c.id, files[key], src)
    Gstr3bService(db).import_file(c.id, files["gstr3b_april_json"])
    return c


def test_interest_working(db, sample_files):
    c = _client(db, sample_files)
    svc = InterestService(db)
    rows, problems = svc.import_filings(c.id, sample_files["filings"], SETUP_SESSION)
    assert len(rows) == 2 and not problems
    w = svc.working(c.id, "2025-26", AS_OF)
    late = {r.return_type: r for r in w.late}
    assert (late["GSTR-1"].days, late["GSTR-1"].fee_total) == (4, 200)
    assert (late["GSTR-3B"].days, late["GSTR-3B"].fee_total) == (8, 400)
    assert late["GSTR-3B"].interest_total == 0 and late["GSTR-3B"].interest_paid == 120  # nothing paid in cash
    assert any("AATO" in n for n in w.notes)
    short = {e.head: e for e in w.exposures if e.kind == "SHORT_PAYMENT"}
    assert set(short) == {"cgst", "sgst"} and short["cgst"].amount == 1800
    assert (short["cgst"].days, short["cgst"].interest, short["cgst"].status) == (164, Decimal("145.58"), "OPEN")
    excess = [e for e in w.exposures if e.kind == "EXCESS_ITC"]
    assert excess and all("UPPER LIMIT" in e.basis and e.start == date(2025, 5, 28) for e in excess)
    d = w.drc03()
    assert d["cgst"]["tax"] == 1800 and d["cgst"]["fee"] == 300

    # the AATO slab lowers the cap; paying the short payment stops the interest
    Gstr9cService(db).set_input(c.id, "2025-26", "AATO", "12000000", "previous year turnover", SETUP_SESSION)
    svc.set_settlement(c.id, "SHORT_PAYMENT", "2025-04", "SETTLED", SETUP_SESSION, date(2025, 6, 19),
                       "DRC-03 AD2706250001")
    svc.set_settlement(c.id, "EXCESS_ITC", "2025-04", "NOT_PAYABLE", SETUP_SESSION,
                       note="ITC on bill of entry, not in GSTR-2B")
    w = svc.working(c.id, "2025-26", AS_OF)
    short = next(e for e in w.exposures if e.kind == "SHORT_PAYMENT" and e.head == "cgst")
    assert (short.days, short.interest, short.status) == (30, Decimal("26.63"), "SETTLED")
    assert all(e.status == "NOT_PAYABLE" and e.interest == 0 for e in w.exposures if e.kind == "EXCESS_ITC")
    assert w.drc03()["cgst"]["tax"] == 0 and w.drc03()["cgst"]["interest"] == Decimal("26.63")
    assert not any("AATO" in n for n in w.notes)

    with pytest.raises(ServiceError):
        svc.set_settlement(c.id, "EXCESS_ITC", "2025-04", "NOT_PAYABLE", SETUP_SESSION)  # reason needed
    with pytest.raises(PermissionDenied):
        svc.set_filing(c.id, "GSTR-3B", "2025-05", date(2025, 6, 20), Session("v", "viewer", "V"))


def test_no_false_excess_without_gstr2b(db, sample_files):
    c = ClientService(db).create(**CLIENT)
    Gstr3bService(db).import_file(c.id, sample_files["gstr3b_april_json"])
    w = InterestService(db).working(c.id, "2025-26", AS_OF)
    assert not w.exposures and any("GSTR-2B 2025-04 not imported" in n for n in w.notes)


def test_cli_interest(tmp_path, sample_files, capsys):
    dbp = str(tmp_path / "cli.db")
    assert main(["--db", dbp, "client", "add", "--name", CLIENT["name"], "--gstin", CLIENT["gstin"]]) == 0
    for src, key in (("sales", "sales_april"), ("gstr1", "gstr1_april_json")):
        assert main(["--db", dbp, "import", "--client", "1", "--source", src, "--file", str(sample_files[key])]) == 0
    assert main(["--db", dbp, "gstr3b", "import", "--client", "1", "--file",
                 str(sample_files["gstr3b_april_json"])]) == 0
    assert main(["--db", dbp, "interest", "filed", "--client", "1", "--return", "GSTR-3B", "--period", "2025-04",
                 "--date", "2025-05-28"]) == 0
    capsys.readouterr()
    assert main(["--db", dbp, "interest", "--client", "1", "--fy", "2025-26", "--as-of", "2025-10-31", "--out",
                 str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "8 day(s)" in out and "Tax short paid" in out and "DRC-03" in out
    from openpyxl import load_workbook

    wb = load_workbook(next(tmp_path.glob("FINTAXPRO_Interest_LateFee_*.xlsx")), read_only=True)
    assert wb.sheetnames == ["Interest & Late Fee"]
