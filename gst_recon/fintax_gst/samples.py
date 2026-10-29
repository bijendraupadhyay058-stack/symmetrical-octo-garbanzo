"""Demo datasets in realistic layouts, with the expected outcome of every scenario.

Generates, for client "Shree Ganesh Traders" (27AAPFU0939F1ZV), April 2025:

* ``tally_purchase_register_2025-04.xlsx`` – TallyPrime columnar purchase register
  (title rows, ledger-wise tax columns, Debit Note vouchers, a total row,
  plus an unregistered purchase and a bad date that must be rejected)
* ``tally_purchase_register_2025-03.xlsx`` – March books (prior-period search)
* ``custom_purchase_register_2025-04.csv`` – the same April books in a custom layout
* ``gstr2b_2025-04.xlsx`` – GST-portal style GSTR-2B Excel (B2B, B2BA, B2B-CDNR)
* ``gstr2b_2025-04.json`` – the same GSTR-2B as portal JSON
* ``EXPECTED_RESULTS.md`` – scenario list with the expected category
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal as D
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

from .core.gstin import check_digit
from .core.models import Category


def gstin(state: str, pan: str, entity: str = "1") -> str:
    base = f"{state}{pan}{entity}Z"
    return base + check_digit(base)


CLIENT = {
    "name": "Shree Ganesh Traders", "trade_name": "Shree Ganesh Traders", "gstin": "27AAPFU0939F1ZV",
    "financial_year": "2025-26", "registration_type": "Regular", "return_frequency": "Monthly",
    "address": "Shop 12, Market Yard, Pune 411037", "contact_person": "R. Kulkarni",
    "email": "accounts@example.com", "mobile": "9800000000",
}

SUPPLIERS = {
    "MSL": (gstin("27", "AABCM1234K"), "Mahalaxmi Steel Pvt Ltd"),
    "MSK": (gstin("29", "AABCM1234K"), "Mahalaxmi Steel Pvt Ltd (Karnataka)"),
    "BEL": (gstin("29", "AACCB5678L"), "Bangalore Electronics LLP"),
    "PPK": (gstin("27", "AAFFP4321M"), "Pune Packaging Co"),
    "GCH": (gstin("24", "AADCG8765N"), "Gujarat Chemicals Ltd"),
    "OSL": (gstin("27", "ABMPS2468P"), "Om Sai Logistics"),
    "DOS": (gstin("07", "AAGFD1357Q"), "Delhi Office Supplies"),
    "KTX": (gstin("33", "AAHCK9753R"), "Kovai Textiles Pvt Ltd"),
}


@dataclass
class Doc:
    sup: str
    no: str
    dt: date
    taxable: str
    igst: str = "0"
    cgst: str = "0"
    sgst: str = "0"
    cess: str = "0"
    doc: str = "INV"  # supplier view: INV / CRN / DBN
    rate: int = 18
    itc: str = "Yes"
    reason: str = ""
    original_no: str = ""
    original_dt: date | None = None


def intra(sup, no, dt, taxable, rate=18, **kw):
    half = (D(taxable) * D(rate) / D(200)).quantize(D("0.01"))
    return Doc(sup, no, dt, taxable, cgst=str(half), sgst=str(half), rate=rate, **kw)


def inter(sup, no, dt, taxable, rate=18, **kw):
    tax = (D(taxable) * D(rate) / D(100)).quantize(D("0.01"))
    return Doc(sup, no, dt, taxable, igst=str(tax), rate=rate, **kw)


def A(day):
    return date(2025, 4, day)


# (scenario, books documents, GSTR-2B documents, expected category, note)
SCENARIOS: list[tuple[str, list[Doc], list[Doc], Category, str]] = []


def scenario(name, books, g2b, expected, note):
    SCENARIOS.append((name, books, g2b, expected, note))


for i, (sup, rate) in enumerate([("MSL", 18), ("PPK", 12), ("OSL", 18), ("MSL", 18), ("PPK", 18)], start=1):
    d = intra(sup, f"{sup}/{100 + i}/25-26", A(i + 1), f"{25000 + i * 1750}", rate)
    scenario(f"Perfect match {i}", [d], [d], Category.FULLY_MATCHED, "All fields agree")
for i, sup in enumerate(["BEL", "GCH", "KTX"], start=1):
    d = inter(sup, f"{sup}-{2000 + i}", A(i + 8), f"{48000 + i * 3300}")
    scenario(f"Perfect match inter-state {i}", [d], [d], Category.FULLY_MATCHED, "IGST invoice")

scenario("Invoice number format", [intra("MSL", "MSL/210/25-26", A(10), "18500")],
         [intra("MSL", "MSL-210-25-26", A(10), "18500")], Category.NUMBER_VARIATION, "Slash vs hyphen")
scenario("Leading zeros", [intra("PPK", "PP-7", A(11), "9200", 12)],
         [intra("PPK", "PP-0007", A(11), "9200", 12)], Category.NUMBER_VARIATION, "PP-7 vs PP-0007")
scenario("Date difference", [inter("BEL", "BEL-2101", A(12), "64000")],
         [inter("BEL", "BEL-2101", A(14), "64000")], Category.DATE_DIFFERENCE, "2 days apart")
scenario("Taxable value difference",
         [Doc("OSL", "OSL/310", A(13), "50000", cgst="4500", sgst="4500")],
         [Doc("OSL", "OSL/310", A(13), "50500", cgst="4500", sgst="4500")],
         Category.TAXABLE_DIFFERENCE, "Taxable differs by 500, tax agrees")
scenario("IGST difference", [Doc("GCH", "GCH-2201", A(14), "100000", igst="18000")],
         [Doc("GCH", "GCH-2201", A(14), "100000", igst="12000")], Category.IGST_DIFFERENCE, "18% booked, 12% reported")
scenario("CGST/SGST difference", [Doc("MSL", "MSL/233/25-26", A(15), "40000", cgst="3600", sgst="3600")],
         [Doc("MSL", "MSL/233/25-26", A(15), "40000", cgst="3400", sgst="3400")],
         Category.CGST_SGST_DIFFERENCE, "CGST and SGST each lower by 200")
scenario("Multiple differences", [intra("PPK", "PPK/480", A(16), "30000")],
         [intra("PPK", "PPK/480", A(18), "28000")], Category.MULTIPLE_DIFFERENCES, "Date and values differ")
scenario("Rounding within tolerance", [Doc("OSL", "OSL/322", A(17), "12345.60", cgst="1111.10", sgst="1111.10")],
         [Doc("OSL", "OSL/322", A(17), "12345.60", cgst="1111.60", sgst="1110.60")],
         Category.FULLY_MATCHED, "50 paise differences are within ₹1 tolerance")
scenario("Missing in GSTR-2B 1", [intra("MSL", "MSL/260/25-26", A(25), "22000")], [], Category.MISSING_IN_2B,
         "Supplier has not filed")
scenario("Missing in GSTR-2B 2", [inter("KTX", "KTX-2290", A(27), "75500", 12)], [], Category.MISSING_IN_2B,
         "Supplier has not filed")
scenario("Missing in books", [], [intra("OSL", "OSL/377", A(26), "8800")], Category.MISSING_IN_BOOKS,
         "Invoice not booked")
scenario("Missing in books (dated March)", [], [inter("BEL", "BEL-1950", date(2025, 3, 20), "15000")],
         Category.MISSING_IN_BOOKS, "Old invoice reported late; not in any books")
scenario("Duplicate in books", [intra("PPK", "PPK/455", A(19), "14000"), intra("PPK", "PPK/455", A(19), "14000")],
         [intra("PPK", "PPK/455", A(19), "14000")], Category.DUPLICATE_IN_BOOKS, "Entered twice in Tally")
scenario("Credit note matched", [inter("GCH", "GCH-CN-12", A(20), "5000", doc="CRN")],
         [inter("GCH", "GCH-CN-12", A(20), "5000", doc="CRN")], Category.FULLY_MATCHED,
         "Purchase return (Debit Note voucher in Tally)")
scenario("Credit note difference", [intra("MSL", "MSL-CN-07", A(21), "6000", doc="CRN")],
         [intra("MSL", "MSL-CN-07", A(21), "6500", doc="CRN")], Category.CDN_DIFFERENCE, "Credit note value differs")
scenario("Amended invoice", [intra("OSL", "OSL/45", A(5), "21000")],
         [intra("OSL", "OSL/45A", A(5), "21000", original_no="OSL/45", original_dt=A(5))], Category.AMENDED,
         "Supplier amended invoice number in B2BA")
scenario("Probable match (typo)", [inter("DOS", "DOS-1189", A(22), "11800")],
         [inter("DOS", "DOS-1198", A(22), "11800")], Category.PROBABLE, "Digits transposed – review")
scenario("GSTIN mismatch", [inter("MSK", "MSK-5501", A(23), "42000")],
         [intra("MSL", "MSK-5501", A(23), "42000")], Category.PROBABLE,
         "Booked under supplier's Karnataka GSTIN; supplier reported from Maharashtra registration")
scenario("ITC not available", [inter("KTX", "KTX-2301", A(24), "36000")],
         [inter("KTX", "KTX-2301", A(24), "36000", itc="No", reason="POS and supplier state are same but recipient state is different")],
         Category.FULLY_MATCHED, "Matched, but GSTR-2B marks ITC unavailable – at risk")

PRIOR_BOOKS = [inter("DOS", "DOS-1001", date(2025, 3, 28), "9500")]
PRIOR_IN_2B = [inter("DOS", "DOS-1001", date(2025, 3, 28), "9500")]
scenario("Previous-period invoice", [], PRIOR_IN_2B, Category.PREVIOUS_PERIOD,
         "Booked in March 2025, reflected in April GSTR-2B")
PRIOR_ONLY_BOOKS = [intra("MSL", "MSL/090/24-25", date(2025, 3, 15), "17000")]  # matched in March already

REJECTED_BOOK_ROWS = [
    {"name": "Local Hardware (URD)", "gstin": "", "no": "LH-55", "dt": "12-04-2025", "taxable": "2500",
     "why": "Unregistered supplier – no GSTIN"},
    {"name": "Pune Packaging Co", "gstin": SUPPLIERS["PPK"][0], "no": "PPK/499", "dt": "31-04-2025",
     "taxable": "4000", "why": "Invalid date 31-04-2025"},
]


def books_docs() -> list[Doc]:
    return [d for _n, b, _g, _c, _t in SCENARIOS for d in b]


def g2b_docs() -> list[Doc]:
    return [d for _n, _b, g, _c, _t in SCENARIOS for d in g]


# ---------------------------------------------------------------- writers
TALLY_HEADERS = [
    "Date", "Particulars", "Voucher Type", "Voucher No.", "Supplier Invoice No.", "Supplier Invoice Date",
    "GSTIN/UIN", "Gross Total", "Purchase @18%", "Purchase @12%", "Input CGST 9%", "Input SGST 9%",
    "Input CGST 6%", "Input SGST 6%", "Input IGST 18%", "Input IGST 12%",
]


def _tally_row(n: int, d: Doc, booking: date) -> list:
    sign = -1 if d.doc == "CRN" else 1
    vtype = {"INV": "Purchase", "CRN": "Debit Note", "DBN": "Credit Note"}[d.doc]
    tx, ig, cg, sg = (D(x) * sign for x in (d.taxable, d.igst, d.cgst, d.sgst))
    gross = tx + ig + cg + sg
    r18 = d.rate == 18
    gst, name = SUPPLIERS[d.sup]
    return [
        booking, name, vtype, n, d.no, d.dt, gst, gross,
        tx if r18 else None, None if r18 else tx,
        cg if r18 and cg else None, sg if r18 and sg else None,
        cg if not r18 and cg else None, sg if not r18 and sg else None,
        ig if r18 and ig else None, ig if not r18 and ig else None,
    ]


def write_tally_register(path: Path, docs: list[Doc], period_label: str, booking_month: tuple[int, int],
                         include_rejects: bool) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Purchase Register"
    ws.append([CLIENT["name"]])
    ws.append(["Purchase Register"])
    ws.append([period_label])
    ws.append([])
    ws.append(TALLY_HEADERS)
    for c in ws[5]:
        c.font = Font(bold=True)
    n = 0
    for d in docs:
        n += 1
        booking = date(booking_month[0], booking_month[1], min(max(d.dt.day, 1), 28)) \
            if (d.dt.year, d.dt.month) != booking_month else d.dt
        ws.append(_tally_row(n, d, booking))
    if include_rejects:
        for rj in REJECTED_BOOK_ROWS:
            n += 1
            tx = D(rj["taxable"])
            ws.append([date(*booking_month, 15), rj["name"], "Purchase", n, rj["no"], rj["dt"], rj["gstin"],
                       tx * D("1.18"), tx, None, tx * D("0.09"), tx * D("0.09"), None, None, None, None])
    last = ws.max_row
    ws.append(["Grand Total", None, None, None, None, None, None, f"=SUM(H6:H{last})"])
    for row in ws.iter_rows(min_row=6):
        for c in row:
            if isinstance(c.value, D):
                c.value = float(c.value)  # Excel stores numbers as binary floats, as Tally exports do
            if isinstance(c.value, date):
                c.number_format = "DD-MMM-YYYY"
    wb.save(path)


def write_custom_csv(path: Path, docs: list[Doc]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Vendor Name", "Vendor GSTIN", "Bill No", "Bill Date", "Document Type", "Taxable Amount",
                    "IGST Amount", "CGST Amount", "SGST Amount", "Cess Amount", "Total Amount"])
        for d in docs:
            gst, name = SUPPLIERS[d.sup]
            total = sum(D(x) for x in (d.taxable, d.igst, d.cgst, d.sgst, d.cess))
            dtype = {"INV": "Invoice", "CRN": "Credit Note", "DBN": "Debit Note"}[d.doc]
            w.writerow([name, gst, d.no, d.dt.strftime("%d/%m/%Y"), dtype, f"{D(d.taxable):,.2f}", d.igst, d.cgst,
                        d.sgst, d.cess, f"{total:.2f}"])
        for rj in REJECTED_BOOK_ROWS:
            w.writerow([rj["name"], rj["gstin"], rj["no"], rj["dt"].replace("-", "/"), "Invoice", rj["taxable"], 0,
                        D(rj["taxable"]) * D("0.09"), D(rj["taxable"]) * D("0.09"), 0, ""])


B2B_TOP = ["GSTIN of supplier", "Trade/Legal name", "Invoice details", None, None, None, "Place of supply",
           "Supply Attract Reverse Charge", "Taxable Value (₹)", "Tax Amount", None, None, None,
           "GSTR-1/IFF/GSTR-5 Period", "GSTR-1/IFF/GSTR-5 Filing Date", "ITC Availability", "Reason",
           "Applicable % of Tax Rate", "Source", "IRN", "IRN Date"]
B2B_SUB = [None, None, "Invoice number", "Invoice type", "Invoice Date", "Invoice Value(₹)", None, None, None,
           "Integrated Tax(₹)", "Central Tax(₹)", "State/UT Tax(₹)", "Cess(₹)"]
CDNR_TOP = ["GSTIN of supplier", "Trade/Legal name", "Credit note/Debit note details", None, None, None, None,
            "Place of supply", "Supply Attract Reverse Charge", "Taxable Value (₹)", "Tax Amount", None, None, None,
            "GSTR-1/IFF/GSTR-5 Period", "GSTR-1/IFF/GSTR-5 Filing Date", "ITC Availability", "Reason",
            "Applicable % of Tax Rate", "Source", "IRN", "IRN Date"]
CDNR_SUB = [None, None, "Note number", "Note type", "Note Supply type", "Note date", "Note Value (₹)", None, None,
            None, "Integrated Tax(₹)", "Central Tax(₹)", "State/UT Tax(₹)", "Cess(₹)"]
B2BA_TOP = ["Original Details", None, "GSTIN of supplier", "Trade/Legal name", "Invoice details", None, None, None,
            "Place of supply", "Supply Attract Reverse Charge", "Taxable Value (₹)", "Tax Amount", None, None, None,
            "GSTR-1/IFF/GSTR-5 Period", "GSTR-1/IFF/GSTR-5 Filing Date", "ITC Availability", "Reason"]
B2BA_SUB = ["Invoice number", "Invoice Date", None, None, "Invoice number", "Invoice type", "Invoice Date",
            "Invoice Value(₹)", None, None, None, "Integrated Tax(₹)", "Central Tax(₹)", "State/UT Tax(₹)", "Cess(₹)"]


def _value(d: Doc) -> D:
    return sum(D(x) for x in (d.taxable, d.igst, d.cgst, d.sgst, d.cess))


def _pos(d: Doc) -> str:
    return "27-Maharashtra"


def write_gstr2b_excel(path: Path, docs: list[Doc]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Read me"
    ws.append(["Goods and Services Tax - GSTR-2B"])
    ws.append(["Financial Year", "2025-26"])
    ws.append(["Tax Period", "April"])
    ws.append(["GSTIN", CLIENT["gstin"]])
    ws.append(["Legal Name", CLIENT["name"]])
    summary = wb.create_sheet("ITC Available")
    summary.append(["Summary of ITC available (computed on the portal)"])

    def sheet(title, top, sub, caption):
        s = wb.create_sheet(title)
        s.append([caption])
        s.append([])
        s.append([])
        s.append([])
        s.append(top)
        s.append(sub)
        return s

    b2b = sheet("B2B", B2B_TOP, B2B_SUB, "Taxable inward supplies received from registered persons")
    b2ba = sheet("B2BA", B2BA_TOP, B2BA_SUB, "Amendments to previously filed invoices by supplier")
    cdnr = sheet("B2B-CDNR", CDNR_TOP, CDNR_SUB, "Debit/Credit notes (Original)")
    for d in docs:
        gst, name = SUPPLIERS[d.sup]
        common_tail = [_pos(d), "No", float(D(d.taxable))]
        taxes = [float(D(x)) for x in (d.igst, d.cgst, d.sgst, d.cess)]
        filing = ["Apr'25" if d.dt.month == 4 else "Mar'25", "11-05-2025", d.itc, d.reason]
        if d.doc in ("CRN", "DBN"):
            cdnr.append([gst, name, d.no, "Credit Note" if d.doc == "CRN" else "Debit Note", "Regular",
                         d.dt.strftime("%d-%m-%Y"), float(_value(d)), *common_tail, *taxes, *filing, None, "", "",
                         ""])
        elif d.original_no:
            b2ba.append([d.original_no, d.original_dt.strftime("%d-%m-%Y"), gst, name, d.no, "Regular",
                         d.dt.strftime("%d-%m-%Y"), float(_value(d)), *common_tail, *taxes, *filing])
        else:
            b2b.append([gst, name, d.no, "Regular", d.dt.strftime("%d-%m-%Y"), float(_value(d)), *common_tail,
                        *taxes, *filing, None, "e-Invoice", "", ""])
    wb.save(path)


def write_gstr2b_json(path: Path, docs: list[Doc]) -> None:
    sections: dict[str, dict[str, list]] = {"b2b": {}, "b2ba": {}, "cdnr": {}}
    for d in docs:
        gst, name = SUPPLIERS[d.sup]
        amounts = {"txval": float(D(d.taxable)), "igst": float(D(d.igst)), "cgst": float(D(d.cgst)),
                   "sgst": float(D(d.sgst)), "cess": float(D(d.cess))}
        base = {"dt": d.dt.strftime("%d-%m-%Y"), "val": float(_value(d)), "pos": "27", "rev": "N",
                "itcavl": "Y" if d.itc == "Yes" else "N", "rsn": "P" if d.reason else "", "diffprcnt": 1,
                **amounts}
        if d.doc in ("CRN", "DBN"):
            sec, key = "cdnr", "nt"
            doc = {"ntnum": d.no, "typ": "C" if d.doc == "CRN" else "D", "suptyp": "R", **base}
        elif d.original_no:
            sec, key = "b2ba", "inv"
            doc = {"oinum": d.original_no, "oidt": d.original_dt.strftime("%d-%m-%Y"), "inum": d.no, "typ": "R",
                   **base}
        else:
            sec, key = "b2b", "inv"
            doc = {"inum": d.no, "typ": "R", **base}
        entry = sections[sec].setdefault(gst, {"ctin": gst, "trdnm": name, "supfildt": "11-05-2025",
                                                "supprd": "042025", key: []})
        entry[key].append(doc)
    payload = {"chksum": "demo", "data": {
        "gstin": CLIENT["gstin"], "rtnprd": "042025", "version": "1.0", "gendt": "14-05-2025",
        "docdata": {sec: list(v.values()) for sec, v in sections.items()},
    }}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_all(out_dir: str | Path) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "books_april": out / "tally_purchase_register_2025-04.xlsx",
        "books_march": out / "tally_purchase_register_2025-03.xlsx",
        "books_april_csv": out / "custom_purchase_register_2025-04.csv",
        "gstr2b_april": out / "gstr2b_2025-04.xlsx",
        "gstr2b_april_json": out / "gstr2b_2025-04.json",
    }
    write_tally_register(files["books_april"], books_docs(), "1-Apr-2025 to 30-Apr-2025", (2025, 4), True)
    write_tally_register(files["books_march"], PRIOR_BOOKS + PRIOR_ONLY_BOOKS, "1-Mar-2025 to 31-Mar-2025",
                         (2025, 3), False)
    write_custom_csv(files["books_april_csv"], books_docs())
    write_gstr2b_excel(files["gstr2b_april"], g2b_docs())
    write_gstr2b_json(files["gstr2b_april_json"], g2b_docs())
    lines = ["# Demo dataset – expected reconciliation outcome", "",
             f"Client: {CLIENT['name']} ({CLIENT['gstin']}), FY 2025-26, period April 2025.", "",
             "| # | Scenario | Expected category | Note |", "|---|---|---|---|"]
    for i, (name, _b, _g, cat, note) in enumerate(SCENARIOS, start=1):
        lines.append(f"| {i} | {name} | {cat.value} | {note} |")
    lines += ["", "Rows that must be rejected at import (books):", ""]
    lines += [f"* {r['no']}: {r['why']}" for r in REJECTED_BOOK_ROWS]
    (out / "EXPECTED_RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return files
