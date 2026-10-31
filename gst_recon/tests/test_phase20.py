"""Phase 20: reverse charge register, ISD distribution, bank statement vs electronic cash ledger."""
from datetime import date
from decimal import Decimal as D

import pytest

from fintax_gst.core.models import Source
from fintax_gst.samples import CLIENT, gstin
from fintax_gst.services.clients import ClientService
from fintax_gst.services.common import ServiceError
from fintax_gst.services.imports import ImportService

from .conftest import rec


# ------------------------------------------------------------------ RCM (20A)
def test_rcm_month_rules():
    from fintax_gst.compliance.rcm import rcm_month
    from fintax_gst.importers.gstr3b import Gstr3bValues

    gta = rec("B", "T-1", "2025-04-03", cgst="250", sgst="250", reverse_charge=True, description="Freight inward")
    gta_untaxed = rec("B", "T-2", "2025-04-04", cgst="0", sgst="0", reverse_charge=True)
    legal = rec("B", "L-1", "2025-04-05", cgst="0", sgst="0", description="Advocate fees – appeal")
    normal = rec("B", "N-1", "2025-04-06", description="Raw material")
    may = rec("B", "M-1", "2025-05-01", reverse_charge=True, period="2025-05")
    m = rcm_month("2025-04", [gta, gta_untaxed, legal, normal, may], {"31D": Gstr3bValues(cgst=D(250), sgst=D(250))})
    by = {ln.doc.invoice_no: ln for ln in m.lines}
    assert set(by) == {"T-1", "T-2", "L-1"}
    assert by["T-1"].status == "RCM" and by["T-1"].service.startswith("Goods transport")
    assert "no tax in the register" in by["T-2"].issues[0]
    assert by["L-1"].status == "Possible RCM – check" and "advocate" in by["L-1"].issues[0]
    assert m.register_total().total == D(500) and m.filed_31d.total == D(500)


def test_rcm_register_and_self_invoices(db, tmp_path):
    from pypdf import PdfReader

    from fintax_gst.services.gstr3b_draft import Gstr3bDraftService
    from fintax_gst.services.rcm import RcmService

    c = ClientService(db).create(**CLIENT)  # Maharashtra (27)
    svc = RcmService(db)
    e = svc.add_entry(c.id, date(2025, 4, 1), "Shri Ram Kulkarni", "50,000", "18", "accountant", "R/APR",
                      "Office rent – April", "27")
    assert (e.cgst, e.sgst, e.igst) == (D(4500), D(4500), D(0)) and e.period == "2025-04"
    with pytest.raises(ServiceError):
        svc.add_entry(c.id, date(2025, 4, 1), "", "100", "18")
    (tmp_path / "rcm.csv").write_text("Date,Party Name,Amount,Rate,State,Narration\n"
                                      "10-04-2025,Karnataka Roadlines,20000,5,Karnataka,Freight\n"
                                      "12-04-2025,Adv. Mehta,15000,18,,Legal fees\n"
                                      ",Bad row,100,18,,\n", encoding="utf-8")
    saved, problems = svc.import_entries(c.id, tmp_path / "rcm.csv", user="accountant")
    assert saved == 2 and "no date" in problems[0]
    m = svc.month(c.id, "2025-04")
    assert len(m.marked) == 3 and all(ln.needs_self_invoice for ln in m.marked)
    freight = next(ln for ln in m.marked if ln.doc.supplier_name == "Karnataka Roadlines")
    assert freight.doc.igst == D(1000) and freight.service.startswith("Goods transport")
    assert m.register_total().total == D(4500 + 4500 + 1000 + 2700)
    pdf, n = svc.self_invoices_pdf(c.id, "2025-04", tmp_path / "si.pdf", first_number=7, user="accountant")
    text = "\n".join(p.extract_text() for p in PdfReader(str(pdf)).pages)
    assert n == 3 and "SI/2025-26/0007" in text and "SI/2025-26/0009" in text and "SELF-INVOICE" in text
    d = Gstr3bDraftService(db).draft(c.id, "2025-04")
    assert d.t31["31D"].total == D(12700) and d.t4["4A3"].total == D(12700)
    assert any("unregistered persons" in n for n in d.notes)
    svc.delete_entry(e.id, "accountant")
    assert len(svc.month(c.id, "2025-04").marked) == 2
    with pytest.raises(ServiceError):
        svc.self_invoices_pdf(c.id, "2025-05", tmp_path / "x.pdf")


def test_isd_distribution(db, tmp_path):
    from openpyxl import load_workbook

    from fintax_gst.compliance.rcm import distribute_isd
    from fintax_gst.importers.gstr3b import Gstr3bValues
    from fintax_gst.services.rcm import RcmService

    shares = distribute_isd(Gstr3bValues(igst=D("1000.00"), cgst=D("500.00"), sgst=D("500.00")), "27",
                            [("Pune", gstin("27", "AABCS1234K"), D(600)), ("Bengaluru", gstin("29", "AABCS1234K"),
                                                                           D(300)),
                             ("Delhi", gstin("07", "AABCS1234K"), D(100)), ("Idle", gstin("24", "AABCS1234K"), D(0))])
    pune, blr, dl, idle = shares
    assert (pune.igst, pune.cgst, pune.sgst) == (D(600), D(300), D(300))
    assert (blr.igst, blr.cgst, blr.sgst) == (D(300) + D(150) + D(150), D(0), D(0))  # CGST/SGST go as IGST
    assert idle.total == 0 and pune.ratio == D("60.0000")
    assert sum((s.total for s in shares), D(0)) == D(2000)
    odd = distribute_isd(Gstr3bValues(igst=D("100.00")), "27", [("A", gstin("27", "AABCS1234K"), D(1)),
                                                                 ("B", gstin("29", "AABCS1234K"), D(1)),
                                                                 ("C", gstin("07", "AABCS1234K"), D(1))])
    assert sum((s.igst for s in odd), D(0)) == D(100)  # rounding difference absorbed
    # service: ISD registration and two units of the same PAN
    cs = ClientService(db)
    isd = cs.create(**{**CLIENT, "gstin": gstin("27", "AABCS1234K", "2"), "name": "Shakti ISD"})
    pune_c = cs.create(**{**CLIENT, "gstin": gstin("27", "AABCS1234K"), "name": "Shakti Pune"})
    ka = cs.create(**{**CLIENT, "gstin": gstin("29", "AABCS1234K"), "name": "Shakti Bengaluru", "state_code": "29"})
    (tmp_path / "isd_books.csv").write_text(
        "GSTIN,Supplier Name,Invoice No,Invoice Date,Taxable Value,CGST,SGST\n"
        f"{gstin('27', 'AABCM1234K')},Consultant,C-1,05-04-2025,10000,900,900\n", encoding="utf-8")
    ImportService(db).import_file(isd.id, tmp_path / "isd_books.csv", Source.BOOKS)
    svc = RcmService(db)
    assert {u.id for u in svc.isd_units(isd.id)} == {pune_c.id, ka.id}
    with pytest.raises(ServiceError, match="No turnover"):
        svc.isd_distribution(isd.id, "2025-04")
    itc, shares, basis = svc.isd_distribution(isd.id, "2025-04", {pune_c.id: D(750), ka.id: D(250)})
    assert itc.total == D(1800) and basis == "entered"
    by = {s.name: s for s in shares}
    assert (by["Shakti Pune"].cgst, by["Shakti Pune"].sgst) == (D(675), D(675))
    assert by["Shakti Bengaluru"].igst == D(450)
    out = svc.export_isd(isd.id, "2025-04", shares, itc, basis, tmp_path / "isd.xlsx")
    ws = load_workbook(out)["Distribution"]
    assert ws["A5"].value == "ISD/2025-04/001" and ws.max_row == 6
