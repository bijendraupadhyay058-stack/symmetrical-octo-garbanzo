"""GSTR-9 Tables 4, 5, 6, 7 and 9, built from data already imported for the year.

Sources and limits (all shown in the working):

* **Tables 4 and 5** come from GSTR-1. B2B and CDNR are classified document by document,
  because the invoice-level records carry the supply type: regular, SEZ with or without
  payment, deemed export, reverse charge, credit or debit note. B2C, exports, nil,
  exempt and non-GST supplies and unregistered notes come from GSTR-1 section totals.
  Each row also shows the sales register, classified the same way.
* **Amendments (4K/4L, 5J/5K)**: an amended B2B or CDNR document is compared with its
  original when that original was imported. The difference is an increase or a
  decrease. Amendments whose original isn't available, and the summary-level amendment
  sections (B2CSA, B2CLA, EXPA, CDNURA), are listed for manual entry and never guessed.
* **4F** (advances) is the net of GSTR-1 Table 11A (advances received) and 11B (advances
  adjusted) for the year.
* **4G** (inward supplies under reverse charge) comes from GSTR-3B 3.1(d).
* **Tables 6 and 7** come from GSTR-3B Table 4. GSTR-3B does not split 4(A)(5) into
  inputs, capital goods and input services, nor 4(A)(3) into supplies from registered
  and unregistered persons. Those rows carry the combined figure with a note.
* **Table 9** compares the tax payable per Table 4 with the tax declared in GSTR-3B
  Table 3.1 and the tax paid in cash and through ITC per GSTR-3B Table 6.1.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from ..core.invoice_no import normalize_invoice_no
from ..core.models import DocType, InvoiceRecord
from ..importers.gstr3b import Gstr3bValues

V = Gstr3bValues

TABLE4_ROWS = [
    ("4A", "Supplies made to un-registered persons (B2C)"),
    ("4B", "Supplies made to registered persons (B2B)"),
    ("4C", "Zero rated supply (export) on payment of tax (except supplies to SEZs)"),
    ("4D", "Supply to SEZs on payment of tax"),
    ("4E", "Deemed exports"),
    ("4F", "Advances on which tax has been paid but invoice has not been issued"),
    ("4G", "Inward supplies on which tax is to be paid on reverse charge basis"),
    ("4H", "Sub-total (A to G above)"),
    ("4I", "Credit notes issued in respect of transactions specified in (B) to (E) above (−)"),
    ("4J", "Debit notes issued in respect of transactions specified in (B) to (E) above (+)"),
    ("4K", "Supplies / tax declared through amendments (+)"),
    ("4L", "Supplies / tax reduced through amendments (−)"),
    ("4M", "Sub-total (I to L above)"),
    ("4N", "Supplies and advances on which tax is to be paid (H + M) above"),
]
TABLE5_ROWS = [
    ("5A", "Zero rated supply (export) without payment of tax"),
    ("5B", "Supply to SEZs without payment of tax"),
    ("5C", "Supplies on which tax is to be paid by the recipient on reverse charge basis"),
    ("5D", "Exempted"),
    ("5E", "Nil rated"),
    ("5F", "Non-GST supply (includes 'no supply')"),
    ("5G", "Sub-total (A to F above)"),
    ("5H", "Credit notes issued in respect of transactions specified in A to F above (−)"),
    ("5I", "Debit notes issued in respect of transactions specified in A to F above (+)"),
    ("5J", "Supplies declared through amendments (+)"),
    ("5K", "Supplies reduced through amendments (−)"),
    ("5L", "Sub-total (H to K above)"),
    ("5M", "Turnover on which tax is not to be paid (G + L above)"),
    ("5N", "Total turnover (including advances) (4N + 5M − 4G above)"),
]
TABLE6_ROWS = [
    ("6A", "Total amount of input tax credit availed through GSTR-3B (sum total of Table 4A of GSTR-3B)",
     ("4A1", "4A2", "4A3", "4A4", "4A5")),
    ("6B", "Inward supplies (other than imports and inward supplies liable to reverse charge) – inputs, "
           "capital goods and input services together (GSTR-3B 4(A)(5))", ("4A5",)),
    ("6C+6D", "Inward supplies received from unregistered and registered persons liable to reverse charge "
              "(GSTR-3B 4(A)(3))", ("4A3",)),
    ("6E", "Import of goods (including supplies from SEZs) (GSTR-3B 4(A)(1))", ("4A1",)),
    ("6F", "Import of services (excluding inward supplies from SEZs) (GSTR-3B 4(A)(2))", ("4A2",)),
    ("6G", "Input tax credit received from ISD (GSTR-3B 4(A)(4))", ("4A4",)),
    ("6H", "Amount of ITC reclaimed (other than B above) under the provisions of the Act (GSTR-3B 4(D)(1))",
     ("4D1",)),
]
TABLE7_ROWS = [
    ("7A–7G", "Reversals under rules 37, 39, 42, 43 and section 17(5) (GSTR-3B 4(B)(1))", ("4B1",)),
    ("7H", "Other reversals (GSTR-3B 4(B)(2))", ("4B2",)),
]
LABELS = dict(TABLE4_ROWS + TABLE5_ROWS + [(c, lab) for c, lab, _ in TABLE6_ROWS + TABLE7_ROWS] + [
    ("6I", "Sub-total (B to H above)"), ("6J", "Difference (I − A above)"),
    ("7I", "Total ITC reversed (sum of A to H above)"), ("7J", "Net ITC available for utilisation (6O − 7I)")])
_EXPORT = re.compile(r"exp|wpay|wopay|lut|bond", re.IGNORECASE)


def _vals(r: InvoiceRecord) -> V:
    return V(r.igst, r.cgst, r.sgst, r.cess, r.taxable)


def _scale(v: V, k: int) -> V:
    return V(v.igst * k, v.cgst * k, v.sgst * k, v.cess * k, v.taxable * k)


def _abs(v: V) -> V:
    return _scale(v, -1) if (v.taxable < 0 or (v.taxable == 0 and v.total < 0)) else v


@dataclass
class Row:
    code: str
    gstr1: V | None = None  # GSTR-1 (Tables 4–5) or GSTR-3B (Tables 6–7)
    books: V | None = None  # sales register (Tables 4–5)
    note: str = ""

    @property
    def label(self) -> str:
        return LABELS.get(self.code, self.code)

    @property
    def diff(self) -> V | None:
        if self.gstr1 is None or self.books is None:
            return None
        return self.books - self.gstr1


@dataclass
class Tax9:
    """GSTR-9 Table 9 for one tax head."""

    head: str
    payable: Decimal  # per Table 4N (GSTR-1 basis)
    declared: Decimal | None  # GSTR-3B 3.1(a)+(b)+(d)
    paid_cash: Decimal | None  # GSTR-3B 6.1
    paid_itc: Decimal | None

    @property
    def paid(self) -> Decimal | None:
        return None if self.paid_cash is None else self.paid_cash + (self.paid_itc or Decimal(0))

    @property
    def unpaid(self) -> Decimal | None:
        """Payable per Table 4 not paid through GSTR-3B (positive = short paid)."""
        return None if self.paid is None else self.payable - self.paid


@dataclass
class Gstr9Working:
    fy: str
    table4: list[Row] = field(default_factory=list)
    table5: list[Row] = field(default_factory=list)
    table6: list[Row] = field(default_factory=list)
    table7: list[Row] = field(default_factory=list)
    table9: list["Tax9"] = field(default_factory=list)
    interest_paid: Decimal | None = None  # GSTR-3B 6.1 interest paid in cash (None = not imported)
    late_fee_paid: Decimal | None = None
    advances_imported: bool = False
    amendments: list[dict] = field(default_factory=list)  # resolved and unresolved amendment lines
    notes: list[str] = field(default_factory=list)
    periods_gstr1: list[str] = field(default_factory=list)
    periods_3b: list[str] = field(default_factory=list)

    def row(self, code: str) -> Row:
        return next(r for r in self.table4 + self.table5 + self.table6 + self.table7 if r.code == code)


# ------------------------------------------------------------ classification
def classify_gstr1_doc(r: InvoiceRecord) -> str:
    """Table 4/5 row of a GSTR-1 B2B / CDNR document (not an amendment)."""
    st = (r.supply_type or "").upper()
    rcm = r.reverse_charge or "REVERSE" in st
    zero_tax = r.total_tax == 0
    if r.doc_type == DocType.CREDIT_NOTE:
        return "5H" if (rcm or zero_tax) else "4I"
    if r.doc_type == DocType.DEBIT_NOTE:
        return "5I" if (rcm or zero_tax) else "4J"
    if rcm:
        return "5C"
    if st.startswith("SEZ") or st in ("SEWP", "SEWOP"):
        return "5B" if zero_tax else "4D"
    if st == "DE" or "DEEMED" in st:
        return "4E"
    return "4B"


def classify_sale(r: InvoiceRecord) -> str:
    """Table 4/5 row of a sales register document."""
    st = (r.supply_type or "").lower()
    zero_tax = r.total_tax == 0
    if r.doc_type == DocType.CREDIT_NOTE:
        return "5H" if zero_tax or r.reverse_charge else "4I"
    if r.doc_type == DocType.DEBIT_NOTE:
        return "5I" if zero_tax or r.reverse_charge else "4J"
    if r.reverse_charge or "reverse" in st:
        return "5C"
    if "sez" in st:
        return "5B" if zero_tax else "4D"
    if "deemed" in st:
        return "4E"
    if _EXPORT.search(st):
        return "5A" if zero_tax else "4C"
    if re.search(r"non.?gst", st):
        return "5F"
    if "exempt" in st:
        return "5D"
    if "nil" in st:
        return "5E"
    return "4B" if r.supplier_gstin else "4A"


def classify_summary(section: str, supply: str, v: V) -> str | None:
    """Table 4/5 row of a GSTR-1 section total that has no invoice-level record."""
    section, supply = section.upper(), supply.upper()
    if section in ("B2CS", "B2CL"):
        return "4A"
    if section == "EXP":
        return "5A" if supply == "WOPAY" or v.total == 0 else "4C"
    if section == "CDNUR":
        negative = v.taxable < 0 or (v.taxable == 0 and v.total < 0)
        zero_tax = v.total == 0
        return ("5H" if zero_tax else "4I") if negative else ("5I" if zero_tax else "4J")
    return {"NIL": "5E", "EXEMPT": "5D", "NONGST": "5F"}.get(section)


SUMMARY_AMENDMENTS = {"B2CSA", "B2CLA", "EXPA", "CDNURA", "ATA", "TXPDA"}
DOC_SECTIONS = {"B2B", "B2BA", "CDNR", "CDNRA"}  # invoice-level records exist for these


# ------------------------------------------------------------------ builder
def build_gstr9(fy: str, months: list[str], summaries: list[dict], gstr1_docs: list[InvoiceRecord],
                sales: list[InvoiceRecord], filed: dict[str, dict[str, V]]) -> Gstr9Working:
    w = Gstr9Working(fy)
    g1: dict[str, V] = {}
    bk: dict[str, V] = {}

    def add(target: dict, code: str, v: V) -> None:
        target[code] = target.get(code, V()) + _abs(v)

    w.periods_gstr1 = sorted({s["period"] for s in summaries} | {r.period for r in gstr1_docs})
    w.periods_3b = sorted(p for p in filed if p in months)
    originals = {}
    for r in gstr1_docs:
        if not r.is_amendment:
            originals[(r.supplier_gstin, r.doc_type, r.invoice_no_norm)] = r
            add(g1, classify_gstr1_doc(r), _vals(r))
    for r in gstr1_docs:
        if not r.is_amendment:
            continue
        orig_no = normalize_invoice_no(r.original_invoice_no or r.invoice_no)
        orig = originals.get((r.supplier_gstin, r.doc_type, orig_no))
        code_up, code_down = ("5J", "5K") if r.total_tax == 0 or classify_gstr1_doc(r).startswith("5") else \
            ("4K", "4L")
        if orig is None:
            w.amendments.append({"period": r.period, "section": "B2BA" if r.doc_type == DocType.INVOICE else
                                 "CDNRA", "party": r.supplier_gstin, "document": r.invoice_no,
                                 "original": r.original_invoice_no, "revised": _vals(r), "delta": None,
                                 "row": f"{code_up}/{code_down}", "status": "original not imported – enter manually"})
            continue
        sign = -1 if r.doc_type == DocType.CREDIT_NOTE else 1  # a larger credit note reduces supplies
        delta = _scale(_vals(r) - _vals(orig), sign)
        increase = delta.taxable > 0 or (delta.taxable == 0 and delta.total > 0)
        code = code_up if increase else code_down
        if delta.taxable or delta.total:
            add(g1, code, delta)
        w.amendments.append({"period": r.period, "section": "B2BA" if r.doc_type == DocType.INVOICE else "CDNRA",
                             "party": r.supplier_gstin, "document": r.invoice_no, "original": orig.invoice_no,
                             "revised": _vals(r), "delta": delta, "row": code, "status": "included"})
    for s in summaries:
        section = s["section"].upper()
        if section in DOC_SECTIONS:
            continue
        v = V(s["igst"], s["cgst"], s["sgst"], s["cess"], s["taxable"])
        if section in SUMMARY_AMENDMENTS:
            w.amendments.append({"period": s["period"], "section": section, "party": s.get("pos", ""),
                                 "document": f"{section} total", "original": "", "revised": v, "delta": None,
                                 "row": "4K/4L" if v.total else "5J/5K",
                                 "status": "revised totals only – enter the change manually"})
            continue
        if section in ("AT", "TXPD"):  # Table 11A advances received (+), 11B advances adjusted (−)
            g1["4F"] = g1.get("4F", V()) + v
            w.advances_imported = True
            continue
        code = classify_summary(section, s.get("supply", ""), v)
        if code:
            add(g1, code, v)
    for r in sales:
        add(bk, classify_sale(r), _vals(r))
    rcm_in = V()
    for p in w.periods_3b:
        rcm_in = rcm_in + filed[p].get("31D", V())
    g1["4G"] = rcm_in

    def table(rows, target_rows):
        for code, _label in rows:
            target_rows.append(Row(code, g1.get(code, V()), bk.get(code, V()) if code not in ("4G",) else None))

    table(TABLE4_ROWS, w.table4)
    table(TABLE5_ROWS, w.table5)
    r = {x.code: x for x in w.table4 + w.table5}
    for side in ("gstr1", "books"):
        def total(codes, signs=None, side=side):
            acc = V()
            for c, k in zip(codes, signs or [1] * len(codes)):
                acc = acc + _scale(getattr(r[c], side) or V(), k)
            return acc

        sub = {"4H": total(["4A", "4B", "4C", "4D", "4E", "4F", "4G"]),
               "4M": total(["4I", "4J", "4K", "4L"], [-1, 1, 1, -1]),
               "5G": total(["5A", "5B", "5C", "5D", "5E", "5F"]),
               "5L": total(["5H", "5I", "5J", "5K"], [-1, 1, 1, -1])}
        sub["4N"] = sub["4H"] + sub["4M"]
        sub["5M"] = sub["5G"] + sub["5L"]
        sub["5N"] = V(taxable=sub["4N"].taxable + sub["5M"].taxable - (getattr(r["4G"], side) or V()).taxable)
        for code, v in sub.items():
            setattr(r[code], side, v)
    r["4F"].note = ("Net of advances received (11A) and adjusted (11B) in GSTR-1" if w.advances_imported else
                    "No GSTR-1 advance tables (11A/11B) imported")
    r["4F"].books = None
    r["4G"].note = "From GSTR-3B 3.1(d) of the year's periods"
    for code in ("4K", "4L", "5J", "5K"):
        r[code].books = None
        r[code].note = "Amendments of the year's GSTR-1 (see the amendments list)"

    # Tables 6 and 7 from GSTR-3B Table 4
    def from_3b(codes):
        acc = V()
        for p in w.periods_3b:
            for c in codes:
                acc = acc + filed[p].get(c, V())
        return acc

    for code, _label, codes in TABLE6_ROWS:
        w.table6.append(Row(code, from_3b(codes)))
    six_i = V()
    for x in w.table6[1:]:
        six_i = six_i + x.gstr1
    w.table6.append(Row("6I", six_i))
    w.table6.append(Row("6J", six_i - w.table6[0].gstr1))
    w.table6[1].note = "GSTR-3B does not split inputs, capital goods and input services – split from the books"
    w.table6[2].note = "GSTR-3B does not split unregistered (6C) and registered (6D) suppliers"
    for code, _label, codes in TABLE7_ROWS:
        w.table7.append(Row(code, from_3b(codes)))
    seven_i = w.table7[0].gstr1 + w.table7[1].gstr1
    w.table7.append(Row("7I", seven_i))
    w.table7.append(Row("7J", six_i - seven_i, note="6O is taken as 6I (no transition credit)"))
    w.table7[0].note = "GSTR-3B does not split the reversal by rule – split from the reversal register"

    # Table 9: tax payable per Table 4 vs declared in GSTR-3B 3.1(a)+(b)+(d) vs paid (GSTR-3B 6.1)
    payable = r["4N"].gstr1
    declared, cash, itc, interest, fee = V(), V(), V(), V(), V()
    paid_periods = [p for p in w.periods_3b if any(c in filed[p] for c in ("61CASH", "61ITC"))]
    for p in w.periods_3b:
        for c in ("31A", "31B", "31D"):
            declared = declared + filed[p].get(c, V())
        cash = cash + filed[p].get("61CASH", V())
        itc = itc + filed[p].get("61ITC", V())
        interest = interest + filed[p].get("61INT", V())
        fee = fee + filed[p].get("61FEE", V())
    have_3b, have_paid = bool(w.periods_3b), bool(paid_periods)
    for head in ("igst", "cgst", "sgst", "cess"):
        w.table9.append(Tax9(head.upper(), getattr(payable, head), getattr(declared, head) if have_3b else None,
                             getattr(cash, head) if have_paid else None, getattr(itc, head) if have_paid else None))
    if have_paid:
        w.interest_paid, w.late_fee_paid = interest.total, fee.total

    missing_g1 = [m for m in months if m not in w.periods_gstr1]
    missing_3b = [m for m in months if m not in w.periods_3b]
    if missing_g1:
        w.notes.append(f"GSTR-1 not imported for {len(missing_g1)} month(s): {', '.join(missing_g1)} – Tables 4 "
                       "and 5 are incomplete.")
    if missing_3b:
        w.notes.append(f"GSTR-3B not imported for {len(missing_3b)} month(s): {', '.join(missing_3b)} – Tables 4G, "
                       "6, 7 and 9 are incomplete.")
    unresolved = [a for a in w.amendments if a["delta"] is None]
    if unresolved:
        w.notes.append(f"{len(unresolved)} amendment(s) need the change from the original entered manually.")
    w.notes.append("Amendments made in the next financial year's returns (up to November) are not included.")
    unpaid_months = [p for p in w.periods_3b if p not in paid_periods]
    if not paid_periods:
        w.notes.append("Payment of tax (GSTR-3B Table 6.1) is not imported: Table 9 compares the tax payable with "
                       "the tax declared in GSTR-3B, not with the tax paid.")
    elif unpaid_months:
        w.notes.append(f"GSTR-3B Table 6.1 (payment) not imported for {', '.join(unpaid_months)} – tax paid in "
                       "Table 9 is incomplete.")
    if not w.advances_imported:
        w.notes.append("No GSTR-1 advance tables (11A/11B) imported – 4F is shown as nil.")
    return w
