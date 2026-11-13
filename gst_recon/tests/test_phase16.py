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


# ------------------------------------------------------------------ e-invoice / e-way bill (16B)
KA_C, MH_C = gstin("29", "AACCV5566C"), gstin("27", "AABCR1122A")
SALES = ("GSTIN,Customer Name,Invoice No,Invoice Date,HSN,Quantity,UQC,Taxable Value,IGST,CGST,SGST,Place of Supply,"
         "Type of Supply\n"
         f"{KA_C},Venkatesh Traders,S/1,03-04-2025,7318,100,KGS,60000,10800,0,0,29,Regular\n"
         f"{MH_C},Rajlaxmi Retail,S/2,04-04-2025,7318,10,KGS,40000,0,3600,3600,27,Regular\n"
         ",Cash sales,CS/1,05-04-2025,7318,1,KGS,80000,0,7200,7200,27,Regular\n"
         f"{KA_C},Venkatesh Traders,S/3,06-04-2025,998314,1,OTH,90000,16200,0,0,29,Regular\n"
         f"{KA_C},Venkatesh Traders,S/4,07-04-2025,,,,1000,180,0,0,29,Regular\n"
         ",Gulf Imports,E/1,08-04-2025,7326,5,NOS,250000,0,0,0,96,Export (LUT)\n")


def _setup(db, tmp_path):
    from fintax_gst.services.einvoice_files import EInvoiceFileService

    c = ClientService(db).create(**CLIENT)
    sales = tmp_path / "sales.csv"
    sales.write_text(SALES)
    ImportService(db).import_file(c.id, sales, Source.SALES)
    parties = tmp_path / "parties.csv"
    parties.write_text("Name,GSTIN/UIN,Address,City,Pincode,State\n"
                       f"Venkatesh Traders,{KA_C},12 MG Road,Bengaluru,560001,Karnataka\n"
                       "Cash sales,,Market Yard,Pune,411037,Maharashtra\n"
                       "Bad Party,,Somewhere,X,12345,Goa\n")
    svc = EInvoiceFileService(db)
    saved, problems = svc.import_parties(c.id, parties, "accountant")
    assert saved == 2 and "6 digits" in problems[0]
    return c, svc


def test_einvoice_file(db, tmp_path):
    c, svc = _setup(db, tmp_path)
    assert svc.seller(c.id).pin == "411037" and svc.seller(c.id).place == "Pune"  # from the client's address
    e = svc.einvoices(c.id, "2025-04")
    by_no = {d["DocDtls"]["No"]: d for d in e.payload}
    assert set(by_no) == {"S/1", "S/3", "E/1"}  # B2C needs none; S/2 lacks an address; S/4 lacks HSN
    s1 = by_no["S/1"]
    assert s1["DocDtls"]["Dt"] == "03/04/2025" and s1["BuyerDtls"]["Pin"] == 560001 and s1["BuyerDtls"]["Pos"] == "29"
    assert s1["ItemList"][0] | {} == {**s1["ItemList"][0], "GstRt": 18.0, "IgstAmt": 10800.0, "UnitPrice": 600.0}
    assert by_no["S/3"]["ItemList"][0]["IsServc"] == "Y"
    exp = by_no["E/1"]
    assert exp["TranDtls"]["SupTyp"] == "EXPWOP" and exp["BuyerDtls"]["Gstin"] == "URP" and exp["BuyerDtls"]["Pos"] == "96"
    left = {i.doc.number: i.message for i in e.issues if i.severity == "error"}
    assert "address" in left["S/2"] and "HSN" in left["S/4"]
    out = svc.save(c.id, "einvoice_json", e, tmp_path / "einv.json", "accountant")
    assert out.exists()


def test_ewaybill_file(db, tmp_path):
    from fintax_gst.outward.einvoice_ewb import Transport

    c, svc = _setup(db, tmp_path)
    w = svc.ewaybills(c.id, "2025-04")
    bills = {b["docNo"]: b for b in w.payload["billLists"]}
    # S/1 goods above 50,000; CS/1 B2C goods above 50,000 (cash customer in the book); S/2 below the limit;
    # S/3 is a service; E/1 export without a dispatch address in the book -> left out
    assert set(bills) == {"S/1", "CS/1"}
    assert bills["CS/1"]["toGstin"] == "URP" and bills["S/1"]["igstValue"] == 10800.0
    assert bills["S/1"]["itemList"][0]["igstRate"] == 18.0 and bills["S/1"]["transDistance"] == "0"
    assert any("Part A" in i.message for i in w.issues)  # no vehicle / transporter
    assert any(i.doc and i.doc.number == "E/1" for i in w.issues)
    w2 = svc.ewaybills(c.id, "2025-04", Transport(vehicle_no="MH12AB1234"))
    assert all(b["vehicleNo"] == "MH12AB1234" for b in w2.payload["billLists"])
    assert not any("Part A" in i.message for i in w2.issues)
    svc.save_seller(c.id, "Plot 4, MIDC", "Chakan", "410501", "accountant")
    assert svc.ewaybills(c.id, "2025-04").payload["billLists"][0]["fromPincode"] == 410501
    with pytest.raises(ServiceError, match="6 digits"):
        svc.save_seller(c.id, "x", "y", "123")


# ------------------------------------------------------------------ TallyPrime statutory reports (17B)
def _offline_gstr1(path):
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)

    def sheet(name, headers, *rows):
        ws = wb.create_sheet(name)
        ws.append(["Summary For B2B"])  # the offline tool's three summary rows above the headings
        ws.append([])
        ws.append([])
        ws.append(headers)
        for r in rows:
            ws.append(r)

    ka, mh = gstin("29", "AACCV5566C"), gstin("27", "AABCR1122A")
    sheet("b2b,sez,de", ["GSTIN/UIN of Recipient", "Receiver Name", "Invoice Number", "Invoice date", "Invoice Value",
                         "Place Of Supply", "Reverse Charge", "Applicable % of Tax Rate", "Invoice Type",
                         "E-Commerce GSTIN", "Rate", "Taxable Value", "Cess Amount"],
          [ka, "Venkatesh", "S/1", "03-Apr-2025", 70800, "29-Karnataka", "N", None, "Regular B2B", None, 18, 60000, 0],
          [mh, "Rajlaxmi", "S/2", "04-Apr-2025", 17400, "27-Maharashtra", "N", None, "Regular B2B", None, 18, 10000, 0],
          [mh, "Rajlaxmi", "S/2", "04-Apr-2025", 17400, "27-Maharashtra", "N", None, "Regular B2B", None, 12, 5000, 0],
          [ka, "Venkatesh", "S/3", "05-Apr-2025", 5000, "29-Karnataka", "N", None, "SEZ supplies without payment",
           None, 0, 5000, 0])
    sheet("b2cl", ["Invoice Number", "Invoice date", "Invoice Value", "Place Of Supply", "Applicable % of Tax Rate",
                   "Rate", "Taxable Value", "Cess Amount", "E-Commerce GSTIN"],
          ["L/1", "06-Apr-2025", 141600, "29-Karnataka", None, 18, 120000, 0, None])
    sheet("b2cs", ["Type", "Place Of Supply", "Applicable % of Tax Rate", "Rate", "Taxable Value", "Cess Amount",
                   "E-Commerce GSTIN"], ["OE", "27-Maharashtra", None, 18, 41000, 0, None])
    sheet("cdnr", ["GSTIN/UIN of Recipient", "Receiver Name", "Note Number", "Note Date", "Note Type",
                   "Place Of Supply", "Reverse Charge", "Note Supply Type", "Note Value", "Applicable % of Tax Rate",
                   "Rate", "Taxable Value", "Cess Amount"],
          [mh, "Rajlaxmi", "CN/1", "20-Apr-2025", "C", "27-Maharashtra", "N", "Regular", 1180, None, 18, 1000, 0])
    sheet("exp", ["Export Type", "Invoice Number", "Invoice date", "Invoice Value", "Port Code",
                  "Shipping Bill Number", "Shipping Bill Date", "Rate", "Taxable Value", "Cess Amount"],
          ["WOPAY", "E/1", "24-Apr-2025", 250000, "INNSA1", "123", "25-Apr-2025", 0, 250000, 0])
    sheet("exemp", ["Description", "Nil Rated Supplies", "Exempted(other than nil rated/non GST supply)",
                    "Non-GST Supplies"],
          ["Intra-State supplies to registered persons", 0, 12000, 0])
    wb.save(path)
    return path


def test_tally_gstr1_report(db, tmp_path):
    from fintax_gst.services.tally_statutory import TallyStatutoryService

    c = ClientService(db).create(**CLIENT)
    svc = TallyStatutoryService(db)
    pv = svc.preview(c.id, _offline_gstr1(tmp_path / "GSTR1_Apr.xlsx"), "gstr1", "2025-04")
    docs = {r.invoice_no: r for r in pv.records}
    assert pv.source == Source.SALES and pv.file_name == "GSTR1_Apr.xlsx" and pv.layout == "tally_gstr1"
    s1, s2 = docs["S/1"], docs["S/2"]
    assert (s1.igst, s1.cgst) == (D("10800.00"), D(0))  # Karnataka customer: IGST worked out from rate
    assert (s2.taxable, s2.cgst, s2.sgst) == (D("15000"), D("1200.00"), D("1200.00"))  # two rates, one invoice
    assert docs["S/3"].supply_type == "SEZ without payment" and docs["L/1"].igst == D("21600.00")
    assert docs["CN/1"].doc_type.value == "CRN" and docs["E/1"].supply_type == "Export (LUT)"
    assert docs["B2CS 27-18%"].cgst == D("3690.00") and docs["B2CS 27-18%"].supplier_gstin == ""
    assert any(r.supply_type == "Exempt" and r.taxable == D("12000") for r in pv.records)
    sf = ImportService(db).commit(c.id, pv, "accountant")
    assert sf.file_name == "GSTR1_Apr.xlsx" and sf.source_type == "SALES"
    with pytest.raises(ServiceError):  # the same report again
        ImportService(db).commit(c.id, svc.preview(c.id, tmp_path / "GSTR1_Apr.xlsx", "gstr1", "2025-04"))
    # the GSTR-1 file made from it reads back the same B2B documents (JSON export of Tally = portal layout)
    from fintax_gst.services.gstr1_prep import Gstr1PrepService
    import json as _json

    draft = Gstr1PrepService(db).draft(c.id, "2025-04")
    # S/2 has items at two rates and no HSN lines: its rate-wise split is unknown, so it is left out, not guessed
    assert any(i.doc and i.doc.number == "S/2" and "not a GST rate" in i.message for i in draft.issues)
    out = Gstr1PrepService(db).save(c.id, draft, tmp_path / "g1.json")
    c2 = ClientService(db).create(gstin("27", "AAPFU0940F"), None, name="Second")
    pv2 = svc.preview(c2.id, out, "gstr1", "2025-04")
    assert {r.invoice_no for r in pv2.records if r.supplier_gstin} == {"S/1", "S/3", "CN/1"}
    assert _json.loads(out.read_text())["fp"] == "042025"
    with pytest.raises(ServiceError, match="month"):
        svc.preview(c.id, out, "gstr1")


def test_tally_reconciliation_and_3b_reports(db, tmp_path, sample_files):
    from openpyxl import Workbook

    from fintax_gst.services.tally_statutory import TallyStatutoryService

    c = ClientService(db).create(**CLIENT)
    svc = TallyStatutoryService(db)
    wb = Workbook()
    ws = wb.active
    ws.append(["Shree Ganesh Traders"])
    ws.append(["GSTR-2B Reconciliation"])
    ws.append(["Party Name", "GSTIN/UIN", "Supplier Invoice No", "Invoice Date", "Taxable Value", "CGST", "SGST",
               "Status"])
    ws.append(["Mahalaxmi", MH, "A-1", "02-04-2025", 1000, 90, 90, "Matched"])
    ws.append(["Mahalaxmi", MH, "A-2", "03-04-2025", 2000, 180, 180, "Not available in portal"])
    ws.append(["Pune Packaging", gstin("27", "AAFFP4321M"), "P-9", "05-04-2025", 500, 45, 45,
               "Available only in GSTR-2B"])
    wb.save(tmp_path / "recon.xlsx")
    pv = svc.preview(c.id, tmp_path / "recon.xlsx", "recon")
    assert pv.source == Source.BOOKS and sorted(r.invoice_no for r in pv.records) == ["A-1", "A-2"]
    assert any(i.severity == "ignored" and "portal only" in i.message for i in pv.issues)
    sf, periods = svc.import_gstr3b(c.id, sample_files["gstr3b_april_json"], user="accountant")
    assert periods == ["2025-04"] and sf.source_type == "TALLY3B"
    books = svc.books_3b(c.id, "2025-04")
    assert books["4A5"].total > 0
    from fintax_gst.services.gstr3b import Gstr3bService

    assert Gstr3bService(db).values(c.id, ["2025-04"]) == {}  # never mixed with the GSTR-3B filed on the portal
    with pytest.raises(ServiceError, match="already imported"):
        svc.import_gstr3b(c.id, sample_files["gstr3b_april_json"])


# ------------------------------------------------------------------ GST portal section (17C)
def _cash_ledger(path, rows, gstin_text=CLIENT["gstin"]):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Cash Ledger"
    ws.append(["Electronic Cash Ledger"])
    ws.append(["GSTIN", gstin_text])
    ws.append(["Sr.No.", "Date of Deposit/Debit", "Reference No.", "Tax Period", "Description",
               "Type of Transaction", "Amount debited/credited", None, None, None, None, None, None, None,
               "Balance", None, None, None])
    ws.append([None] * 6 + ["IGST", None, "CGST", None, "SGST", None, "Cess", None, "IGST", "CGST", "SGST", "Cess"])
    ws.append([None] * 6 + ["Tax", "Total", "Tax", "Total", "Tax", "Total", "Tax", "Total"])
    for r in rows:
        ws.append(r)
    wb.save(path)


def test_portal_recognises_downloads_and_ledgers(db, tmp_path, sample_files):
    import shutil

    from fintax_gst.services.portal import PortalService, recognise

    c = ClientService(db).create(**CLIENT)
    dl = tmp_path / "Downloads"
    dl.mkdir()
    for key in ("gstr2b_april_json", "gstr3b_april_json", "ims_april_json"):
        shutil.copy(sample_files[key], dl / sample_files[key].name)
    (dl / "notes.txt").write_text("x")
    (dl / "random.json").write_text('{"a": 1}')
    opening = ["", "01-04-2025", "", "", "Opening Balance", "", 0, 0, 0, 0, 0, 0, 0, 0, 100, 200, 200, 0]
    dep = ["1", "05-04-2025", "CPIN123", "Apr-25", "Deposit", "Credit", 1000, 1000, 500, 500, 500, 500, 0, 0,
           1100, 700, 700, 0]
    pay = ["2", "20-04-2025", "DC27", "Mar-25", "Payment towards liability", "Debit", 0, 0, 400, 400, 400, 400, 0,
           0, 1100, 300, 300, 0]
    _cash_ledger(dl / "cash_ledger_q1.xlsx", [opening, dep, pay])
    svc = PortalService(db)
    found = {f.path.name: f for f in svc.scan(dl, current_client_id=c.id)}
    assert set(found) == {"gstr2b_2025-04.json", "gstr3b_2025-04.json", "ims_2025-04.json", "cash_ledger_q1.xlsx"}
    g2b = found["gstr2b_2025-04.json"]
    assert g2b.kind == "GSTR2B" and g2b.client_id == c.id and g2b.period == "2025-04" and g2b.ready
    cash = found["cash_ledger_q1.xlsx"]
    assert cash.kind == "CASH" and cash.client_id == c.id
    assert "line(s) saved" in svc.import_file(cash, "accountant")
    rows = svc.ledger_rows(c.id, "CASH")
    assert [r.txn for r in rows] == ["BAL", "CR", "DR"] and rows[2].cgst == D("-400")
    as_on, bal = svc.balances(c.id)["CASH"]
    assert as_on == date(2025, 4, 20) and bal == {"igst": D(1100), "cgst": D(300), "sgst": D(300), "cess": D(0)}
    # an overlapping later download adds only the new lines
    more = ["3", "02-05-2025", "CPIN999", "May-25", "Deposit", "Credit", 0, 0, 100, 100, 100, 100, 0, 0,
            1100, 400, 400, 0]
    _cash_ledger(dl / "cash_ledger_q1b.xlsx", [opening, dep, pay, more])
    _sf, _led, repeated = svc.import_ledger(c.id, dl / "cash_ledger_q1b.xlsx", user="accountant")
    assert repeated == 3 and len(svc.ledger_rows(c.id, "CASH")) == 4
    assert svc.balances(c.id)["CASH"][1]["cgst"] == D(400)
    assert svc.inspect(dl / "cash_ledger_q1.xlsx", c.id).status.startswith("Already imported")
    assert "2025-04" in svc.import_file(found["gstr3b_2025-04.json"])
    assert "document(s) saved" in svc.import_file(g2b)
    assert recognise(dl / "random.json")[0] is None
    # a file for a GSTIN that is not a client is listed but cannot be imported
    _cash_ledger(dl / "other.xlsx", [dep], gstin_text=gstin("29", "AACCV5566C"))
    other = svc.inspect(dl / "other.xlsx", c.id)
    assert other.client_id is None and "No client with GSTIN" in other.status
    with pytest.raises(ServiceError):
        svc.import_file(other)
    # removing the import removes its ledger lines
    ImportService(db).remove_import(c.id, _sf.id, user="admin")
    assert len(svc.ledger_rows(c.id, "CASH")) == 3


# ------------------------------------------------------------------ GSTR-9 / 9C import (17E)
def test_gstr9_and_9c_import_compare(db, sample_files, tmp_path):
    import json

    from openpyxl import Workbook

    from fintax_gst.services.annual_import import AnnualImportService
    from fintax_gst.services.auth import SETUP_SESSION
    from fintax_gst.services.gstr3b import Gstr3bService
    from fintax_gst.services.gstr9 import Gstr9Service
    from fintax_gst.services.gstr9c import Gstr9cService

    c = ClientService(db).create(**CLIENT)
    svc = ImportService(db)
    for key, src in (("sales_april", Source.SALES), ("gstr1_april_json", Source.GSTR1),
                     ("books_april", Source.BOOKS), ("gstr2b_april_json", Source.GSTR2B)):
        svc.import_file(c.id, sample_files[key], src)
    Gstr3bService(db).import_file(c.id, sample_files["gstr3b_april_json"])
    js, _mp = Gstr9Service(db).draft_json(c.id, "2025-26", tmp_path)
    data = json.loads(js.read_text(encoding="utf-8"))
    data["table4"]["b2b"]["camt"] += 100  # the filed return differs in one place
    js.write_text(json.dumps(data), encoding="utf-8")
    ann = AnnualImportService(db)
    af = ann.save(c.id, "2025-26", js, "GSTR9", user="accountant")
    assert af.values["4B"].taxable > 0
    rows = {r.code: r for r in ann.compare_9(c.id, "2025-26")}
    assert rows["4B"].diff == D(100)
    assert all(r.diff == 0 for code, r in rows.items() if code != "4B" and r.file_tax is not None
               and r.ours_tax is not None)
    with pytest.raises(ServiceError, match="not 2024-25"):
        ann.save(c.id, "2024-25", js, "GSTR9")
    # GSTR-9C offline-tool style sheet: row letters under the table heading
    wb = Workbook()
    ws = wb.active
    ws.title = "Pt. II 5,6"
    ws.append(["Pt. II", "Reconciliation of turnover declared in audited Annual Financial Statement"])
    ws.append(["5", "Reconciliation of Gross Turnover"])
    ws.append([None, "Description", "Amount (₹)"])
    ws.append(["A", "Turnover (including exports) as per audited financial statements", 1250000])
    ws.append(["B", "Unbilled revenue at the beginning of Financial Year", 15000])
    ws.append(["H", "Unbilled revenue at the end of Financial Year", 5000])
    ws2 = wb.create_sheet("Pt. III 12")
    ws2.append(["12", "Reconciliation of Net Input Tax Credit"])
    ws2.append([None, "Description", "Amount (₹)"])
    ws2.append(["A", "ITC availed as per audited Annual Financial Statement", 41000])
    wb.save(tmp_path / "gstr9c.xlsx")
    af9c = ann.save(c.id, "2025-26", tmp_path / "gstr9c.xlsx", "GSTR9C", user="accountant")
    assert af9c.amounts == {"5A": D(1250000), "5B": D(15000), "5H": D(5000), "12A": D(41000)}
    cmp9c = {r.code: r for r in ann.compare_9c(c.id, "2025-26")}
    assert cmp9c["5A"].file_tax == D(1250000) and cmp9c["5A"].ours_tax != D(1250000)
    assert ann.use_9c_amounts(c.id, "2025-26", SETUP_SESSION) == 4
    assert Gstr9cService(db).inputs(c.id, "2025-26")["5A"][0] == D(1250000)
    assert all(r.diff == 0 for r in ann.compare_9c(c.id, "2025-26") if r.code in ("5A", "12A"))
    # a plain CSV template: Table, Taxable value, IGST, CGST, SGST, Cess
    (tmp_path / "g9.csv").write_text("Table,Taxable value,Integrated Tax,Central Tax,State Tax,Cess\n"
                                     "4B,1000,0,90,90,0\n6B,,10,20,20,0\n", encoding="utf-8")
    csv9 = ann.read(tmp_path / "g9.csv", "GSTR9")
    assert csv9.values["4B"].cgst == D(90) and csv9.values["6B"].igst == D(10)
