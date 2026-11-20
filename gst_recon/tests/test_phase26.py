"""Phase 25: follow-up from the Return comparison (letters, DRC-01B/01C replies, DRC-03) and year on year."""
from datetime import date
from decimal import Decimal as D

import pytest

from fintax_gst.samples import CLIENT
from fintax_gst.services.auth import SETUP_SESSION
from fintax_gst.services.clients import ClientService
from fintax_gst.services.common import ServiceError

from .test_phase4 import _full


def test_reply_drafts_and_drc03(db, sample_files, tmp_path):
    from docx import Document
    from openpyxl import load_workbook

    from fintax_gst.samples_outward import SHORT_PAID_3B
    from fintax_gst.services.compare_actions import CompareActionService
    from fintax_gst.services.notices import NoticeService

    c, _i, _o = _full(db, sample_files)
    svc = CompareActionService(db)
    assert svc.excess_months(c.id, "2025-26", "1_3B") == ["2025-04"]
    with pytest.raises(ServiceError):
        svc.excess_months(c.id, "2025-26", "2A_2B")
    path, nid = svc.reply_draft(c.id, "2025-26", "1_3B", tmp_path, SETUP_SESSION, reference="ZD2707250001",
                                notice_date=date(2025, 7, 1))
    assert path.exists() and "DRC-01B" in path.name
    n = NoticeService(db).get(nid)
    assert n.form == "DRC-01B" and n.amount == SHORT_PAID_3B and n.period_from == "2025-04" and n.status == "OPEN"
    text = "\n".join(p.text for p in Document(path).paragraphs)
    assert "ZD2707250001" in text
    path2, nid2 = svc.reply_draft(c.id, "2025-26", "3B_2B", tmp_path, SETUP_SESSION)
    assert NoticeService(db).get(nid2).form == "DRC-01C" and NoticeService(db).get(nid2).amount == D(2000)
    with pytest.raises(ServiceError):
        svc.reply_draft(c.id, "2025-26", "1_3B", tmp_path, None)  # not logged in

    w = svc.drc03(c.id, "2025-26", "1_3B", date(2025, 7, 31))
    heads = w.by_head()
    assert heads["cgst"]["tax"] + heads["sgst"]["tax"] == SHORT_PAID_3B
    assert all(r.days == 72 and r.interest > 0 for r in w.rows)  # from the day after the 20 May due date
    assert w.total == SHORT_PAID_3B + sum(r.interest for r in w.rows)
    out = svc.export_drc03(w, tmp_path / "drc03.xlsx")
    ws = load_workbook(out).active
    assert "DRC-03 working" in ws["A1"].value and "rule 88C" in ws["A2"].value
    itc = svc.drc03(c.id, "2025-26", "3B_2B", date(2025, 7, 31))
    assert itc.rows and any("UPPER LIMIT" in n for n in itc.notes) and any("4(C)" in n for n in itc.notes)
    with pytest.raises(ServiceError):
        svc.drc03(c.id, "2025-26", "2A_2B")


def test_supplier_letters_from_comparison(db, sample_files, tmp_path):
    from fintax_gst.services.compare_actions import CompareActionService

    c, _i, _o = _full(db, sample_files)
    n, files = CompareActionService(db).supplier_letters(c.id, "2025-26", tmp_path, "accountant")
    assert n >= 1 and files and all(f.exists() for f in files)
    assert {f.suffix for f in files} == {".docx", ".pdf"}
    empty = ClientService(db).create(**{**CLIENT, "gstin": "27AAPFU0939F2ZU"})
    with pytest.raises(ServiceError, match="no letters"):
        CompareActionService(db).supplier_letters(empty.id, "2025-26", tmp_path)


def test_year_on_year(db, sample_files, tmp_path):
    from openpyxl import load_workbook

    from fintax_gst.services.yoy import YoyService, pct, prev_fy

    assert prev_fy("2025-26") == "2024-25" and pct(D(110), D(100)) == D("10.0") and pct(D(1), D(0)) is None
    c, _i, _o = _full(db, sample_files)
    svc = YoyService(db)
    y = svc.build(c.id, "2025-26", 3, date(2025, 8, 10))
    assert y.years == ["2023-24", "2024-25", "2025-26"] and y.latest == "2025-26" and y.previous == "2024-25"
    assert y.total("2025-26", "sales") > 0 and y.total("2024-25", "sales") is None
    assert y.total("2024-25", "itc_books") > 0  # March 2025 purchases, not reconciled: added from the register
    d, p = y.change("itc_books")
    assert d == y.total("2025-26", "itc_books") - y.total("2024-25", "itc_books") and p is not None
    assert y.like_for_like("itc_books") == (None, None, 0)  # no month has both years
    assert any("No data imported for 2023-24" in n for n in y.notes)
    assert any("still in progress" in n for n in y.notes)
    by = {s.name: s for s in y.suppliers}
    assert by["Mahalaxmi Steel Pvt Ltd"].status(y.years) == "" and by["Kovai Textiles Pvt Ltd"].status(y.years) \
        == "New supplier"
    out = svc.export_xlsx(y, tmp_path / "yoy.xlsx")
    wb = load_workbook(out)
    assert {"Summary", "Monthly", "Suppliers", "Notes"} <= set(wb.sheetnames)
    assert wb["Summary"].cell(2, 4).value == "2025-26" and wb["Summary"].cell(3, 1).value.startswith("Sales")
    with pytest.raises(ServiceError):
        svc.build(c.id, "2025-26", 9)
