"""Write the Excel templates for purchase and sales registers (blank and with examples) into sample_data/.

Usage:  python scripts/make_templates.py
The headings are ones FIN TAX PRO recognises automatically, so the files import without any column mapping.
"""
from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal as D
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Alignment, Font, PatternFill  # noqa: E402
from openpyxl.worksheet.datavalidation import DataValidation  # noqa: E402

from fintax_gst.samples import gstin  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "sample_data"
NAVY = PatternFill("solid", fgColor="1F3864")
NOTE = PatternFill("solid", fgColor="FFF3C4")

PURCHASE = ["Date", "Particulars", "Voucher Type", "Voucher No.", "Supplier Invoice No", "Supplier Invoice Date",
            "GSTIN/UIN", "Place of Supply", "Reverse Charge", "Taxable Value", "IGST", "CGST", "SGST", "Cess",
            "Invoice Value", "Narration"]
SALES = ["Date", "Particulars", "Voucher Type", "Voucher No.", "GSTIN/UIN", "Place of Supply", "Type of Supply",
         "Taxable Value", "IGST", "CGST", "SGST", "Cess", "Invoice Value", "Narration"]
WIDTHS = {"Date": 12, "Particulars": 30, "Voucher Type": 14, "Voucher No.": 12, "Supplier Invoice No": 18,
          "Supplier Invoice Date": 14, "GSTIN/UIN": 18, "Place of Supply": 16, "Reverse Charge": 10,
          "Type of Supply": 18, "Narration": 34}

PURCHASE_HELP = [
    "HOW TO FILL THE PURCHASE REGISTER TEMPLATE",
    "",
    "One row per purchase invoice, debit note or credit note. If an invoice has items at two tax rates, you may",
    "enter one row per rate with the same supplier invoice number – they are combined into one document.",
    "",
    "Date – the date you booked the voucher (DD-MM-YYYY). It decides the month the invoice belongs to.",
    "Particulars – supplier name.",
    "Voucher Type – Purchase; Debit Note for a purchase return; Credit Note for a rate increase / extra charge.",
    "Voucher No. – your voucher number (optional).",
    "Supplier Invoice No – the bill number printed on the supplier's invoice. This is the number the GST portal shows.",
    "Supplier Invoice Date – the date on the supplier's invoice (DD-MM-YYYY).",
    "GSTIN/UIN – the supplier's 15-character GSTIN. Rows without it are rejected (unregistered purchases).",
    "Place of Supply – state name or code, e.g. Maharashtra or 27 (optional).",
    "Reverse Charge – Yes for RCM purchases (e.g. GTA), otherwise No.",
    "Taxable Value, IGST, CGST, SGST, Cess – amounts in rupees. Use positive numbers, also for returns.",
    "Invoice Value – total of the invoice (optional).",
    "Narration – free text (optional); words like food, gift, motor car help the ITC review.",
    "",
    "Do not change the heading row. Extra columns are ignored. Save as Excel (.xlsx).",
    "In FIN TAX PRO: Reconcile → Import purchase register… → choose this file.",
    "This 'How to fill' sheet is not imported.",
]
SALES_HELP = [
    "HOW TO FILL THE SALES REGISTER TEMPLATE",
    "",
    "One row per sales invoice, credit note or debit note issued by you.",
    "",
    "Date – invoice date (DD-MM-YYYY). It decides the month.",
    "Particulars – customer name (for cash sales, e.g. 'Cash sales').",
    "Voucher Type – Sales; Credit Note for a sales return / discount; Debit Note for an extra charge.",
    "Voucher No. – your invoice number exactly as reported in GSTR-1.",
    "GSTIN/UIN – customer's GSTIN. Leave blank for unregistered customers (B2C) and exports.",
    "Place of Supply – state name or code, e.g. Karnataka or 29; 96 for exports (optional).",
    "Type of Supply – Regular, SEZ with payment, SEZ without payment, Export (LUT), Export with payment,",
    "    Deemed export, Exempt, Nil rated, Non-GST.",
    "Taxable Value, IGST, CGST, SGST, Cess – amounts in rupees. Use positive numbers, also for credit notes.",
    "Invoice Value – total of the invoice (optional).",
    "",
    "Do not change the heading row. Extra columns are ignored. Save as Excel (.xlsx).",
    "In FIN TAX PRO: Sales & GSTR-1 → Import sales register… → choose this file.",
    "This 'How to fill' sheet is not imported.",
]


def _tax(taxable: str, rate: int, inter: bool) -> tuple[D, D, D, D]:
    t = (D(taxable) * rate / 100).quantize(D("0.01"))
    igst, half = (t, D(0)) if inter else (D(0), t / 2)
    return D(taxable), igst, half, half


def _book(path: Path, title: str, headers: list[str], rows: list[list], help_lines: list[str],
          lists: dict[str, list[str]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = title
    ws.append(headers)
    for i, h in enumerate(headers, start=1):
        c = ws.cell(1, i)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = NAVY
        c.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[c.column_letter].width = WIDTHS.get(h, 13)
    ws.row_dimensions[1].height = 32
    ws.freeze_panes = "A2"
    for r in rows:
        ws.append(r)
    last = 1000
    for i, h in enumerate(headers, start=1):
        letter = ws.cell(1, i).column_letter
        if "Date" in h:
            for row in range(2, last + 1):
                ws[f"{letter}{row}"].number_format = "DD-MM-YYYY"
        elif h in ("Taxable Value", "IGST", "CGST", "SGST", "Cess", "Invoice Value"):
            for row in range(2, last + 1):
                ws[f"{letter}{row}"].number_format = "#,##0.00"
        if h in lists:
            dv = DataValidation(type="list", formula1='"' + ",".join(lists[h]) + '"', allow_blank=True,
                                showErrorMessage=False)
            dv.add(f"{letter}2:{letter}{last}")
            ws.add_data_validation(dv)
    hs = wb.create_sheet("How to fill")
    hs.column_dimensions["A"].width = 115
    for line in help_lines:
        hs.append([line])
    hs["A1"].font = Font(bold=True, size=13, color="1F3864")
    wb.save(path)


def main() -> None:
    sup = {"STEEL": (gstin("27", "AABCM1234K"), "Mahalaxmi Steel Pvt Ltd"),
           "ELEC": (gstin("29", "AACCB5678L"), "Bangalore Electronics LLP"),
           "GTA": (gstin("27", "ABKPS1357T"), "Shree Roadways (GTA)")}
    purchases = []
    for d, vtype, vno, key, inv, inv_d, taxable, rate, rcm, narr in (
            (date(2025, 4, 3), "Purchase", 1, "STEEL", "MSPL/0451", date(2025, 4, 2), "100000", 18, "No",
             "MS sheets"),
            (date(2025, 4, 9), "Purchase", 2, "ELEC", "BE-2290", date(2025, 4, 8), "40000", 18, "No",
             "Control panels"),
            (date(2025, 4, 15), "Purchase", 3, "GTA", "SR/77", date(2025, 4, 15), "12000", 5, "Yes",
             "Freight inward – reverse charge"),
            (date(2025, 4, 20), "Debit Note", 4, "STEEL", "MSPL/CN/12", date(2025, 4, 19), "5000", 18, "No",
             "Purchase return – damaged sheets")):
        g, name = sup[key]
        inter = g[:2] != "27"
        tx, ig, cg, sg = _tax(taxable, rate, inter)
        if rcm == "Yes":
            ig = cg = sg = D(0)  # tax under reverse charge is paid by you, not charged on the bill
        purchases.append([d, name, vtype, vno, inv, inv_d, g, "Karnataka" if inter else "Maharashtra", rcm,
                          tx, ig or None, cg or None, sg or None, None, tx + ig + cg + sg, narr])
    cust = {"RAJ": (gstin("27", "AABCR1122A"), "Rajlaxmi Retail Pvt Ltd"),
            "VEN": (gstin("29", "AACCV5566C"), "Venkatesh Traders")}
    sales = []
    for d, vtype, vno, key, taxable, rate, supply, pos in (
            (date(2025, 4, 3), "Sales", "SGT/25-26/0001", "RAJ", "45000", 18, "Regular", "Maharashtra"),
            (date(2025, 4, 6), "Sales", "SGT/25-26/0002", "VEN", "60000", 18, "Regular", "Karnataka"),
            (date(2025, 4, 10), "Sales", "CS/25-26/001", None, "4250", 18, "Regular", "Maharashtra"),
            (date(2025, 4, 24), "Sales", "EXP/25-26/001", None, "250000", 0, "Export (LUT)", "96"),
            (date(2025, 4, 20), "Credit Note", "SGT-CN/25-26/001", "RAJ", "5000", 18, "Regular", "Maharashtra")):
        g, name = cust[key] if key else ("", "Cash sales" if supply == "Regular" else "Gulf Imports LLC (Dubai)")
        inter = pos not in ("Maharashtra",)
        tx, ig, cg, sg = _tax(taxable, rate, inter)
        sales.append([d, name, vtype, vno, g or None, pos, supply, tx, ig or None, cg or None, sg or None, None,
                      tx + ig + cg + sg, None])
    yesno = {"Reverse Charge": ["No", "Yes"], "Voucher Type": ["Purchase", "Debit Note", "Credit Note"]}
    supplies = {"Voucher Type": ["Sales", "Credit Note", "Debit Note"],
                "Type of Supply": ["Regular", "SEZ with payment", "SEZ without payment", "Export (LUT)",
                                   "Export with payment", "Deemed export", "Exempt", "Nil rated", "Non-GST"]}
    _book(OUT / "TEMPLATE_purchase_register.xlsx", "Purchase Register", PURCHASE, [], PURCHASE_HELP, yesno)
    _book(OUT / "EXAMPLE_purchase_register.xlsx", "Purchase Register", PURCHASE, purchases, PURCHASE_HELP, yesno)
    _book(OUT / "TEMPLATE_sales_register.xlsx", "Sales Register", SALES, [], SALES_HELP, supplies)
    _book(OUT / "EXAMPLE_sales_register.xlsx", "Sales Register", SALES, sales, SALES_HELP, supplies)
    print("Templates written to", OUT)


if __name__ == "__main__":
    main()
