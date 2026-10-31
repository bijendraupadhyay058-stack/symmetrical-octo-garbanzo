"""GSTR-3B draft for a month: Tables 3.1, 3.2, 4, 5 and 6.1 from the client's data, on one page.

* 3.1(a)(b)(c)(e) – the sales register (as in the GSTR-1 vs GSTR-3B working); 3.1(d) – purchases under reverse
  charge in the purchase register.
* 3.2 – inter-state supplies to unregistered persons, by place of supply.
* 4 – the ITC working (claim register, else purchase documents matched with GSTR-2B less blocked credit; GSTR-2B
  when the month is not reconciled).
* 5 – exempt / nil-rated / non-GST purchases (purchase documents without tax), inter- and intra-state.
* 6.1 – tax payable, the ITC set-off (see compliance/gstr3b_draft.py) and the cash to pay.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from ..compliance.gstr3b_draft import HEADS, Setoff, set_off
from ..compliance.tax_checks import pos_code
from ..core.gstin import STATE_CODES
from ..core.money import ZERO
from ..db.database import Database
from ..db.models import Client, Invoice
from ..importers.gstr3b import TABLE4, TABLE31, Gstr3bValues
from ..importers.parsing import parse_period
from ..outward.liability import sales_code
from .common import ServiceError, invoice_to_record


@dataclass
class Gstr3bDraft:
    client: str
    gstin: str
    period: str
    t31: dict[str, Gstr3bValues]
    t32: list[tuple[str, Decimal, Decimal]]  # (place of supply, taxable, IGST)
    t4: dict[str, Gstr3bValues]
    t4_basis: str
    t5: dict[str, Decimal]  # inter / intra-state exempt, nil, non-GST inward supplies
    setoff: Setoff
    notes: list[str] = field(default_factory=list)


def _add(a: Gstr3bValues, b: Gstr3bValues) -> Gstr3bValues:
    return Gstr3bValues(a.igst + b.igst, a.cgst + b.cgst, a.sgst + b.sgst, a.cess + b.cess, a.taxable + b.taxable)


class Gstr3bDraftService:
    def __init__(self, db: Database):
        self.db = db

    def draft(self, client_id: int, period: str, as_of: date | None = None) -> Gstr3bDraft:
        from .itc import ItcService
        from .outward import OutwardService

        p = parse_period(period)
        if not p:
            raise ServiceError(f"Invalid period {period} – use YYYY-MM")
        with self.db.session() as s:
            client = s.get(Client, client_id)
            if client is None:
                raise ServiceError(f"Client {client_id} not found")
            name, gstin, state = client.name, client.gstin, client.state_code
            sales = [invoice_to_record(r) for r in s.scalars(select(Invoice).where(
                Invoice.client_id == client_id, Invoice.source_type == "SALES", Invoice.period == p))]
            books = [invoice_to_record(r) for r in s.scalars(select(Invoice).where(
                Invoice.client_id == client_id, Invoice.source_type == "BOOKS", Invoice.period == p))]
        notes: list[str] = []
        if not sales:
            notes.append("No sales register for the month – Table 3.1 shows no outward supplies.")
        t31 = {c: Gstr3bValues() for c in TABLE31}
        if sales:
            w = OutwardService(self.db).liability(client_id, [p])[0]
            for c in ("31A", "31B", "31C", "31E"):
                t31[c] = w.row(c).sales
        rcm_missing = 0
        for b in books:
            if not b.reverse_charge:
                continue
            sign = -1 if b.doc_type.value == "CRN" else 1
            t31["31D"] = _add(t31["31D"], Gstr3bValues(sign * b.igst, sign * b.cgst, sign * b.sgst, sign * b.cess,
                                                       sign * b.taxable))
            rcm_missing += (b.igst + b.cgst + b.sgst) == 0
        if rcm_missing:
            notes.append(f"{rcm_missing} reverse-charge purchase(s) carry no tax in the register – add the tax at the "
                         "applicable rate to 3.1(d) (e.g. GTA 5 %) and to 4(A)(3).")
        # 3.2 – inter-state B2C, by place of supply
        t32: dict[str, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO])
        for r in sales:
            if r.supplier_gstin or sales_code(r) != "31A":
                continue
            pos = pos_code(r.place_of_supply)
            if pos and pos != state:
                sign = -1 if r.doc_type.value == "CRN" else 1
                t32[pos][0] += sign * r.taxable
                t32[pos][1] += sign * r.igst
        # 4 – ITC
        work = ItcService(self.db).table4(client_id, [p], as_of)[0]
        t4 = {row.code: row.books for row in work.rows}
        basis = work.books_basis
        if all(v.total == 0 for k, v in t4.items() if k != "4C") and any(r.auto_2b.total for r in work.rows):
            t4 = {row.code: row.auto_2b for row in work.rows}
            basis = "GSTR-2B (the month is not reconciled – reconcile for the ITC as per books)"
            notes.append("ITC is taken from GSTR-2B because the month is not reconciled.")
        if t31["31D"].total == 0 and t4["4A3"].total > 0:
            # bills GSTR-2B shows under reverse charge, not marked so in the register: their tax is payable too
            a3 = t4["4A3"]
            t31["31D"] = Gstr3bValues(a3.igst, a3.cgst, a3.sgst, a3.cess, t31["31D"].taxable)
            notes.append("Reverse-charge tax in 3.1(d) is taken as the ITC claimed in 4(A)(3) (bills shown under "
                         "reverse charge in GSTR-2B) – mark them as reverse charge in the purchase register and check "
                         "the taxable value.")
        elif t4["4A3"].total == 0 and t31["31D"].total > 0:
            t4["4A3"] = Gstr3bValues(t31["31D"].igst, t31["31D"].cgst, t31["31D"].sgst, t31["31D"].cess)
            a = [t4[c] for c in ("4A1", "4A2", "4A3", "4A4", "4A5")]
            b_ = [t4[c] for c in ("4B1", "4B2")]
            net = Gstr3bValues()
            for v in a:
                net = _add(net, v)
            for v in b_:
                net = Gstr3bValues(net.igst - v.igst, net.cgst - v.cgst, net.sgst - v.sgst, net.cess - v.cess)
            t4["4C"] = net
            notes.append("ITC on reverse-charge purchases (4(A)(3)) is taken as the tax paid under 3.1(d) – check "
                         "that it is eligible.")
        # 5 – exempt / nil / non-GST inward supplies
        t5 = {"inter": ZERO, "intra": ZERO}
        for b in books:
            if b.reverse_charge or (b.igst + b.cgst + b.sgst + b.cess) != 0:
                continue
            sign = -1 if b.doc_type.value == "CRN" else 1
            t5["inter" if b.supplier_gstin[:2] != state else "intra"] += sign * b.taxable
        credit = {h: getattr(t4["4C"], h) for h in HEADS}
        # a negative net credit (reversals above the credit of the month) is tax payable
        liability = {h: getattr(t31["31A"], h) + getattr(t31["31B"], h) + max(-credit[h], ZERO) for h in HEADS}
        rcm = {h: getattr(t31["31D"], h) for h in HEADS}
        so = set_off(liability, credit, rcm)
        if any(v < 0 for v in credit.values()):
            notes.append("Net ITC of a head is negative (reversals exceed the credit of the month) – the excess is "
                         "added to the tax payable; check Table 4.")
        return Gstr3bDraft(name, gstin, p, t31, sorted((k, v[0], v[1]) for k, v in t32.items()), t4, basis, t5, so,
                           notes)


def state_label(code: str) -> str:
    return f"{code}-{STATE_CODES.get(code, '')}"


__all__ = ["Gstr3bDraft", "Gstr3bDraftService", "TABLE4", "TABLE31", "state_label"]
