"""Phase 21: exports, SEZ and refunds; composition and QRMP."""
from datetime import date
from decimal import Decimal as D

import pytest

from fintax_gst.samples import CLIENT, gstin
from fintax_gst.services.clients import ClientService
from fintax_gst.services.common import ServiceError


def _sale(no, dt, taxable, igst="0", supply="Export without payment", hsn="7208", **kw):
    from fintax_gst.outward.gstr1_json import SaleDoc

    return SaleDoc(1, "", "Overseas Buyer", "INV", no, dt, D(taxable), D(igst), D(0), D(0), D(0),
                   place_of_supply="96-Other Countries", supply_type=supply,
                   hsn_lines=[{"hsn": hsn, "taxable": taxable}], **kw)


# ------------------------------------------------------------------ exports (21A)
def test_export_checks():
    from fintax_gst.outward.exports import ACTION, CHECK, OK, ShippingBill, check_exports

    docs = [_sale("E/1", date(2025, 4, 5), "100000", "18000", "Export with payment"),
            _sale("E/2", date(2025, 4, 6), "50000", "9000", "Export with payment"),
            _sale("E/3", date(2025, 4, 7), "60000", "6000", "Export with payment"),
            _sale("L/1", date(2025, 4, 8), "80000"),
            _sale("L/2", date(2025, 9, 1), "70000"),
            _sale("S/1", date(2025, 4, 9), "40000", hsn="998313"),
            _sale("Z/1", date(2025, 4, 10), "30000", supply="SEZ without payment")]
    bills = [ShippingBill("4455667", date(2025, 4, 8), "INNSA1", "E/1", D(18000)),
             ShippingBill("4455668", date(2025, 4, 9), "INNSA1", "E-3", D(5400)),
             ShippingBill("4455669", date(2025, 8, 20), "INMAA1", "L/1")]
    by = {ln.doc.number: ln for ln in check_exports(docs, bills, date(2025, 10, 1))}
    assert by["E/1"].status == OK and "refund-ready" in by["E/1"].note
    assert by["E/2"].status == ACTION and "no shipping bill" in by["E/2"].note
    assert by["E/3"].status == CHECK and "differs" in by["E/3"].note  # number written E-3 on the SB
    assert by["L/1"].status == CHECK and "after three months" in by["L/1"].note
    assert by["L/2"].status == CHECK and "export by 30-11-2025" in by["L/2"].note
    assert not by["S/1"].goods and "foreign exchange" in by["S/1"].note
    assert by["Z/1"].kind == "SEZ under LUT" and "endorsement" in by["Z/1"].note
    late = {ln.doc.number: ln for ln in check_exports(docs, [], date(2025, 12, 15))}
    assert late["L/2"].status == ACTION and "rule 96A" in late["L/2"].note


def test_refund_formulas():
    from fintax_gst.outward.exports import RefundInputs, compute_refund

    zr = compute_refund(RefundInputs("zero_rated", "2025-04", "2025-06", turnover_zero_rated=D(6000000),
                                     adjusted_total_turnover=D(10000000), net_itc=D(900000),
                                     credit_ledger_balance=D(500000)))
    assert zr.amount == D(540000) and zr.admissible == D(500000)  # limited to the credit ledger balance
    inv = compute_refund(RefundInputs("inverted", "2025-04", "2025-06", turnover_inverted=D(5000000),
                                      adjusted_total_turnover=D(5000000), net_itc=D(800000),
                                      itc_inputs_and_services=D(1000000), tax_payable_inverted=D(250000)))
    # 50,00,000 × 8,00,000 ÷ 50,00,000 − 2,50,000 × 8,00,000 ÷ 10,00,000 = 8,00,000 − 2,00,000
    assert inv.amount == D(600000) and inv.admissible == D(600000)
    with pytest.raises(ValueError):
        compute_refund(RefundInputs("zero_rated", "2025-04", "2025-04"))


def test_export_service(db, tmp_path, sample_files):
    from openpyxl import Workbook, load_workbook

    from fintax_gst.core.models import Source
    from fintax_gst.services.exports import ExportService
    from fintax_gst.services.imports import ImportService

    c = ClientService(db).create(**CLIENT)
    ImportService(db).import_file(c.id, sample_files["sales_april"], Source.SALES)
    svc = ExportService(db)
    lines = svc.check(c.id, "2025-04", "2025-04", date(2025, 5, 1))
    assert lines and all(ln.kind.startswith(("Export", "SEZ")) for ln in lines)
    wb = Workbook()
    ws = wb.active
    ws.append(["Shipping Bill No", "Shipping Bill Date", "Port Code", "Invoice No", "IGST Amount", "FOB Value"])
    ws.append(["4455667", "25-04-2025", "INNSA1", lines[0].doc.number, float(lines[0].doc.igst), 100000])
    ws.append(["", "25-04-2025", "INNSA1", "X", 0, 0])
    wb.save(tmp_path / "sb.xlsx")
    saved, problems = svc.import_shipping_bills(c.id, tmp_path / "sb.xlsx", "accountant")
    assert saved == 1 and "missing" in problems[0]
    assert svc.import_shipping_bills(c.id, tmp_path / "sb.xlsx")[0] == 0  # never twice
    first = svc.check(c.id, "2025-04", "2025-04", date(2025, 5, 1))[0]
    assert first.sb is not None and first.sb.sb_no == "4455667"
    svc.save_lut(c.id, "2025-26", "AD270325000123X", date(2025, 3, 20), "accountant")
    assert svc.lut(c.id, "2025-26")["arn"] == "AD270325000123X"
    inp = svc.refund_defaults(c.id, "zero_rated", "2025-04", "2025-04")
    assert inp.adjusted_total_turnover > 0 and inp.credit_ledger_balance is None
    assert any("credit ledger" in n for n in inp.notes)
    inp.net_itc = D(10000)
    res = svc.refund(inp)
    assert res.formula == "Rule 89(4)"
    out = svc.export_xlsx(c.id, lines, (inp, res), tmp_path / "exp.xlsx")
    assert load_workbook(out).sheetnames == ["Exports", "Refund working"]
    inp.adjusted_total_turnover = D(0)
    with pytest.raises(ServiceError):
        svc.refund(inp)
    assert gstin


# ------------------------------------------------------------------ composition and QRMP (21B)
def test_composition_cmp08_and_gstr4(db, tmp_path, sample_files):
    from fintax_gst.core.models import Source
    from fintax_gst.services.composition import CompositionService, quarter_label, quarter_months
    from fintax_gst.services.imports import ImportService
    from fintax_gst.services.rcm import RcmService

    assert quarter_months("2025-05") == ["2025-04", "2025-05", "2025-06"] and quarter_label("2025-05") == \
        "Apr – Jun 2025"
    c = ClientService(db).create(**CLIENT)
    svc = CompositionService(db)
    with pytest.raises(ServiceError, match="composition dealer"):
        svc.cmp08(c.id, "2025-04")
    svc.set_category(c.id, "trader", "manager")
    ImportService(db).import_file(c.id, sample_files["sales_april"], Source.SALES)
    RcmService(db).add_entry(c.id, date(2025, 5, 3), "Local Transport", "10000", "5", supplier_state="27")
    q = svc.cmp08(c.id, "2025-05")
    assert q.rate == D(1) and q.turnover > 0
    assert q.tax_outward["cgst"] == q.tax_outward["sgst"] == (q.turnover / 200).quantize(D("0.01"))
    assert q.tax_rcm["cgst"] == D(250) and q.total == q.tax_outward["cgst"] * 2 + D(500)
    g4 = svc.gstr4(c.id, "2025-26")
    assert len(g4["quarters"]) == 4 and g4["turnover"] == q.turnover
    svc.set_category(c.id, None)
    assert svc.category(c.id) is None


def test_qrmp_pmt06(db, tmp_path):
    from fintax_gst.services.composition import CompositionService
    from fintax_gst.services.gstr3b import Gstr3bService

    c = ClientService(db).create(**{**CLIENT, "return_frequency": "Quarterly"})
    # last quarter's GSTR-3B (Jan–Mar 2025) with tax paid in cash
    (tmp_path / "3b.csv").write_text("Period,Table,Description,IGST,CGST,SGST,Cess\n"
                                     "2025-03,4A5,All other ITC,100,100,100,0\n"
                                     "2025-03,61CASH,Tax paid in cash,10000,20000,20000,0\n", encoding="utf-8")
    Gstr3bService(db).import_file(c.id, tmp_path / "3b.csv")
    svc = CompositionService(db)
    with pytest.raises(ServiceError, match="last month of the quarter"):
        svc.pmt06(c.id, "2025-06")
    p = svc.pmt06(c.id, "2025-04")
    assert p.fixed_sum == {"igst": D(3500), "cgst": D(7000), "sgst": D(7000), "cess": D(0)}
    assert "35 %" in p.fixed_basis
    assert p.self_assessed == {"igst": D(0), "cgst": D(0), "sgst": D(0), "cess": D(0)}  # nothing sold in April
    assert p.iff_docs == 0 and not p.iff_over_limit
