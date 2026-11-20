"""Return comparison: GSTR-3B vs GSTR-2B, GSTR-1 vs GSTR-3B, GSTR-2A vs GSTR-2B, with portal files imported."""
import json
from decimal import Decimal as D
from pathlib import Path

import pytest

from fintax_gst.core.models import Source
from fintax_gst.samples import CLIENT, SUPPLIERS, g2b_docs
from fintax_gst.services.clients import ClientService
from fintax_gst.services.common import ServiceError
from fintax_gst.services.imports import ImportService

from .test_phase4 import _full


def write_gstr2a_json(path: Path, gstin: str | None = CLIENT["gstin"]) -> dict:
    """April GSTR-2A from the GSTR-2B sample: one invoice left out, one with a different amount and one invoice
    that is not in the GSTR-2B at all (supplier filed after the cut-off)."""
    docs = [d for d in g2b_docs() if d.doc == "INV" and not d.original_no]
    left_out, changed = docs[0], docs[1]
    b2b: dict[str, dict] = {}
    for d in docs[1:]:
        g, name = SUPPLIERS[d.sup]
        bump = D(100) if d is changed else D(0)
        det = {"txval": float(D(d.taxable)), "rt": d.rate, "iamt": float(D(d.igst) + (bump if D(d.igst) else 0)),
               "camt": float(D(d.cgst) + (bump / 2 if not D(d.igst) else 0)),
               "samt": float(D(d.sgst) + (bump / 2 if not D(d.igst) else 0)), "csamt": float(D(d.cess))}
        b2b.setdefault(g, {"ctin": g, "trdnm": name, "cfs": "Y", "fldtr1": "11-May-25", "inv": []})["inv"].append(
            {"inum": d.no, "idt": d.dt.strftime("%d-%m-%Y"), "val": float(D(d.taxable) * D("1.18")), "pos": "27",
             "rchrg": "Y" if d.rcm else "N", "inv_typ": "R", "itms": [{"num": 1, "itm_det": det}]})
    g, name = SUPPLIERS["MSL"]
    b2b.setdefault(g, {"ctin": g, "trdnm": name, "cfs": "Y", "fldtr1": "20-May-25", "inv": []})["inv"].append(
        {"inum": "LATE-777", "idt": "28-04-2025", "val": 11800, "pos": "27", "rchrg": "N", "inv_typ": "R",
         "itms": [{"num": 1, "itm_det": {"txval": 10000, "rt": 18, "iamt": 0, "camt": 900, "samt": 900,
                                         "csamt": 0}}]})
    payload = {"fp": "042025", "b2b": list(b2b.values())}
    if gstin:
        payload["gstin"] = gstin
    path.write_text(json.dumps(payload), encoding="utf-8")
    return {"left_out": left_out.no, "changed": changed.no}


def test_gstr3b_vs_gstr2b(db, sample_files):
    from fintax_gst.services.return_compare import ReturnCompareService

    c, _i, _o = _full(db, sample_files)
    svc = ReturnCompareService(db)
    comp = svc.compare("3B_2B", c.id, "2025-26")
    assert comp.sides == ("GSTR-3B", "GSTR-2B") and len(comp.rows) == 12
    april = comp.rows[0]
    assert april.label == "Apr-2025" and april.status(*comp.sides) == "Difference"
    assert april.diff.total == D(2000) and april.diff.cgst == D(1000) and april.diff.sgst == D(1000)
    may = comp.rows[1]
    assert may.left is None and may.right is None and may.status(*comp.sides) == "Not imported"
    assert comp.difference.total == D(2000) and comp.months_with_difference == 1
    lines = {d.label[:8]: d for d in comp.details_for("2025-04")}
    assert lines["4(A)(5) "].diff.total == D(2000) and lines["4(A)(1) "].diff.total == 0
    assert any("exceeds GSTR-2B" in f.text and f.severity == "high" for f in comp.findings)
    assert any(f.period == "Year" and "₹2,000.00" in f.text for f in comp.findings)


def test_gstr1_vs_gstr3b(db, sample_files):
    from fintax_gst.samples_outward import SHORT_PAID_3B
    from fintax_gst.services.return_compare import ReturnCompareService

    c, _i, _o = _full(db, sample_files)
    comp = ReturnCompareService(db).compare("1_3B", c.id, "2025-26")
    april = comp.rows[0]
    assert april.left is not None and april.right is not None
    assert april.diff.total == SHORT_PAID_3B and april.status(*comp.sides) == "Difference"
    assert any("possible short payment" in f.text for f in comp.findings)
    assert any(f.period == "Year" and "DRC-03" in f.text for f in comp.findings)
    assert {d.label[:6] for d in comp.details_for("2025-04")} >= {"3.1(a)", "3.1(b)", "3.1(c)", "3.1(e)"}


def test_gstr2a_vs_gstr2b(db, sample_files, tmp_path):
    from fintax_gst.services.return_compare import (
        AMOUNT, MATCHED, ONLY_2A, ONLY_2B, ReturnCompareService,
    )

    c, _i, _o = _full(db, sample_files)
    info = write_gstr2a_json(tmp_path / "2a.json")
    ImportService(db).import_file(c.id, tmp_path / "2a.json", Source.GSTR2A)
    comp = ReturnCompareService(db).compare("2A_2B", c.id, "2025-26")
    counts = comp.doc_counts()
    by_no = {d.invoice_no: d for d in comp.docs}
    assert by_no["LATE-777"].status == ONLY_2A and "later months not imported" in by_no["LATE-777"].note
    assert by_no[info["changed"]].status == AMOUNT and by_no[info["changed"]].diff == D(100)
    assert by_no[info["left_out"]].status == ONLY_2B and counts[MATCHED] >= 2
    assert comp.rows[0].left is not None and comp.rows[0].right is not None and comp.rows[1].left is None
    assert any("not in any GSTR-2B" in f.text for f in comp.findings)
    assert comp.details_for("2025-04")


def test_export_and_quarterly_groups(db, sample_files, tmp_path):
    from openpyxl import load_workbook

    from fintax_gst.services.return_compare import KINDS, ReturnCompareService

    c, _i, _o = _full(db, sample_files)
    svc = ReturnCompareService(db)
    out = svc.export_xlsx([svc.compare(k, c.id, "2025-26") for k in KINDS], tmp_path / "cmp.xlsx")
    wb = load_workbook(out)
    assert {"3B vs 2B", "1 vs 3B", "2A vs 2B", "3B vs 2B detail"} <= set(wb.sheetnames)
    ws = wb["3B vs 2B"]
    assert ws.cell(3, 1).value == "Apr-2025" and ws.cell(3, 2).value == "Difference"
    with pytest.raises(ServiceError):
        svc.compare("XX", c.id, "2025-26")
    q = ClientService(db).create(**{**CLIENT, "gstin": "27AAPFU0939F2ZU", "return_frequency": "Quarterly"})
    comp = svc.compare("3B_2B", q.id, "2025-26")
    assert len(comp.rows) == 4 and comp.rows[0].label == "Apr–Jun 2025" and comp.rows[0].period == "2025-06"
    assert "No GSTR-3B or GSTR-2B imported" in comp.notes[0]
    avail = svc.availability(c.id, "2025-26")
    assert avail.has("GSTR3B", "2025-04") and avail.has("GSTR2B", "2025-04") and not avail.has("GSTR2A", "2025-04")


def write_gstr3b_pdf(path: Path, gstin: str = CLIENT["gstin"]) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table
    from reportlab.lib.styles import getSampleStyleSheet

    st = getSampleStyleSheet()["Normal"]
    rows31 = [["Nature of Supplies", "Total Taxable value", "Integrated Tax", "Central Tax", "State/UT Tax", "Cess"],
              ["(a) Outward taxable supplies (other than zero rated, nil rated and exempted)", "1,00,000.00",
               "5,400.00", "3,600.00", "3,600.00", "0.00"],
              ["(b) Outward taxable supplies (zero rated)", "20,000.00", "0.00", "0.00", "0.00", "0.00"],
              ["(c) Other outward supplies (nil rated, exempted)", "5,000.00", "", "", "", ""],
              ["(d) Inward supplies (liable to reverse charge)", "2,000.00", "0.00", "180.00", "180.00", "0.00"],
              ["(e) Non-GST outward supplies", "0.00", "", "", "", ""]]
    rows4 = [["Details", "Integrated Tax", "Central Tax", "State/UT Tax", "Cess"],
             ["A. ITC Available (whether in full or part)", "", "", "", ""],
             ["(1) Import of goods", "1,800.00", "0.00", "0.00", "0.00"],
             ["(2) Import of services", "0.00", "0.00", "0.00", "0.00"],
             ["(3) Inward supplies liable to reverse charge (other than 1 & 2 above)", "0.00", "180.00", "180.00",
              "0.00"],
             ["(4) Inward supplies from ISD", "0.00", "900.00", "900.00", "0.00"],
             ["(5) All other ITC", "4,500.00", "2,250.50", "2,250.50", "0.00"],
             ["B. ITC Reversed", "", "", "", ""],
             ["(1) As per rules 38,42 & 43 of CGST Rules and section 17(5)", "0.00", "720.00", "720.00", "0.00"],
             ["(2) Others", "0.00", "0.00", "0.00", "0.00"],
             ["C. Net ITC available (A-B)", "6,300.00", "2,610.50", "2,610.50", "0.00"],
             ["D. Other Details", "", "", "", ""],
             ["(1) ITC reclaimed which was reversed under Table 4(B)(2) in earlier tax period", "0.00", "0.00",
              "0.00", "0.00"],
             ["(2) Ineligible ITC under section 16(4) & ITC restricted due to PoS rules", "0.00", "50.00", "50.00",
              "0.00"]]
    doc = SimpleDocTemplate(str(path), pagesize=A4)
    doc.build([Paragraph("Form GSTR-3B", st), Paragraph("[See rule 61(5)]", st),
               Paragraph("Year 2025-26 Period April", st), Paragraph(f"1. GSTIN {gstin}", st),
               Paragraph("2(a). Legal name of the registered person Shree Ganesh Traders", st), Spacer(1, 8),
               Paragraph("3.1 Details of Outward supplies and inward supplies liable to reverse charge", st),
               Table(rows31), Spacer(1, 8),
               Paragraph("3.2 Of the supplies shown in 3.1 (a) above, details of inter-state supplies", st),
               Spacer(1, 8), Paragraph("4. Eligible ITC", st), Table(rows4), Spacer(1, 8),
               Paragraph("5. Values of exempt, nil-rated and non-GST inward supplies", st)])


def test_gstr3b_pdf_is_read(tmp_path):
    from fintax_gst.importers.gstr3b import preview_gstr3b
    from fintax_gst.services.portal import recognise

    write_gstr3b_pdf(tmp_path / "GSTR3B.pdf")
    pv = preview_gstr3b(tmp_path / "GSTR3B.pdf")
    assert pv.periods == ["2025-04"] and pv.layout == "GSTR-3B filed return (PDF)"
    t = pv.entries["2025-04"]
    assert t["31A"].taxable == D("100000") and t["31A"].igst == D("5400") and t["31A"].cgst == D("3600")
    assert t["31B"].taxable == D("20000") and t["31C"].taxable == D("5000") and t["31C"].total == 0
    assert t["4A1"].igst == D("1800") and t["4A4"].cgst == D("900") and t["4A5"].cgst == D("2250.50")
    assert t["4B1"].sgst == D("720") and t["4C"].igst == D("6300") and t["4D2"].cgst == D("50")
    assert not any("expected" in w for w in pv.warnings), pv.warnings
    kind, seen, period = recognise(tmp_path / "GSTR3B.pdf")
    assert kind == "GSTR3B" and CLIENT["gstin"] in seen and period == "2025-04"
    other = tmp_path / "bill.pdf"
    from reportlab.pdfgen import canvas

    cv = canvas.Canvas(str(other))
    cv.drawString(50, 800, "Tax invoice no 12 dated 01-04-2025")
    cv.save()
    assert recognise(other)[0] is None


def test_import_portal_files(db, sample_files, tmp_path):
    from fintax_gst.services.gstr3b import Gstr3bService
    from fintax_gst.services.return_compare import ReturnCompareService

    c = ClientService(db).create(**CLIENT)
    other = ClientService(db).create(**{**CLIENT, "name": "Other", "gstin": "27AAPFU0939F2ZU"})
    svc = ReturnCompareService(db)
    write_gstr3b_pdf(tmp_path / "GSTR3B_april.pdf")
    write_gstr2a_json(tmp_path / "gstr2a_no_gstin.json", gstin=None)
    write_gstr2a_json(tmp_path / "gstr2a_other.json", gstin=other.gstin)
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    res = svc.import_portal_files(c.id, [sample_files["gstr2b_april_json"], tmp_path / "GSTR3B_april.pdf",
                                         tmp_path / "gstr2a_no_gstin.json", tmp_path / "gstr2a_other.json",
                                         tmp_path / "notes.txt"], "accountant")
    ok = {name: (saved, msg) for name, saved, msg in res}
    assert ok[sample_files["gstr2b_april_json"].name][0]
    assert ok["GSTR3B_april.pdf"][0] and "2025-04" in ok["GSTR3B_april.pdf"][1]
    assert ok["gstr2a_no_gstin.json"][0]
    assert ok["gstr2a_other.json"][0] and "for Other" in ok["gstr2a_other.json"][1]
    assert not ok["notes.txt"][0]
    again = svc.import_portal_files(c.id, [tmp_path / "GSTR3B_april.pdf"])
    assert not again[0][1] and "Already imported" in again[0][2]
    assert Gstr3bService(db).values(c.id, ["2025-04"])["2025-04"]["4A5"].igst == D("4500")
    avail = svc.availability(c.id, "2025-26")
    assert avail.has("GSTR2A", "2025-04") and avail.has("GSTR2B", "2025-04") and avail.has("GSTR3B", "2025-04")
    assert svc.availability(other.id, "2025-26").has("GSTR2A", "2025-04")
    assert svc.downloads(c.id, tmp_path) == []  # everything there is imported already
