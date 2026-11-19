"""Rule 37A reversal tracker: supplier GSTR-3B filing status, reversal, re-availment."""
import json
from datetime import date
from decimal import Decimal as D

import pytest

from fintax_gst.samples import CLIENT
from fintax_gst.services.clients import ClientService
from fintax_gst.services.common import ServiceError
from fintax_gst.services.rule37a import Rule37aService, parse_period

from .test_phase32 import SUP, SUP2, add_docs

FY = "2024-25"
SUP3 = "24AAACC1206D1ZM"


def test_parse_period():
    assert parse_period("2025-06") == parse_period("06-2025") == parse_period("062025") == "2025-06"
    assert parse_period("Jun-25") == parse_period("June 2025") == parse_period(date(2025, 6, 9)) == "2025-06"
    assert parse_period("13-2025") is None and parse_period("") is None


@pytest.fixture
def client(db):
    c = ClientService(db).create(**CLIENT)
    add_docs(db, c.id, [
        ("GSTR2B", SUP, "INV", "A1", date(2024, 6, 3), "2024-06", 10000, 1800, ""),
        ("GSTR2B", SUP, "INV", "A2", date(2024, 6, 9), "2024-06", 5000, 900, ""),
        ("GSTR2B", SUP, "CRN", "C1", date(2024, 6, 20), "2024-06", 1000, 180, ""),
        ("GSTR2B", SUP2, "INV", "B1", date(2024, 8, 3), "2024-08", 20000, 3600, ""),
        ("GSTR2B", SUP3, "INV", "Q1", date(2024, 5, 3), "2024-05", 4000, 720, ""),  # quarterly supplier
        ("GSTR2B", SUP3, "INV", "Q2", date(2024, 11, 3), "2024-11", 1000, 180, ""),  # status unknown
        ("BOOKS", SUP, "INV", "A1", date(2024, 6, 3), "2024-06", 10000, 1800, ""),
    ])
    return c


def test_working_and_actions(db, client, tmp_path):
    svc = Rule37aService(db)
    svc.set_status(SUP, "2024-06", False, user="a")
    svc.set_status(SUP2, "Aug-24", True, date(2025, 10, 15), user="a")  # after 30-09-2025
    svc.set_status(SUP3, "2024-06", True, date(2024, 7, 22))  # quarter Apr-Jun
    with pytest.raises(ServiceError):
        svc.set_status("BAD", "2024-06", True)
    w = svc.working(client.id, FY, date(2025, 10, 20))
    by = {(ln.gstin, ln.period): ln for ln in w.lines}
    a = by[(SUP, "2024-06")]
    assert a.state == "not_filed" and a.total == D(2520) and a.docs == 3
    assert by[(SUP2, "2024-08")].state == "filed_late"
    assert by[(SUP3, "2024-05")].state == "filed"
    assert by[(SUP3, "2024-11")].state == "unknown"
    assert w.total("reverse") == D(2520) + D(3600) and w.total("unknown") == D(180)
    assert not w.provisional and w.reverse_by == date(2025, 11, 30)
    assert w.lines[0].gstin == SUP  # not filed first
    with pytest.raises(ServiceError, match="before the re-availment"):
        svc.record(client.id, SUP2, "2024-08", reclaimed_in="2025-11")
    svc.record(client.id, SUP2, "2024-08", reversed_in="2025-10", note="reversed in Oct", user="a")
    w = svc.working(client.id, FY, date(2025, 10, 20))
    late = next(ln for ln in w.lines if ln.gstin == SUP2)
    assert "re-avail" in late.action and w.total("reclaim") == D(3600) and w.total("pending") == D(2520)
    with pytest.raises(ServiceError, match="before the reversal"):
        svc.record(client.id, SUP2, "2024-08", reclaimed_in="2025-09")
    svc.record(client.id, SUP2, "2024-08", reclaimed_in="2025-11", user="a")
    w = svc.working(client.id, FY, date(2025, 10, 20))
    assert next(ln for ln in w.lines if ln.gstin == SUP2).action == "Reclaimed" and w.total("reclaim") == 0
    out = svc.export_xlsx(client.id, FY, tmp_path / "r37a.xlsx", date(2025, 10, 20))
    from openpyxl import load_workbook

    ws = load_workbook(out).active
    assert ws.cell(5, 1).value == SUP and ws.cell(5, 10).value.startswith("Not filed")


def test_import_status(db, client, tmp_path):
    svc = Rule37aService(db)
    j = tmp_path / "2a.json"
    j.write_text(json.dumps({"data": {"fp": "062024", "b2b": [
        {"ctin": SUP, "cfs": "Y", "cfs3b": "N", "inv": []},
        {"ctin": SUP2, "cfs": "Y", "cfs3b": "Y", "flprdr1": "082024", "inv": []}]}}))
    n, _notes = svc.import_file(j, "a")
    assert n == 2
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Supplier filing status"])
    ws.append(["GSTIN of supplier", "Tax period", "GSTR-3B filing status", "Date of filing"])
    ws.append([SUP3, "Nov-24", "Filed", date(2024, 12, 20)])
    ws.append([SUP, "06-2024", "", ""])  # unknown never overwrites the known "not filed"
    wb.save(tmp_path / "list.xlsx")
    n, _ = svc.import_file(tmp_path / "list.xlsx", "a")
    assert n == 2
    st = svc.statuses([SUP, SUP2, SUP3])
    assert st[(SUP, "2024-06")].gstr3b_filed is False and st[(SUP2, "2024-08")].gstr3b_filed is True
    assert st[(SUP3, "2024-11")].filed_on == date(2024, 12, 20)
    w = svc.working(client.id, FY, date(2025, 3, 1))
    assert w.provisional
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"data": {"docdata": {}}}))
    with pytest.raises(ServiceError, match="No GSTR-3B filing status"):
        svc.import_file(bad)
