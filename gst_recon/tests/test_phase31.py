"""Voucher-wise ledger split: vouchers from Tally (Day Book XML, ledger voucher lists), parts from vouchers with
their own GST, nothing used twice, vouchers reconciled to the ledger."""
import json
from decimal import Decimal as D

import pytest

from fintax_gst.samples import CLIENT
from fintax_gst.services.clients import ClientService
from fintax_gst.services.common import ServiceError

FY = "2025-26"
L = D(100000)


def _setup(db, files):
    from fintax_gst.services.bifurcation import BifurcationService

    c = ClientService(db).create(**CLIENT)
    svc = BifurcationService(db)
    svc.import_tb(c.id, FY, files["trial_balance"], "a")
    ids = {v.ledger.name: v.ledger.id for v in svc.views(c.id, FY)}
    return c, svc, ids


def test_voucher_reader(sample_files):
    from fintax_gst.importers.vouchers import read_vouchers

    vf = read_vouchers(sample_files["daybook_xml"])
    assert vf.ledgers == {"Repairs & Maintenance": 4, "Freight Inward": 1}
    rep = [x for x in vf.lines if x.ledger == "Repairs & Maintenance"]
    assert sum(x.amount for x in rep) == 3 * L
    single = next(x for x in rep if x.voucher_no == "P-101")
    assert single.tax["cgst"] == D(10800) and single.gstin
    multi = next(x for x in rep if x.voucher_no == "J-77")
    assert multi.tax is None and "2 ledgers" in multi.tax_note
    vf = read_vouchers(sample_files["ledger_vouchers"])
    assert vf.ledgers == {"Professional Fees": 3} and all(x.tax is None for x in vf.lines)
    assert sum(x.amount for x in vf.lines) == 2 * L


def test_split_voucher_by_voucher(db, sample_files):
    from fintax_gst.services.bifurcation import SplitIn

    c, svc, ids = _setup(db, sample_files)
    _sf, _vf, stats = svc.import_vouchers(c.id, FY, sample_files["daybook_xml"], "a")
    assert stats["saved"] == 5
    with pytest.raises(ServiceError, match="already imported"):
        svc.import_vouchers(c.id, FY, sample_files["daybook_xml"], "a")
    rid = ids["Repairs & Maintenance"]
    view = next(v for v in svc.views(c.id, FY) if v.ledger.id == rid)
    assert view.vouchers == (4, 3 * L) and view.voucher_difference == 0
    lines = {v.voucher_no: v for v in svc.voucher_lines(rid)}
    services = svc.part_from_vouchers(rid, [lines["P-101"].id, lines["P-188"].id], "Repairs & maintenance",
                                      "services", eligibility="eligible")
    assert services.amount == D(180000) and services.cgst == D(16200) and services.gst_basis == "vouchers"
    spares = svc.part_from_vouchers(rid, [lines["P-240"].id], "Stores & spares", "inputs", eligibility="eligible")
    mixed = svc.part_from_vouchers(rid, [lines["J-77"].id], "Repairs & maintenance", "services")
    assert mixed.cgst is None and "GST not known" in mixed.basis_note
    v = svc.save_splits(rid, [services, spares, mixed], "partner")
    assert v.state == "Approved" and v.unallocated == 0
    assert json.loads(v.splits[0].voucher_ids) == sorted([lines["P-101"].id, lines["P-188"].id])
    sm = svc.summary(c.id, FY)
    assert sm.table6[("6B", "services")].cgst == D(16200) and sm.table6[("6B", "inputs")].sgst == D(9000)
    # a voucher is used once: not offered again, and refused in another part or ledger
    assert svc.voucher_lines(ids["Freight Inward"])[0].voucher_no == "J-77"
    freight_line = svc.voucher_lines(ids["Freight Inward"])[0]
    with pytest.raises(ServiceError, match="not this ledger"):
        svc.save_splits(ids["Freight Inward"], [SplitIn(L, "Freight & transportation", "services",
                                                        voucher_ids=[lines["P-101"].id])], "a")
    with pytest.raises(ServiceError, match="used in another part"):
        svc.save_splits(rid, [services, SplitIn(D(120000), "Stores & spares", "inputs",
                                                voucher_ids=[lines["P-101"].id])], "a")
    _ = freight_line


def test_ledger_voucher_list_and_reconciliation(db, sample_files, tmp_path):
    from openpyxl import load_workbook

    c, svc, ids = _setup(db, sample_files)
    svc.import_vouchers(c.id, FY, sample_files["ledger_vouchers"], "a")
    pf = next(v for v in svc.views(c.id, FY) if v.ledger.name == "Professional Fees")
    assert pf.vouchers == (3, 2 * L) and not any("vouchers imported" in w for w in pf.warnings)
    lines = svc.voucher_lines(pf.ledger.id)
    audit = svc.part_from_vouchers(pf.ledger.id, [lines[0].id], "Legal & audit fees", "services")
    assert audit.amount == L and audit.taxable is None and audit.gst_basis == ""
    # a partial voucher file shows up as a difference against the ledger
    p = tmp_path / "Freight Inward.csv"
    p.write_text("Date,Particulars,Vch Type,Vch No.,Debit,Credit\n01-05-2025,Shree Roadways,Journal,J-5,40000,\n",
                 encoding="utf-8")
    svc.import_vouchers(c.id, FY, p, "a")
    fr = next(v for v in svc.views(c.id, FY) if v.ledger.name == "Freight Inward")
    assert fr.voucher_difference == D(-60000) and any("vouchers imported" in w for w in fr.warnings)
    out = svc.export_xlsx(c.id, FY, tmp_path / "b.xlsx")
    ws = load_workbook(out)["Voucher Lines"]
    assert ws.max_row == 5 and ws.cell(2, 10).value == "(not allocated)"
    # outside the year is left out
    q = tmp_path / "other.csv"
    q.write_text("Date,Particulars,Vch Type,Vch No.,Debit,Credit\n01-05-2024,Old,Journal,J-1,100,\n", encoding="utf-8")
    _sf, _vf, stats = svc.import_vouchers(c.id, FY, q, "a")
    assert stats["saved"] == 0 and stats["outside_year"] == 1
    # removing the voucher import removes its lines
    from fintax_gst.services.imports import ImportService
    sf = next(f for f in ImportService(db).list_files(c.id) if f.file_name == "Freight Inward.csv")
    ImportService(db).remove_import(c.id, sf.id, "a")
    fr = next(v for v in svc.views(c.id, FY) if v.ledger.name == "Freight Inward")
    assert fr.vouchers is None
