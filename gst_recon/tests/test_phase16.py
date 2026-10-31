"""Phase 16: revised files, Rule 42/43, e-invoice / e-way bill JSON."""
from datetime import date
from decimal import Decimal as D

import pytest

from fintax_gst.core.models import Source
from fintax_gst.samples import CLIENT, gstin
from fintax_gst.services.clients import ClientService
from fintax_gst.services.common import ServiceError
from fintax_gst.services.imports import ImportService

MH = gstin("27", "AABCM1234K")
HEAD = "GSTIN,Supplier Name,Invoice No,Invoice Date,Taxable Value,CGST,SGST\n"


def _reg(path, *rows):
    path.write_text(HEAD + "".join(f"{MH},Mahalaxmi,{no},{dt},{tx},{tax},{tax}\n" for no, dt, tx, tax in rows))
    return path


# ------------------------------------------------------------------ revised file (16C)
def test_replace_with_revised_file(db, tmp_path):
    from sqlalchemy import select

    from fintax_gst.core.models import ExceptionStatus
    from fintax_gst.db.models import AuditLog, Invoice, ReconRun, SourceFile
    from fintax_gst.services.reconciliation import ReconciliationService
    from fintax_gst.services.revision import RevisionService

    c = ClientService(db).create(**CLIENT)
    imp = ImportService(db)
    old, _ = imp.import_file(c.id, _reg(tmp_path / "april.csv", ("A-1", "02-04-2025", 1000, 90),
                                        ("A-2", "03-04-2025", 2000, 180), ("A-3", "04-04-2025", 500, 45)),
                             Source.BOOKS, period="2025-04")
    two_b = _reg(tmp_path / "2b.csv", ("A-1", "02-04-2025", 1000, 90))
    imp.import_file(c.id, two_b, Source.GSTR2B, period="2025-04")
    recon = ReconciliationService(db)
    run = recon.run(c.id, "2025-04")
    lines = {(ln.books.invoice_no if ln.books else ""): ln for ln in recon.load(run).result.lines}
    recon.update_line(run, lines["A-2"].line_no, "priya", status=ExceptionStatus.SUPPLIER_FOLLOWUP.value,
                      remarks="Asked the supplier")
    with db.session() as s:
        a1, a2 = (s.scalar(select(Invoice.id).where(Invoice.invoice_no == n)) for n in ("A-1", "A-2"))

    revised = _reg(tmp_path / "april_revised.csv", ("A-1", "02-04-2025", 1000, 90),
                   ("A-2", "03-04-2025", 2100, 189), ("A-4", "09-04-2025", 700, 63))
    svc = RevisionService(db)
    preview = imp.preview(c.id, revised, Source.BOOKS, "2025-04")
    diff = svc.compare(c.id, old.id, preview)
    assert [i for i, _r in diff.unchanged] == [a1] and [ch.invoice_id for ch, _r in diff.changed] == [a2]
    assert diff.changed[0][0].differences["taxable"] == (D("2000"), D("2100"))
    assert [r.invoice_no for r in diff.added] == ["A-4"] and [i.invoice_no for i in diff.removed] == ["A-3"]
    assert [r.id for r in diff.runs_affected] == [run] and diff.needs_confirmation
    with pytest.raises(ServiceError, match="confirm"):
        svc.replace(c.id, old.id, preview, "priya")

    new, _ = svc.replace(c.id, old.id, preview, "priya", confirmed=True)
    with db.session() as s:
        docs = {i.invoice_no: i for i in s.scalars(select(Invoice).where(Invoice.source_type == "BOOKS"))}
        assert set(docs) == {"A-1", "A-2", "A-4"} and docs["A-1"].id == a1 and docs["A-2"].id == a2  # same records
        assert docs["A-2"].taxable == D("2100") and docs["A-2"].source_file_id == new.id
        assert s.get(SourceFile, old.id) is None and s.get(ReconRun, run) is None  # the run used A-3: removed
        a = s.scalars(select(AuditLog).where(AuditLog.action == "REPLACE")).one()
        assert "april.csv" in a.details_json and "A-3" in a.details_json and '"2000", "2100"' in a.details_json
    # without a run using the removed documents, review work on kept documents stays
    run2 = recon.run(c.id, "2025-04")
    lines2 = {(ln.books.invoice_no if ln.books else ""): ln for ln in recon.load(run2).result.lines}
    recon.update_line(run2, lines2["A-1"].line_no, "priya", remarks="checked")
    again = _reg(tmp_path / "april_v3.csv", ("A-1", "02-04-2025", 1000, 90), ("A-2", "03-04-2025", 2100, 189),
                 ("A-4", "09-04-2025", 700, 63), ("A-5", "10-04-2025", 100, 9))
    p3 = imp.preview(c.id, again, Source.BOOKS, "2025-04")
    d3 = svc.compare(c.id, new.id, p3)
    assert not d3.needs_confirmation and [r.invoice_no for r in d3.added] == ["A-5"]
    new3, _ = svc.replace(c.id, new.id, p3, "priya")
    kept = {(ln.books.invoice_no if ln.books else ""): ln for ln in recon.load(run2).result.lines}
    assert kept["A-1"].remarks == "checked"  # the run and its review work are untouched
    with pytest.raises(ServiceError, match="already imported"):
        svc.compare(c.id, new3.id, imp.preview(c.id, again, Source.BOOKS, "2025-04"))
    with pytest.raises(ServiceError, match="same kind"):
        svc.compare(c.id, new3.id, imp.preview(c.id, two_b, Source.GSTR2B, "2025-04"))


# ------------------------------------------------------------------ Rule 42 / 43 (16A)
def test_rule42_formula():
    from fintax_gst.compliance.rule42 import Rule42Month, Rule42Year, capital_good_tm

    m = Rule42Month("2025-04", {"igst": D("6000"), "cgst": D("2000"), "sgst": D("2000"), "cess": D(0)},
                    t1=D("500"), t2=D("1000"), t4=D("3500"), exempt=D("200000"), turnover=D("1000000"))
    assert m.c1_total == D("10000") and m.c2 == D("5000") and m.ratio == D("0.2")
    assert m.d1 == D("1000.00") and m.d2 == 0
    assert m.reversal == {"igst": D("600.00"), "cgst": D("200.00"), "sgst": D("200.00"), "cess": D("0")}
    m.non_business = True
    assert m.d2 == D("250.00") and m.total == D("1250.00")
    tm = capital_good_tm({"cgst": D("6000"), "sgst": D("6000")}, date(2025, 4, 15), "2025-04")
    assert tm["cgst"] == D("100.00")  # 6000 / 60 from the month of purchase
    assert capital_good_tm({"cgst": D("6000")}, date(2025, 4, 15), "2030-04") is None  # after 60 months
    assert capital_good_tm({"cgst": D("6000")}, date(2025, 4, 15), "2025-03") is None
    m.capital_goods.append(("Generator", tm))
    assert m.te["cgst"] == D("20.00")  # 20 % of 100
    year = Rule42Year("2025-26", [m], exempt=D("100000"), turnover=D("1000000"))  # 10 % over the year
    assert year.d1 == D("500.00") and year.reversed_monthly == D("1250.00") and year.difference == D("-500.00")
    short = Rule42Year("2025-26", [m], exempt=D("300000"), turnover=D("1000000"))
    assert short.difference == D("500.00") and short.interest(date(2026, 9, 30)) > 0


def test_rule42_service_and_gstr3b(db, tmp_path):
    from fintax_gst.services.batch import BatchService, write_example
    from fintax_gst.services.common_credit import CommonCreditService
    from fintax_gst.services.gstr3b_draft import Gstr3bDraftService
    from fintax_gst.services.tally_journals import TallyJournalService

    BatchService(db).run(write_example(tmp_path / "b"), create_clients=True)
    cc, g3 = CommonCreditService(db), Gstr3bDraftService(db)
    before = g3.draft(1, "2025-04").t4["4B1"].total
    m = cc.month(1, "2025-04")
    assert m.exempt == D(12000) and m.turnover > m.exempt and m.c2 == m.c1_total
    assert not cc.applies(1, "2025-04")  # nothing saved: the draft is unchanged
    cc.save(1, "2025-04", t4=D("10000"), user="accountant")
    m = cc.month(1, "2025-04")
    after = g3.draft(1, "2025-04")
    assert after.t4["4B1"].total == before + m.total and any("Rule 42/43" in n for n in after.notes)
    (j,) = TallyJournalService(db).entries(1, "2025-04", "rule42")
    assert j.total == m.total and j.balanced()
    gid = cc.add_good(1, "Generator", date(2025, 4, 2), cgst=D("3000"), sgst=D("3000"), user="accountant")
    assert cc.month(1, "2025-05").capital_goods and cc.applies(1, "2025-05")  # Rule 43 runs on by itself
    cc.remove_good(1, gid, "accountant")
    assert not cc.applies(1, "2025-05")
    with pytest.raises(ServiceError):
        cc.save(1, "2025-04", t1=D("-1"))
    with pytest.raises(ServiceError):
        cc.add_good(1, "Nothing", date(2025, 4, 2))
    # a month without sales takes E / F of the last month that had sales
    assert cc.month(1, "2025-06").ratio_from == "2025-04"
    y = cc.year(1, "2025-26")
    assert [x.period for x in y.months] == ["2025-04"]
