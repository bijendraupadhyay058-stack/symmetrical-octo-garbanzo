"""Phase 12: direct Tally import."""
import importlib.util
from datetime import date
from pathlib import Path

import pytest

from fintax_gst.cli import main
from fintax_gst.core.models import DocType, Source
from fintax_gst.importers.pipeline import preview_file
from fintax_gst.importers.readers import UnsupportedFileError
from fintax_gst.importers.tally_xml import TallyClient, flatten_vouchers, parse_xml
from fintax_gst.samples import CLIENT
from fintax_gst.services.clients import ClientService
from fintax_gst.services.imports import ImportService
from fintax_gst.services.tally import TallyService

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def tally(sample_files):
    spec = importlib.util.spec_from_file_location("tally_simulator", ROOT / "scripts" / "tally_simulator.py")
    sim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sim)
    server = sim.serve(sample_files["books_tally_xml"], port=0, company=CLIENT["name"], background=True)
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _key(r):
    return (r.supplier_gstin, r.invoice_no_norm, r.doc_type, r.invoice_date, r.taxable, r.igst, r.cgst, r.sgst,
            r.period)


def test_tally_xml_matches_the_excel_register(sample_files):
    xml = preview_file(sample_files["books_tally_xml"], Source.BOOKS)
    xlsx = preview_file(sample_files["books_april"], Source.BOOKS)
    assert xml.layout == "tally_xml"
    assert {_key(r) for r in xml.records} == {_key(r) for r in xlsx.records}
    ignored = {i.row: i.message for i in xml.issues if i.severity == "ignored"}
    assert ignored == {"Purchase 99": "cancelled voucher",
                       "Payment 7": "voucher type 'Payment' is not a purchase / sales / note voucher"}
    # a purchase return (debit note voucher) is the supplier's credit note
    assert any(r.doc_type == DocType.CREDIT_NOTE for r in xml.records)
    with pytest.raises(UnsupportedFileError, match="purchase or sales register"):
        preview_file(sample_files["books_tally_xml"], Source.GSTR2B)


def test_tally_xml_details():
    xml = b"""<?xml version="1.0"?><ENVELOPE><BODY><DATA>
      <VOUCHER VCHTYPE="GST Sales"><DATE>20250405</DATE><VOUCHERTYPENAME>GST Sales</VOUCHERTYPENAME>
        <VOUCHERNUMBER>S/1</VOUCHERNUMBER><PARTYLEDGERNAME>Asha &amp; Co</PARTYLEDGERNAME>
        <PARTYGSTIN>27AABCR1122A1Z7</PARTYGSTIN>
        <ALLLEDGERENTRIES.LIST><LEDGERNAME>Asha &amp; Co</LEDGERNAME><ISPARTYLEDGER>Yes</ISPARTYLEDGER>
          <AMOUNT>-11800.40</AMOUNT></ALLLEDGERENTRIES.LIST>
        <ALLLEDGERENTRIES.LIST><LEDGERNAME>Output CGST</LEDGERNAME><AMOUNT>900.00</AMOUNT></ALLLEDGERENTRIES.LIST>
        <ALLLEDGERENTRIES.LIST><LEDGERNAME>Output SGST</LEDGERNAME><AMOUNT>900.00</AMOUNT></ALLLEDGERENTRIES.LIST>
        <ALLLEDGERENTRIES.LIST><LEDGERNAME>Rounding Off</LEDGERNAME><AMOUNT>0.40</AMOUNT></ALLLEDGERENTRIES.LIST>
        <ALLLEDGERENTRIES.LIST><LEDGERNAME>State Bank Charges</LEDGERNAME><AMOUNT>0</AMOUNT></ALLLEDGERENTRIES.LIST>
        <ALLINVENTORYENTRIES.LIST><STOCKITEMNAME>Steel</STOCKITEMNAME><AMOUNT>10000.00</AMOUNT>
          <GSTHSNNAME>7208</GSTHSNNAME><ACTUALQTY>10 MT</ACTUALQTY>
          <ACCOUNTINGALLOCATIONS.LIST><LEDGERNAME>Sales @18%</LEDGERNAME><AMOUNT>10000.00</AMOUNT>
          </ACCOUNTINGALLOCATIONS.LIST></ALLINVENTORYENTRIES.LIST>
      </VOUCHER>
      <VOUCHER VCHTYPE="Purchase"><DATE>20250406</DATE><VOUCHERTYPENAME>Purchase</VOUCHERTYPENAME>
        <VOUCHERNUMBER>P/9</VOUCHERNUMBER><ISOPTIONAL>Yes</ISOPTIONAL></VOUCHER>
    </DATA></BODY></ENVELOPE>"""
    found = flatten_vouchers(parse_xml(xml), "sales")
    (row,) = found.rows
    assert row["invoice_no"] == "S/1" and row["supplier_name"] == "Asha & Co" and row["invoice_date"] == date(2025, 4, 5)
    assert (row["taxable_value"], row["cgst"], row["sgst"], row["igst"]) == ("10000.00", "900.00", "900.00", "0")
    assert row["invoice_value"] == "11800.40" and row["hsn"] == "7208"  # round-off in the value, not the taxable
    assert found.ignored == []  # the optional purchase belongs to the other register
    purchases = flatten_vouchers(parse_xml(xml), "purchase")
    assert purchases.ignored == [("Purchase P/9", "optional (memorandum) voucher")]


def test_tally_xml_refuses_entities():
    with pytest.raises(UnsupportedFileError):
        parse_xml(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><ENVELOPE>&a;</ENVELOPE>')
    # control-character references Tally sometimes emits are dropped, not fatal
    assert parse_xml(b"<ENVELOPE><X>a&#4;b</X></ENVELOPE>").findtext("X") == "ab"


def test_live_fetch_and_import(db, tally, sample_files):
    c = ClientService(db).create(**CLIENT)
    client = TallyClient(tally)
    assert client.companies() == [CLIENT["name"]]
    assert client.duty_heads(CLIENT["name"])["Input IGST 18%"] == "igst"
    with pytest.raises(ValueError, match="Could not set"):
        client.vouchers("Another Company", date(2025, 4, 1), date(2025, 4, 30))
    path = TallyService(db).fetch(c.id, CLIENT["name"], "2025-04", url=tally, user="preparer")
    assert path.parent == db.data_dir / "tally" and path.read_bytes().startswith(b"<?xml")
    sf, preview = ImportService(db).import_file(c.id, path, Source.BOOKS, user="preparer")
    assert preview.layout == "tally_xml" and sf.documents_imported == 28
    # a month with no vouchers
    empty = TallyService(db).fetch(c.id, CLIENT["name"], "2025-06", url=tally)
    with pytest.raises(UnsupportedFileError, match="no vouchers"):
        preview_file(empty, Source.BOOKS)


def test_unreachable_tally_explains_the_setting():
    with pytest.raises(ConnectionError, match="Connectivity"):
        TallyClient("http://127.0.0.1:9", timeout=2).companies()


def test_cli_tally(tmp_path, tally, capsys):
    dbp = str(tmp_path / "cli.db")
    assert main(["--db", dbp, "client", "add", "--name", CLIENT["name"], "--gstin", CLIENT["gstin"]]) == 0
    assert main(["--db", dbp, "tally", "companies", "--url", tally]) == 0
    assert CLIENT["name"] in capsys.readouterr().out
    assert main(["--db", dbp, "tally", "import", "--url", tally, "--client", "1", "--company", CLIENT["name"],
                 "--from", "2025-04"]) == 0
    out = capsys.readouterr().out
    assert "Fetched from Tally" in out and "28 documents saved" in out
