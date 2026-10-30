"""Phase 10: e-invoice (IRP) and e-way bill reconciliation."""
import csv
from collections import Counter

import pytest

from fintax_gst.cli import main
from fintax_gst.core.models import Category, ExceptionStatus, Source, side_labels
from fintax_gst.importers.pipeline import preview_file
from fintax_gst.importers.readers import UnsupportedFileError
from fintax_gst.samples import CLIENT
from fintax_gst.samples_outward import (
    EINV_CANCELLED, EINV_MATCHED, EINV_NOT_IN_BOOKS, EINV_NOT_REPORTED, EWB_MATCHED, EWB_MISSING, EWB_NOT_IN_BOOKS,
)
from fintax_gst.services.auth import SETUP_SESSION
from fintax_gst.services.clients import ClientService
from fintax_gst.services.imports import ImportService
from fintax_gst.services.reconciliation import ReconciliationService
from fintax_gst.services.reports import export_run
from fintax_gst.services.security import SecurityService


def _client(db, files, *sources):
    c = ClientService(db).create(**CLIENT)
    svc = ImportService(db)
    svc.import_file(c.id, files["sales_april"], Source.SALES)
    keys = {Source.EINV: "einv_april", Source.EWB: "ewb_april", Source.GSTR1: "gstr1_april_json"}
    for src in sources:
        svc.import_file(c.id, files[keys[src]], src)
    return c


def _why(ln):
    return " ".join(ln.reasons)


def _by_no(ctx):
    return {(ln.books or ln.gstr2b).invoice_no: ln for ln in ctx.result.lines}


def test_einvoice_report_import(sample_files):
    pv = preview_file(sample_files["einv_april"], Source.EINV)
    assert pv.layout == "einvoice_report"
    assert {r.invoice_no for r in pv.records} == {*EINV_MATCHED, EINV_CANCELLED, EINV_NOT_IN_BOOKS}
    export = next(r for r in pv.records if r.invoice_no == "EXP/25-26/001")
    assert export.supplier_gstin == "" and len(export.irn) == 64 and export.ref_status == "ACTIVE"
    cancelled = next(r for r in pv.records if r.invoice_no == EINV_CANCELLED)
    assert cancelled.ref_status == "CANCELLED" and cancelled.period == "2025-04"
    assert any("cancelled" in i.message for i in pv.issues if i.severity == "warning")
    # a register is not an e-invoice report, and an e-invoice report is not a GSTR-2B
    with pytest.raises(UnsupportedFileError):
        preview_file(sample_files["gstr2b_april"], Source.EINV)


def test_ewb_report_import_ignores_challans_and_inward(sample_files):
    pv = preview_file(sample_files["ewb_april"], Source.EWB)
    assert pv.layout == "ewb_report"
    ignored = [i.message for i in pv.issues if i.severity == "ignored"]
    assert len(ignored) == 2 and any("Delivery Challan" in m for m in ignored) and any("Inward" in m for m in ignored)
    # the cancelled and the regenerated e-way bill of one invoice are two records, not a duplicate
    two = [r for r in pv.records if r.invoice_no == "SGT/25-26/0002"]
    assert sorted(r.ref_status for r in two) == ["ACTIVE", "CANCELLED"] and not pv.duplicate_rows
    assert all(len(r.ref_no) == 12 for r in pv.records)


def test_sales_vs_einvoice(db, sample_files):
    c = _client(db, sample_files, Source.EINV)
    svc = ReconciliationService(db)
    ctx = svc.load(svc.run(c.id, "2025-04", compare_with=Source.EINV))
    assert ctx.run.comparison == "SALES_VS_EINV"
    assert side_labels(ctx.run.comparison) == ("Sales register", "e-Invoice (IRP)")
    lines = _by_no(ctx)
    assert {n for n, ln in lines.items() if ln.category == Category.FULLY_MATCHED} == set(EINV_MATCHED)
    cancelled = lines[EINV_CANCELLED]
    assert cancelled.category == Category.MISSING_IN_2B and cancelled.status == ExceptionStatus.CLIENT_CLARIFICATION
    assert "cancelled" in _why(cancelled)
    assert lines[EINV_NOT_REPORTED].category == Category.MISSING_IN_2B
    assert "No e-invoice" in _why(lines[EINV_NOT_REPORTED])
    assert lines[EINV_NOT_IN_BOOKS].category == Category.MISSING_IN_BOOKS
    # B2C and exempt sales are not e-invoiced: out of scope
    assert not any(n.startswith("CS/") or n == "SGT/25-26/0016" for n in lines)


def test_sales_vs_ewb_threshold_and_notes(db, sample_files):
    c = _client(db, sample_files, Source.EWB)
    svc = ReconciliationService(db)
    ctx = svc.load(svc.run(c.id, "2025-04", compare_with=Source.EWB))
    lines = _by_no(ctx)
    assert {n for n, ln in lines.items() if ln.category == Category.FULLY_MATCHED} == set(EWB_MATCHED)
    assert lines[EWB_MISSING].status == ExceptionStatus.PENDING_REVIEW and "No e-way bill" in _why(lines[EWB_MISSING])
    assert lines[EWB_NOT_IN_BOOKS.no].category == Category.MISSING_IN_BOOKS
    no_action = [n for n, ln in lines.items() if ln.status == ExceptionStatus.NO_ACTION
                 and ln.category == Category.MISSING_IN_2B]
    assert len(no_action) == 12  # 8 cash sales, 0011, 0014, the exempt sale and the credit note
    assert "threshold" in _why(lines["CS/25-26/001"]) and "Credit" in _why(lines["SGT-CN/25-26/001"])
    # nothing is hidden: every sales document is on a line
    assert Counter(ln.category for ln in ctx.result.lines)[Category.MISSING_IN_2B] == 13

    # a lower threshold makes the small documents exceptions again
    SecurityService(db).set_setting("ewb_threshold", 20000, SETUP_SESSION)
    lines = _by_no(svc.load(svc.run(c.id, "2025-04", compare_with=Source.EWB)))
    assert lines["SGT/25-26/0011"].status != ExceptionStatus.NO_ACTION  # ₹23,600
    assert lines["CS/25-26/001"].status == ExceptionStatus.NO_ACTION

    # a status chosen by the reviewer is kept on a re-run; a rule's status follows the rule
    ctx = svc.load(max(r.id for r in svc.list_runs(c.id)))
    line = _by_no(ctx)["CS/25-26/002"]
    svc.update_line(ctx.run.id, line.line_no, status=ExceptionStatus.CLOSED, remarks="checked", user="preparer")
    SecurityService(db).set_setting("ewb_threshold", 5000, SETUP_SESSION)
    lines = _by_no(svc.load(svc.run(c.id, "2025-04", compare_with=Source.EWB)))
    assert lines["CS/25-26/002"].status == ExceptionStatus.CLOSED and lines["CS/25-26/002"].remarks == "checked"
    assert lines["CS/25-26/003"].status == ExceptionStatus.PENDING_REVIEW  # ₹5,605 ≥ ₹5,000


def test_latest_import_of_a_reference_wins(db, sample_files, tmp_path):
    c = _client(db, sample_files, Source.EWB)
    # a later report shows the e-way bill of SGT/25-26/0001 cancelled
    with open(sample_files["ewb_april"], encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    later = tmp_path / "ewb_later.csv"
    with later.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(rows[0])
        w.writerow(rows[1][:-1] + ["Cancelled"])
    ImportService(db).import_file(c.id, later, Source.EWB)
    svc = ReconciliationService(db)
    line = _by_no(svc.load(svc.run(c.id, "2025-04", compare_with=Source.EWB)))["SGT/25-26/0001"]
    assert line.category == Category.MISSING_IN_2B and "cancelled" in _why(line)


def test_review_work_stays_with_its_comparison(db, sample_files):
    c = _client(db, sample_files, Source.EINV, Source.EWB, Source.GSTR1)
    svc = ReconciliationService(db)
    g1 = svc.load(svc.run(c.id, "2025-04", compare_with=Source.GSTR1))
    line = _by_no(g1)["SGT/25-26/0011"]  # not in GSTR-1 either
    svc.update_line(g1.run.id, line.line_no, status=ExceptionStatus.BOOKS_CORRECTION, remarks="GSTR-1 amendment due",
                    user="preparer")
    ewb = _by_no(svc.load(svc.run(c.id, "2025-04", compare_with=Source.EWB)))["SGT/25-26/0011"]
    assert ewb.status == ExceptionStatus.NO_ACTION and not ewb.remarks
    again = _by_no(svc.load(svc.run(c.id, "2025-04", compare_with=Source.GSTR1)))["SGT/25-26/0011"]
    assert again.status == ExceptionStatus.BOOKS_CORRECTION and again.remarks == "GSTR-1 amendment due"


def test_einvoice_report_export(db, sample_files, tmp_path):
    c = _client(db, sample_files, Source.EINV)
    run_id = ReconciliationService(db).run(c.id, "2025-04", compare_with=Source.EINV)
    paths = export_run(db, run_id, tmp_path, pdf=False)
    from openpyxl import load_workbook

    wb = load_workbook(paths[0], read_only=True)
    assert not any("3.1" in n or "Liability" in n for n in wb.sheetnames)


def test_cli_einvoice(tmp_path, sample_files, capsys):
    dbp = str(tmp_path / "cli.db")
    assert main(["--db", dbp, "client", "add", "--name", CLIENT["name"], "--gstin", CLIENT["gstin"]]) == 0
    for src, key in (("sales", "sales_april"), ("einv", "einv_april"), ("ewb", "ewb_april")):
        assert main(["--db", dbp, "import", "--client", "1", "--source", src, "--file",
                     str(sample_files[key])]) == 0
    capsys.readouterr()
    assert main(["--db", dbp, "reconcile", "--client", "1", "--from", "2025-04", "--compare", "ewb"]) == 0
    out = capsys.readouterr().out
    assert "e-Way bill" in out or "Sales register" in out
