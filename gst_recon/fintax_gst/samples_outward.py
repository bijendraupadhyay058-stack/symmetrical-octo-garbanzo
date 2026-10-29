"""Outward demo data (April 2025): TallyPrime sales register and GSTR-1 JSON.

Scenarios: perfect B2B matches, an invoice not reported in GSTR-1, an invoice in
GSTR-1 missing from the sales register, a value difference, a wrong customer
GSTIN, a credit note, an SEZ supply, B2C sales (one under-reported in B2CS), an
export under LUT and an exempt supply. The GSTR-3B 3.1(a) tax is ₹3,600 lower
than GSTR-1, which the liability working reports as a possible short payment.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal as D
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

from .core.models import Category
from .samples import CLIENT, gstin

CUSTOMERS = {
    "RAJ": (gstin("27", "AABCR1122A"), "Rajlaxmi Retail Pvt Ltd"),
    "SHV": (gstin("27", "AAFFS3344B"), "Shivam Hardware"),
    "VEN": (gstin("29", "AACCV5566C"), "Venkatesh Traders"),
    "MPL": (gstin("24", "AADCM7788D"), "Mehta Polymers Ltd"),
    "SEZ": (gstin("27", "AAECS9900E"), "Pune SEZ Unit – Infotech Park"),
    "B2C": ("", "Cash sales"),
    "EXP": ("", "Gulf Imports LLC (Dubai)"),
}


@dataclass
class Sale:
    cust: str
    no: str
    dt: date
    taxable: str
    rate: int = 18
    inter: bool = False
    doc: str = "INV"
    supply: str = "Regular"


def A(day):
    return date(2025, 4, day)


def tax(s: Sale) -> dict[str, D]:
    t = (D(s.taxable) * D(s.rate) / D(100)).quantize(D("0.01"))
    if s.supply in ("Export (LUT)", "Exempt"):
        return {"igst": D(0), "cgst": D(0), "sgst": D(0)}
    if s.inter:
        return {"igst": t, "cgst": D(0), "sgst": D(0)}
    return {"igst": D(0), "cgst": t / 2, "sgst": t / 2}


# (scenario, in sales register, in GSTR-1, expected category for B2B documents or None for summary-level)
OUT_SCENARIOS: list[tuple[str, list[Sale], list[Sale], Category | None]] = []


def scenario(name, books, g1, expected):
    OUT_SCENARIOS.append((name, books, g1, expected))


for i, c in enumerate(["RAJ", "SHV", "RAJ", "VEN", "MPL"], start=1):
    s = Sale(c, f"SGT/25-26/{i:04d}", A(i + 2), f"{40000 + i * 5000}", inter=c in ("VEN", "MPL"))
    scenario(f"B2B perfect {i}", [s], [s], Category.FULLY_MATCHED)
scenario("Not reported in GSTR-1", [Sale("SHV", "SGT/25-26/0011", A(28), "20000")], [], Category.MISSING_IN_2B)
scenario("In GSTR-1, not in sales register", [], [Sale("RAJ", "SGT/25-26/0012", A(29), "10000")],
         Category.MISSING_IN_BOOKS)
scenario("Value difference", [Sale("VEN", "SGT/25-26/0013", A(15), "60000", inter=True)],
         [Sale("VEN", "SGT/25-26/0013", A(15), "66000", inter=True)], Category.MULTIPLE_DIFFERENCES)
scenario("Wrong customer GSTIN", [Sale("SHV", "SGT/25-26/0014", A(16), "18000")],
         [Sale("RAJ", "SGT/25-26/0014", A(16), "18000")], Category.PROBABLE)
scenario("Credit note", [Sale("RAJ", "SGT-CN/25-26/001", A(20), "5000", doc="CRN")],
         [Sale("RAJ", "SGT-CN/25-26/001", A(20), "5000", doc="CRN")], Category.FULLY_MATCHED)
scenario("SEZ supply with payment", [Sale("SEZ", "SGT/25-26/0015", A(21), "90000", inter=True, supply="SEZ with payment")],
         [Sale("SEZ", "SGT/25-26/0015", A(21), "90000", inter=True, supply="SEZ with payment")], Category.FULLY_MATCHED)
B2C_SALES = [Sale("B2C", f"CS/25-26/{i:03d}", A(i + 1), f"{4000 + i * 250}") for i in range(1, 9)]
scenario("B2C cash sales (one under-reported in B2CS)", B2C_SALES, B2C_SALES, None)
EXPORT = Sale("EXP", "EXP/25-26/001", A(24), "250000", inter=True, supply="Export (LUT)")
scenario("Export under LUT", [EXPORT], [EXPORT], None)
EXEMPT = Sale("SHV", "SGT/25-26/0016", A(25), "12000", supply="Exempt")
scenario("Exempt supply", [EXEMPT], [EXEMPT], None)
B2CS_UNDER_REPORTED = D("1000")  # taxable value missing from the B2CS row
SHORT_PAID_3B = D("3600")  # 3.1(a) tax paid less than GSTR-1


def sales_docs() -> list[Sale]:
    return [s for _n, b, _g, _c in OUT_SCENARIOS for s in b]


def gstr1_docs() -> list[Sale]:
    return [s for _n, _b, g, _c in OUT_SCENARIOS for s in g]


HEADERS = ["Date", "Particulars", "Voucher Type", "Voucher No.", "GSTIN/UIN", "Type of Supply", "Gross Total",
           "Sales @18%", "Sales @12%", "Output CGST 9%", "Output SGST 9%", "Output IGST 18%"]


def write_sales_register(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sales Register"
    for line in (CLIENT["name"], "Sales Register", "1-Apr-2025 to 30-Apr-2025", None):
        ws.append([line] if line else [])
    ws.append(HEADERS)
    for c in ws[5]:
        c.font = Font(bold=True)
    for s in sales_docs():
        g, name = CUSTOMERS[s.cust]
        sign = -1 if s.doc == "CRN" else 1
        t = {k: v * sign for k, v in tax(s).items()}
        tx = D(s.taxable) * sign
        vtype = {"INV": "Sales", "CRN": "Credit Note", "DBN": "Debit Note"}[s.doc]
        ws.append([s.dt, name, vtype, s.no, g or None, s.supply, float(tx + sum(t.values())), float(tx), None,
                   float(t["cgst"]) or None, float(t["sgst"]) or None, float(t["igst"]) or None])
    ws.append(["Grand Total"])
    wb.save(path)


def _itm(s: Sale) -> dict:
    t = tax(s)
    return {"num": 1, "itm_det": {"rt": s.rate, "txval": float(D(s.taxable)), "iamt": float(t["igst"]),
                                  "camt": float(t["cgst"]), "samt": float(t["sgst"]), "csamt": 0}}


def write_gstr1_json(path: Path) -> None:
    import json

    b2b: dict[str, dict] = {}
    cdnr: dict[str, dict] = {}
    b2cs: dict[tuple, dict] = {}
    exp, nil = [], []
    for s in gstr1_docs():
        g, _name = CUSTOMERS[s.cust]
        val = float(D(s.taxable) + sum(tax(s).values()))
        if s.supply == "Export (LUT)":
            exp.append({"inum": s.no, "idt": s.dt.strftime("%d-%m-%Y"), "val": val, "sbpcode": "INNSA1",
                        "sbnum": "4455667", "sbdt": "25-04-2025", "itms": [{"txval": float(D(s.taxable)), "rt": 0,
                                                                            "iamt": 0, "csamt": 0}]})
        elif s.supply == "Exempt":
            nil.append(D(s.taxable))
        elif not g:
            t = tax(s)
            key = ("INTRA", s.rate, "27")
            row = b2cs.setdefault(key, {"sply_ty": "INTRA", "rt": s.rate, "typ": "OE", "pos": "27", "txval": D(0),
                                        "iamt": D(0), "camt": D(0), "samt": D(0), "csamt": 0})
            row["txval"] += D(s.taxable)
            row["camt"] += t["cgst"]
            row["samt"] += t["sgst"]
        elif s.doc == "CRN":
            cdnr.setdefault(g, {"ctin": g, "nt": []})["nt"].append(
                {"ntty": "C", "nt_num": s.no, "nt_dt": s.dt.strftime("%d-%m-%Y"), "val": val, "pos": g[:2],
                 "rchrg": "N", "inv_typ": "R", "itms": [_itm(s)]})
        else:
            inv_typ = "SEWP" if s.supply.startswith("SEZ") else "R"
            b2b.setdefault(g, {"ctin": g, "inv": []})["inv"].append(
                {"inum": s.no, "idt": s.dt.strftime("%d-%m-%Y"), "val": val, "pos": g[:2], "rchrg": "N",
                 "inv_typ": inv_typ, "itms": [_itm(s)]})
    b2cs_rows = []
    for row in b2cs.values():  # one B2C invoice of ₹1,000 taxable is left out of the B2CS total
        cut = B2CS_UNDER_REPORTED * D(row["rt"]) / D(200)
        b2cs_rows.append({**row, "txval": float(row["txval"] - B2CS_UNDER_REPORTED),
                          "camt": float(row["camt"] - cut), "samt": float(row["samt"] - cut)})
    payload = {"gstin": CLIENT["gstin"], "fp": "042025", "b2b": list(b2b.values()), "cdnr": list(cdnr.values()),
               "b2cs": b2cs_rows, "exp": [{"exp_typ": "WOPAY", "inv": exp}],
               "nil": {"inv": [{"sply_ty": "INTRAB2B", "expt_amt": float(sum(nil)), "nil_amt": 0, "ngsup_amt": 0}]},
               "hsn": {"data": []}, "doc_issue": {"doc_det": []}}
    path.write_text(json.dumps(payload, indent=2, default=float), encoding="utf-8")


def gstr3b_31() -> dict[str, dict]:
    """Table 3.1 as filed for April 2025 (derived from GSTR-1, with 3.1(a) tax short by ₹3,600)."""
    a = {"txval": D(0), "iamt": D(0), "camt": D(0), "samt": D(0)}
    b = {"txval": D(0), "iamt": D(0)}
    c = D(0)
    for s in gstr1_docs():
        g, _ = CUSTOMERS[s.cust]
        t = tax(s)
        sign = -1 if s.doc == "CRN" else 1
        if s.supply == "Export (LUT)" or s.supply.startswith("SEZ"):
            b["txval"] += D(s.taxable)
            b["iamt"] += t["igst"]
        elif s.supply == "Exempt":
            c += D(s.taxable)
        else:
            a["txval"] += D(s.taxable) * sign
            a["iamt"] += t["igst"] * sign
            a["camt"] += t["cgst"] * sign
            a["samt"] += t["sgst"] * sign
    a["txval"] -= B2CS_UNDER_REPORTED
    a["camt"] -= B2CS_UNDER_REPORTED * D("0.09") + SHORT_PAID_3B / 2
    a["samt"] -= B2CS_UNDER_REPORTED * D("0.09") + SHORT_PAID_3B / 2
    f = lambda d: {k: float(d.get(k, 0)) for k in ("txval", "iamt", "camt", "samt")} | {"csamt": 0}  # noqa: E731
    return {"osup_det": f(a), "osup_zero": f(b), "osup_nil_exmp": {"txval": float(c)},
            "isup_rev": f({}), "osup_nongst": {"txval": 0}}


#: May 2025 GSTR-1: one new B2B invoice, the April value difference (SGT/25-26/0013, 66,000 reported
#: against 60,000 in the books) amended down through B2BA, and a B2CSA revising April's B2C total.
MAY_INVOICE = Sale("RAJ", "SGT/25-26/0021", date(2025, 5, 6), "30000")
AMENDED_0013 = Sale("VEN", "SGT/25-26/0013", A(15), "60000", inter=True)
ADVANCE_MAY = D("50000")  # advance received in May 2025 against a June supply (GSTR-1 Table 11A)


def write_gstr1_may_json(path: Path) -> None:
    import json

    g_raj, g_ven = CUSTOMERS["RAJ"][0], CUSTOMERS["VEN"][0]
    may = MAY_INVOICE
    amended = AMENDED_0013
    b2b = [{"ctin": g_raj, "inv": [{"inum": may.no, "idt": may.dt.strftime("%d-%m-%Y"),
                                    "val": float(D(may.taxable) + sum(tax(may).values())), "pos": "27",
                                    "rchrg": "N", "inv_typ": "R", "itms": [_itm(may)]}]}]
    b2ba = [{"ctin": g_ven, "inv": [{"oinum": amended.no, "oidt": amended.dt.strftime("%d-%m-%Y"),
                                     "inum": amended.no, "idt": amended.dt.strftime("%d-%m-%Y"),
                                     "val": float(D(amended.taxable) + sum(tax(amended).values())), "pos": "29",
                                     "rchrg": "N", "inv_typ": "R", "itms": [_itm(amended)]}]}]
    b2csa = [{"omon": "042025", "sply_ty": "INTRA", "pos": "27", "typ": "OE",
              "itms": [{"rt": 18, "txval": 41000.0, "iamt": 0, "camt": 3690.0, "samt": 3690.0, "csamt": 0}]}]
    at = [{"pos": "27", "sply_ty": "INTRA", "itms": [{"rt": 18, "ad_amt": float(ADVANCE_MAY), "iamt": 0,
                                                     "camt": float(ADVANCE_MAY * D("0.09")),
                                                     "samt": float(ADVANCE_MAY * D("0.09")), "csamt": 0}]}]
    payload = {"gstin": CLIENT["gstin"], "fp": "052025", "b2b": b2b, "b2ba": b2ba, "b2csa": b2csa, "at": at,
               "hsn": {"data": []}, "doc_issue": {"doc_det": []}}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_outward(out: Path) -> dict[str, Path]:
    files = {"sales_april": out / "tally_sales_register_2025-04.xlsx", "gstr1_april_json": out / "gstr1_2025-04.json",
             "gstr1_may_json": out / "gstr1_2025-05.json"}
    write_sales_register(files["sales_april"])
    write_gstr1_json(files["gstr1_april_json"])
    write_gstr1_may_json(files["gstr1_may_json"])
    return files
