"""Phase 15: GSTR-1 JSON, GSTR-3B draft, invoices entered by hand."""
import json
from datetime import date
from decimal import Decimal as D

import pytest

from fintax_gst.core.models import Source
from fintax_gst.outward.gstr1_json import SaleDoc, build_gstr1
from fintax_gst.samples import CLIENT, gstin
from fintax_gst.services.clients import ClientService
from fintax_gst.services.common import ServiceError
from fintax_gst.services.imports import ImportService

ME = CLIENT["gstin"]  # Maharashtra
KA_CUST = gstin("29", "AACCV5566C")


def _s(no, taxable, igst="0", cgst="0", sgst="0", g="", doc="INV", dt=date(2025, 4, 10), **kw):
    return SaleDoc(1, g, "Cust", doc, no, dt, D(taxable), D(igst), D(cgst), D(sgst), D(0), **kw)


# ------------------------------------------------------------------ GSTR-1 JSON (15A)
def test_gstr1_sections():
    docs = [
        _s("A/1", "1000", cgst="90", sgst="90", g=gstin("27", "AABCR1122A")),  # B2B intra
        _s("A/2", "2000", igst="360", g=KA_CUST, place_of_supply="29-Karnataka"),  # B2B inter
        _s("A/3", "500", igst="25", g=KA_CUST, supply_type="SEZ with payment"),  # SEZ -> SEWP
        _s("A/4", "150000", igst="27000", place_of_supply="Karnataka"),  # B2C inter above 1 lakh -> B2CL
        _s("A/5", "50000", igst="9000", place_of_supply="Karnataka"),  # B2C inter below the limit -> B2CS
        _s("A/6", "1000", cgst="90", sgst="90"),  # local B2C -> B2CS
        _s("A/7", "100", cgst="9", sgst="9"),  # local B2C, same rate: summed
        _s("CN/1", "100", cgst="9", sgst="9", doc="CRN"),  # B2C credit note: netted in B2CS
        _s("CN/2", "200", cgst="18", sgst="18", g=gstin("27", "AABCR1122A"), doc="CRN"),  # CDNR
        _s("E/1", "5000", supply_type="Export (LUT)"),  # export without payment
        _s("X/1", "800", supply_type="Exempt", g=gstin("27", "AABCR1122A")),  # nil / exempt
        _s("A/8", "1000", cgst="75", sgst="75"),  # 15 %: no such rate -> left out
        _s("A/9", "1000", cgst="90", sgst="90", g="27AABCR1122A1Z0"),  # wrong check digit -> left out
        _s("A/10", "200000", igst="36000", place_of_supply="Karnataka", dt=date(2024, 7, 10)),  # old 2.5 lakh limit
    ]
    d = build_gstr1(ME, "2025-04", docs)
    p = d.payload
    assert p["fp"] == "042025" and p["gstin"] == ME
    assert {c["ctin"] for c in p["b2b"]} == {gstin("27", "AABCR1122A"), KA_CUST}
    ka = next(c for c in p["b2b"] if c["ctin"] == KA_CUST)["inv"]
    assert {i["inum"]: i["inv_typ"] for i in ka} == {"A/2": "R", "A/3": "SEWP"} and ka[0]["pos"] == "29"
    assert ka[0]["itms"][0]["itm_det"] == {"txval": 2000.0, "rt": 18.0, "iamt": 360.0, "csamt": 0.0}
    assert [i["inum"] for g in p["b2cl"] for i in g["inv"]] == ["A/4"]
    b2cs = {(r["sply_ty"], r["pos"], r["rt"]): r for r in p["b2cs"]}
    assert b2cs[("INTRA", "27", 18.0)]["txval"] == 1000.0  # 1000 + 100 - 100 (credit note)
    assert b2cs[("INTER", "29", 18.0)]["iamt"] == 9000.0 + 36000.0  # A/10: below the limit of its date
    assert "camt" not in b2cs[("INTER", "29", 18.0)]
    assert p["cdnr"][0]["nt"][0]["ntty"] == "C"
    assert p["exp"] == [{"exp_typ": "WOPAY", "inv": [{"inum": "E/1", "idt": "10-04-2025", "val": 5000.0, "itms": [
        {"txval": 5000.0, "rt": 0.0, "iamt": 0.0, "csamt": 0.0}]}]}]
    assert p["nil"]["inv"] == [{"sply_ty": "INTRAB2B", "expt_amt": 800.0, "nil_amt": 0.0, "ngsup_amt": 0.0}]
    left = {i.doc.number: i.message for i in d.issues if i.severity == "error"}
    assert set(left) == {"A/8", "A/9"} and "not a GST rate" in left["A/8"]
    assert d.counts["B2B"] == 3 and d.counts["B2CS"] == 5


def test_gstr1_hsn_and_documents():
    lines = [{"hsn": "7318", "uqc": "KGS", "qty": "10", "taxable": "1000", "igst": "0", "cgst": "90", "sgst": "90"},
             {"hsn": "9983", "uqc": "", "qty": "0", "taxable": "500", "igst": "0", "cgst": "45", "sgst": "45"}]
    docs = [_s("INV-001", "1500", cgst="135", sgst="135", g=gstin("27", "AABCR1122A"), hsn_lines=lines),
            _s("INV-002", "1000", cgst="90", sgst="90", hsn_lines=lines[:1]),
            _s("INV-005", "100", cgst="9", sgst="9"),
            _s("CN-1", "100", cgst="9", sgst="9", doc="CRN")]
    d = build_gstr1(ME, "2025-04", docs)
    hsn = d.payload["hsn"]
    assert [(r["hsn_sc"], r["uqc"], r["rt"], r["txval"]) for r in hsn["hsn_b2b"]] == [
        ("7318", "KGS", 18.0, 1000.0), ("9983", "NA", 18.0, 500.0)]  # services: UQC 'NA'
    assert hsn["hsn_b2c"][0]["qty"] == 10.0
    assert any("2 document(s) have no HSN lines" in i.message for i in d.issues)
    inv = d.payload["doc_issue"]["doc_det"][0]
    assert inv["doc_num"] == 1 and inv["docs"] == [{"num": 1, "from": "INV-001", "to": "INV-005", "totnum": 5,
                                                    "cancel": 2, "net_issue": 3}]
    assert any("2 number(s) between INV-001 and INV-005" in i.message for i in d.issues)
    assert d.payload["doc_issue"]["doc_det"][1]["doc_num"] == 5  # credit notes


def test_gstr1_round_trip(db, sample_files, tmp_path):
    """The JSON made from the sales register, imported as GSTR-1, reconciles with that register."""
    from fintax_gst.core.models import Category
    from fintax_gst.services.gstr1_prep import Gstr1PrepService
    from fintax_gst.services.reconciliation import ReconciliationService

    c = ClientService(db).create(**CLIENT)
    imp = ImportService(db)
    imp.import_file(c.id, sample_files["sales_april"], Source.SALES)
    svc = Gstr1PrepService(db)
    draft = svc.draft(c.id, "2025-04")
    out = svc.save(c.id, draft, tmp_path / "gstr1.json", "accountant")
    assert json.loads(out.read_text(encoding="utf-8"))["fp"] == "042025"
    imp.import_file(c.id, out, Source.GSTR1)
    run = ReconciliationService(db).run(c.id, "2025-04", compare_with=Source.GSTR1)
    lines = ReconciliationService(db).load(run).result.lines
    assert lines and all(ln.category == Category.FULLY_MATCHED for ln in lines)
    with pytest.raises(ServiceError, match="No sales register"):
        svc.draft(c.id, "2025-05")


def test_cli_gstr1_json(tmp_path, capsys, sample_files):
    from fintax_gst.cli import main

    dbp = str(tmp_path / "cli.db")
    assert main(["--db", dbp, "client", "add", "--name", CLIENT["name"], "--gstin", CLIENT["gstin"]]) == 0
    assert main(["--db", dbp, "import", "--client", ME, "--source", "sales", "--file",
                 str(sample_files["sales_april"])]) == 0
    capsys.readouterr()
    out = tmp_path / "g1.json"
    assert main(["--db", dbp, "gstr1-json", "--client", ME, "--period", "2025-04", "--out", str(out)]) == 0
    assert "B2B" in capsys.readouterr().out and out.exists()
