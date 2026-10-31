"""Phase 14: tax type / rate checks, journal and payment registers, 180-day tracker, PAN view, Tally journals."""
from datetime import date
from decimal import Decimal as D

import pytest

from fintax_gst.compliance.tax_checks import Doc, check, fits_rate, pos_code
from fintax_gst.core.models import Source
from fintax_gst.samples import CLIENT, gstin
from fintax_gst.services.clients import ClientService
from fintax_gst.services.common import ServiceError
from fintax_gst.services.imports import ImportService

MH, KA = gstin("27", "AABCM1234K"), gstin("29", "AACCB5678L")


def _doc(source="BOOKS", g=MH, taxable="1000", igst="0", cgst="0", sgst="0", **kw):
    return Doc(1, source, g, "Party", "INV-1", date(2025, 4, 2), D(taxable), D(igst), D(cgst), D(sgst), **kw)


# ------------------------------------------------------------------ tax type and rate checks (14A)
def test_place_of_supply_and_rates():
    assert [pos_code(x) for x in ("27", "27-Maharashtra", "Karnataka (29)", "tamil nadu", "Orissa", "", "x")] == \
        ["27", "27", "29", "33", "21", None, None]
    assert fits_rate(D("1000"), D("180"), D(0), D(0)) == D("18")
    assert fits_rate(D("1000"), D(0), D("90"), D("90.40")) == D("18")  # rounding
    assert fits_rate(D("1000"), D("400"), D(0), D(0)) == D("40")  # GST 2.0 rate from 22-09-2025
    assert fits_rate(D("1000"), D("150"), D(0), D(0)) is None
    assert fits_rate(D("1000"), D(0), D(0), D(0)) is not None  # nil / exempt: nothing to check


@pytest.mark.parametrize("doc, kinds", [
    (_doc(cgst="90", sgst="90"), []),  # Maharashtra supplier, CGST + SGST: right
    (_doc(igst="180"), ["tax_type"]),  # same state, IGST charged
    (_doc(g=KA, igst="180"), []),  # inter-state, IGST: right
    (_doc(g=KA, cgst="90", sgst="90", place_of_supply="27-Maharashtra"), ["tax_type"]),
    (_doc(g=KA, cgst="90", sgst="90"), ["other_state"]),  # no place of supply: hotel there, or wrong head
    (_doc(g=KA, cgst="90", sgst="90", place_of_supply="Karnataka"), ["other_state"]),
    (_doc(g=KA, cgst="90", sgst="90", reverse_charge=True), []),
    (_doc(igst="100", cgst="40", sgst="40"), ["tax_type"]),  # IGST and CGST/SGST on one document
    (_doc(cgst="75", sgst="75"), ["rate"]),  # 15 %: no such rate
    (_doc(cgst="57.50", sgst="57.50"), ["rate"]),  # 11.5 %: two rates combined, or an error
    (_doc(cgst="57.50", sgst="57.50", lines=((D(500), D(0), D("12.50"), D("12.50")),
                                             (D(500), D(0), D(45), D(45)))), []),  # 5 % + 18 % lines: right
    (_doc("SALES", g=KA, cgst="90", sgst="90"), ["tax_type"]),  # customer in another state
    (_doc("SALES", g="", cgst="90", sgst="90"), []),  # local B2C
    (_doc("SALES", g="", igst="180", place_of_supply="29-Karnataka"), []),
    (_doc("SALES", g="", cgst="90", sgst="90", supply_type="Export (LUT)"), ["tax_type"]),
    (_doc("SALES", g=MH, igst="180"), ["tax_type"]),
])
def test_tax_checks(doc, kinds):
    assert [i.kind for i in check(doc, "27")] == kinds


def test_tax_check_service(db, tmp_path):
    from openpyxl import load_workbook

    from fintax_gst.services.tax_checks import TaxCheckService

    c = ClientService(db).create(**CLIENT)
    reg = tmp_path / "purchases.csv"
    reg.write_text("GSTIN,Invoice No,Invoice Date,Taxable Value,IGST,CGST,SGST,Place of Supply\n"
                   f"{MH},OK-1,02-04-2025,1000,0,90,90,Maharashtra\n"
                   f"{MH},IG-1,03-04-2025,1000,180,0,0,Maharashtra\n"
                   f"{KA},HOT-1,04-04-2025,2000,0,180,180,\n"
                   f"{MH},RT-1,05-04-2025,1000,0,75,75,\n")
    ImportService(db).import_file(c.id, reg, Source.BOOKS)
    issues = TaxCheckService(db).check(c.id, "2025-04")
    assert [(i.doc.invoice_no, i.kind) for i in issues] == [("IG-1", "tax_type"), ("HOT-1", "other_state"),
                                                             ("RT-1", "rate")]
    out = TaxCheckService.export_xlsx(issues, tmp_path / "t.xlsx", "April")
    assert load_workbook(out)["Tax checks"].max_row == 5
    assert TaxCheckService(db).check(c.id, "2025-05") == []
    with pytest.raises(ServiceError):
        TaxCheckService(db).check(c.id, "April")


def test_cli_tax_check(tmp_path, capsys):
    from fintax_gst.cli import main

    dbp = str(tmp_path / "cli.db")
    reg = tmp_path / "p.csv"
    reg.write_text(f"GSTIN,Invoice No,Invoice Date,Taxable Value,IGST\n{MH},IG-1,03-04-2025,1000,180\n")
    assert main(["--db", dbp, "client", "add", "--name", CLIENT["name"], "--gstin", CLIENT["gstin"]]) == 0
    assert main(["--db", dbp, "import", "--client", CLIENT["gstin"], "--source", "books", "--file", str(reg)]) == 0
    capsys.readouterr()
    assert main(["--db", dbp, "tax-check", "--client", CLIENT["gstin"], "--from", "2025-04"]) == 0
    out = capsys.readouterr().out
    assert "Wrong tax type" in out and "IG-1" in out and "1 finding(s)" in out


# ------------------------------------------------------------------ journal register (14B)
def test_journal_register_excel(db, sample_files):
    from fintax_gst.importers.pipeline import preview_file

    pv = preview_file(sample_files["journal_april"], Source.BOOKS)
    assert pv.layout == "tally"
    assert [(r.invoice_no, r.taxable, r.cgst, r.igst) for r in pv.records] == [
        ("SP/RENT/04", D("50000"), D("4500"), D(0)), ("VA/25-26/017", D("20000"), D(0), D("3600"))]
    ignored = {i.row: i.message for i in pv.issues if i.severity == "ignored"}
    assert "depreciation" in ignored["8"] and "ITC reversal" in ignored["9"] and "TDS" in ignored["10"]
    assert not [i for i in pv.issues if i.severity == "error"]  # non-bill journals are never errors
    c = ClientService(db).create(**CLIENT)
    sf, _ = ImportService(db).import_file(c.id, sample_files["journal_april"], Source.BOOKS)
    assert sf.documents_imported == 2 and sf.rows_rejected == 0


def test_journal_vouchers_from_tally_xml():
    from fintax_gst.importers.tally_xml import flatten_vouchers, parse_xml

    xml = f"""<ENVELOPE><BODY><DATA>
      <VOUCHER><DATE>20250405</DATE><VOUCHERTYPENAME>Journal</VOUCHERTYPENAME><VOUCHERNUMBER>101</VOUCHERNUMBER>
        <REFERENCE>SP/RENT/04</REFERENCE><REFERENCEDATE>20250401</REFERENCEDATE><PARTYGSTIN>{MH}</PARTYGSTIN>
        <ALLLEDGERENTRIES.LIST><LEDGERNAME>Rent</LEDGERNAME><AMOUNT>-50000</AMOUNT></ALLLEDGERENTRIES.LIST>
        <ALLLEDGERENTRIES.LIST><LEDGERNAME>Input CGST</LEDGERNAME><AMOUNT>-4500</AMOUNT></ALLLEDGERENTRIES.LIST>
        <ALLLEDGERENTRIES.LIST><LEDGERNAME>Input SGST</LEDGERNAME><AMOUNT>-4500</AMOUNT></ALLLEDGERENTRIES.LIST>
        <ALLLEDGERENTRIES.LIST><LEDGERNAME>Shree Properties</LEDGERNAME><AMOUNT>59000</AMOUNT>
        </ALLLEDGERENTRIES.LIST></VOUCHER>
      <VOUCHER><DATE>20250430</DATE><VOUCHERTYPENAME>Journal</VOUCHERTYPENAME><VOUCHERNUMBER>103</VOUCHERNUMBER>
        <ALLLEDGERENTRIES.LIST><LEDGERNAME>Depreciation</LEDGERNAME><AMOUNT>-15000</AMOUNT></ALLLEDGERENTRIES.LIST>
        <ALLLEDGERENTRIES.LIST><LEDGERNAME>Machinery</LEDGERNAME><AMOUNT>15000</AMOUNT></ALLLEDGERENTRIES.LIST>
      </VOUCHER>
      <VOUCHER><DATE>20250430</DATE><VOUCHERTYPENAME>Journal</VOUCHERTYPENAME><VOUCHERNUMBER>104</VOUCHERNUMBER>
        <ALLLEDGERENTRIES.LIST><LEDGERNAME>Input CGST</LEDGERNAME><AMOUNT>1200</AMOUNT></ALLLEDGERENTRIES.LIST>
        <ALLLEDGERENTRIES.LIST><LEDGERNAME>Input SGST</LEDGERNAME><AMOUNT>1200</AMOUNT></ALLLEDGERENTRIES.LIST>
        <ALLLEDGERENTRIES.LIST><LEDGERNAME>ITC reversed</LEDGERNAME><AMOUNT>-2400</AMOUNT></ALLLEDGERENTRIES.LIST>
      </VOUCHER>
      <VOUCHER><DATE>20250415</DATE><VOUCHERTYPENAME>Journal</VOUCHERTYPENAME><VOUCHERNUMBER>106</VOUCHERNUMBER>
        <ALLLEDGERENTRIES.LIST><LEDGERNAME>Freight (RCM)</LEDGERNAME><AMOUNT>-1000</AMOUNT></ALLLEDGERENTRIES.LIST>
        <ALLLEDGERENTRIES.LIST><LEDGERNAME>Input IGST</LEDGERNAME><AMOUNT>-50</AMOUNT></ALLLEDGERENTRIES.LIST>
        <ALLLEDGERENTRIES.LIST><LEDGERNAME>Cash</LEDGERNAME><AMOUNT>1050</AMOUNT></ALLLEDGERENTRIES.LIST>
      </VOUCHER>
    </DATA></BODY></ENVELOPE>""".encode()
    found = flatten_vouchers(parse_xml(xml), "purchase")
    (row,) = found.rows
    assert (row["invoice_no"], row["supplier_name"], row["taxable_value"], row["cgst"], row["invoice_value"]) == \
        ("SP/RENT/04", "Shree Properties", "50000", "4500", "59000")
    reasons = dict(found.ignored)
    assert "without GST" in reasons["Journal 103"] and "ITC reversal" in reasons["Journal 104"]
    assert "without supplier GSTIN" in reasons["Journal 106"]
    assert flatten_vouchers(parse_xml(xml), "sales").rows == []  # journals never go to the sales register


# ------------------------------------------------------------------ payment register and 180-day rule (14C)
def _bills(db, tmp_path):
    """A small purchase register: three bills of one supplier and one of another (amounts incl. tax)."""
    c = ClientService(db).create(**CLIENT)
    reg = tmp_path / "bills.csv"
    reg.write_text("GSTIN,Supplier Name,Invoice No,Invoice Date,Taxable Value,CGST,SGST,Invoice Value\n"
                   f"{MH},Mahalaxmi Steel Pvt Ltd,A-1,01-04-2025,10000,900,900,11800\n"
                   f"{MH},Mahalaxmi Steel Pvt Ltd,A-2,15-04-2025,20000,1800,1800,23600\n"
                   f"{MH},Mahalaxmi Steel Pvt Ltd,A-3,20-04-2025,5000,450,450,5900\n"
                   f"{gstin('27', 'AAFFP4321M')},Pune Packaging Co,P-9,05-04-2025,1000,90,90,1180\n")
    ImportService(db).import_file(c.id, reg, Source.BOOKS)
    return c


def test_payment_register_reader(tmp_path, sample_files):
    from fintax_gst.importers.payments import party_key, read_payments
    from fintax_gst.importers.readers import UnsupportedFileError

    res = read_payments(sample_files["payments"])
    assert len(res.rows) == 4 and [r.bill_ref for r in res.rows][:2] == ["MSL/101/25-26", ""]
    assert dict(res.ignored) == {"10": "voucher type 'Contra' is not a payment", "11": "total / opening balance line"}
    assert party_key("M/s. Mahalaxmi Steel Pvt. Ltd.") == party_key("MAHALAXMI STEEL PRIVATE LIMITED") == \
        "mahalaxmisteel"
    xml = tmp_path / "pay.xml"
    xml.write_text("""<ENVELOPE><BODY><DATA>
      <VOUCHER><DATE>20250510</DATE><VOUCHERTYPENAME>Payment</VOUCHERTYPENAME><VOUCHERNUMBER>7</VOUCHERNUMBER>
        <ALLLEDGERENTRIES.LIST><LEDGERNAME>Mahalaxmi Steel Pvt Ltd</LEDGERNAME><AMOUNT>-15000</AMOUNT>
          <BILLALLOCATIONS.LIST><NAME>A-1</NAME><AMOUNT>-11800</AMOUNT></BILLALLOCATIONS.LIST>
          <BILLALLOCATIONS.LIST><NAME>A-2</NAME><AMOUNT>-3200</AMOUNT></BILLALLOCATIONS.LIST>
        </ALLLEDGERENTRIES.LIST>
        <ALLLEDGERENTRIES.LIST><LEDGERNAME>HDFC Bank</LEDGERNAME><AMOUNT>15000</AMOUNT></ALLLEDGERENTRIES.LIST>
      </VOUCHER>
      <VOUCHER><DATE>20250511</DATE><VOUCHERTYPENAME>Sales</VOUCHERTYPENAME></VOUCHER>
    </DATA></BODY></ENVELOPE>""")
    x = read_payments(xml)
    assert [(r.party, r.bill_ref, r.amount) for r in x.rows] == [("Mahalaxmi Steel Pvt Ltd", "A-1", D("11800")),
                                                                 ("Mahalaxmi Steel Pvt Ltd", "A-2", D("3200"))]
    bad = tmp_path / "x.csv"
    bad.write_text("Name,Value\nfoo,1\n")
    with pytest.raises(UnsupportedFileError, match="no payments found"):
        read_payments(bad)


def test_rule37_tracker(db, tmp_path):
    from fintax_gst.services.rule37 import Rule37Service

    c = _bills(db, tmp_path)
    pay = tmp_path / "payments.csv"
    pay.write_text("Date,Particulars,Vch Type,Agst Ref,Debit Amount\n"
                   "10-05-2025,M/s Mahalaxmi Steel Pvt. Ltd.,Payment,A-2,23600\n"  # A-2 by reference
                   "20-06-2025,Mahalaxmi Steel Private Limited,Payment,,5000\n"  # oldest open bill first: A-1
                   "15-11-2025,Mahalaxmi Steel Pvt Ltd,Payment,,6800\n"  # after day 180: rest of A-1 + 0 of A-3
                   "01-05-2025,Unknown Traders,Payment,,999\n")
    svc = Rule37Service(db)
    sf, result = svc.import_payments(c.id, pay, "accountant")
    assert len(result.rows) == 4 and result.total == D("36399")
    with pytest.raises(ServiceError, match="already imported"):
        svc.import_payments(c.id, pay)
    bills = {b.invoice_no: b for b in svc.track(c.id, as_of=date(2025, 12, 1))}
    a1, a2, a3, p9 = bills["A-1"], bills["A-2"], bills["A-3"], bills["P-9"]
    assert a2.status == "Paid in time" and a2.itc_to_reverse == 0
    assert a1.day180 == date(2025, 9, 28) and a1.unpaid_at_day180 == D("6800")  # 11800 - 5000 paid by day 180
    assert a1.status == "Paid late – re-claim" and a1.paid_in_full_on == date(2025, 11, 15)
    assert a1.itc_to_reverse == D("1037.29") and a1.reversal_period == "2025-10"  # 1800 x 6800 / 11800
    assert a1.itc_to_reclaim == D("1037.29") and a1.reclaim_period == "2025-11"
    assert a1.interest > 0
    assert a3.status == "Reverse ITC" and a3.itc_to_reverse == D("900.00") and a3.reversal_period == "2025-11"
    assert p9.status == "Reverse ITC" and p9.unpaid_at_day180 == D("1180")
    assert [p.party_name for p in svc.unmatched_payments(c.id)] == ["Unknown Traders"]
    # judged earlier, nothing is due yet
    assert {b.status for b in svc.track(c.id, as_of=date(2025, 6, 1))} == {"Paid in time", "Not yet due"}

    # pay P-9 by hand: it becomes 'paid late' with ITC to re-claim
    svc.mark_paid(c.id, p9.invoice_id, date(2025, 11, 20), note="UTR 123", user="accountant")
    p9b = next(b for b in svc.track(c.id, as_of=date(2025, 12, 1)) if b.invoice_no == "P-9")
    assert p9b.status == "Paid late – re-claim" and p9b.itc_to_reclaim == D("180.00")
    with pytest.raises(ServiceError, match="Nothing unpaid"):
        svc.mark_paid(c.id, p9.invoice_id, date(2025, 11, 21))
    out = svc.export_xlsx(list(bills.values()), tmp_path / "r37.xlsx")
    assert out.exists()

    # removing the payment register removes its payments (the hand-marked one stays)
    ImportService(db).remove_import(c.id, sf.id)
    left = {b.invoice_no: b.status for b in svc.track(c.id, as_of=date(2025, 12, 1))}
    assert left["A-2"] == "Reverse ITC" and left["P-9"] == "Paid late – re-claim"


def test_rule37_reversal_in_claim_register(db, tmp_path):
    from fintax_gst.db.models import Invoice, ItcClaim
    from fintax_gst.services.itc import ItcService
    from fintax_gst.services.rule37 import Rule37Service
    from sqlalchemy import select

    c = _bills(db, tmp_path)
    with db.session() as s:
        a1 = s.scalar(select(Invoice.id).where(Invoice.invoice_no == "A-1"))
    ItcService(db).claim(c.id, [a1], "2025-04", "accountant")  # only A-1 is in the claim register
    svc = Rule37Service(db)
    due = [b for b in svc.track(c.id, as_of=date(2025, 12, 1)) if b.status == "Reverse ITC"]
    done, skipped = svc.record_reversals(c.id, due, "accountant")
    assert done == 1 and len(skipped) == 3
    with db.session() as s:
        rev = s.scalars(select(ItcClaim).where(ItcClaim.action == "REVERSE")).one()
        assert rev.period == "2025-10" and rev.rule_ref == "Rule 37 CGST Rules" and rev.cgst == D("900.00")


def test_cli_payments_and_rule37(tmp_path, capsys, sample_files):
    from fintax_gst.cli import main

    dbp = str(tmp_path / "cli.db")
    assert main(["--db", dbp, "client", "add", "--name", CLIENT["name"], "--gstin", CLIENT["gstin"]]) == 0
    assert main(["--db", dbp, "import", "--client", CLIENT["gstin"], "--source", "books", "--file",
                 str(sample_files["books_april"])]) == 0
    assert main(["--db", dbp, "payments", "--client", CLIENT["gstin"], "--file",
                 str(sample_files["payments"])]) == 0
    capsys.readouterr()
    assert main(["--db", dbp, "rule37", "--client", CLIENT["gstin"], "--as-of", "2025-11-15"]) == 0
    out = capsys.readouterr().out
    assert "Reverse ITC" in out and "Paid late – re-claim" in out and "ITC to reverse:" in out


# ------------------------------------------------------------------ PAN view (14D)
def test_pan_view(db, sample_files, tmp_path):
    from openpyxl import load_workbook

    from fintax_gst.services.pan_view import PanViewService
    from fintax_gst.services.reconciliation import ReconciliationService

    clients = ClientService(db)
    mh = clients.create(**CLIENT)
    ka = clients.create(gstin("29", "AAPFU0939F"), None, name="Shree Ganesh Traders (Karnataka)")
    clients.create(gstin("24", "AADCG8765N"), None, name="Single State Ltd")
    imp = ImportService(db)
    imp.import_file(mh.id, sample_files["books_april"], Source.BOOKS)
    imp.import_file(mh.id, sample_files["gstr2b_april_json"], Source.GSTR2B)
    ReconciliationService(db).run(mh.id, "2025-04")
    reg = tmp_path / "ka.csv"
    reg.write_text(f"GSTIN,Invoice No,Invoice Date,Taxable Value,IGST\n{MH},K-1,03-04-2025,1000,180\n")
    imp.import_file(ka.id, reg, Source.BOOKS)

    svc = PanViewService(db)
    groups = svc.groups()
    assert [(pan, [c.gstin for c in cs]) for pan, cs in groups] == [("AAPFU0939F", [mh.gstin, ka.gstin])]
    assert len(svc.groups(include_single=True)) == 2
    v = svc.view("aapfu0939f", "2025-26", today=date(2025, 6, 15))
    m, k = v.registrations
    assert (m.state, k.state) == ("Maharashtra", "Karnataka")
    assert m.months_reconciled == 1 and m.itc_at_risk > 0 and k.months_reconciled == 0
    assert k.itc_books == D("180") and v.total("itc_books") == m.itc_books + D("180")
    assert m.returns_overdue == 3  # April GSTR-1 and 3B, May GSTR-1 (due 11 June)
    assert v.suppliers and all(a.registrations == {mh.gstin} for a in v.suppliers)
    wb = load_workbook(svc.export_xlsx(v, tmp_path / "pan.xlsx", "Shree Ganesh Traders"))
    assert wb.sheetnames == ["Registrations", "Suppliers to follow up"] and wb["Registrations"].max_row == 5
    with pytest.raises(ServiceError):
        svc.view("ZZZZZ9999Z", "2025-26")


def test_cli_pan_view(tmp_path, capsys):
    from fintax_gst.cli import main

    dbp = str(tmp_path / "cli.db")
    assert main(["--db", dbp, "client", "add", "--name", CLIENT["name"], "--gstin", CLIENT["gstin"]]) == 0
    assert main(["--db", dbp, "pan-view"]) == 0
    assert "AAPFU0939F" in capsys.readouterr().out
    assert main(["--db", dbp, "pan-view", "--pan", "AAPFU0939F", "--fy", "2025-26"]) == 0
    assert "Maharashtra" in capsys.readouterr().out
