"""Composition scheme (CMP-08 quarterly, GSTR-4 annual) and QRMP helpers (IFF, PMT-06 monthly payment).

Composition: tax = rate × turnover of the quarter (sales register), half CGST and half SGST, plus the tax on
inward supplies under reverse charge (purchase register marked RCM and the RCM register). Rates: traders and
manufacturers 1 %, restaurants 5 %, suppliers of services / mixed supplies under section 10(2A) 6 %.

QRMP: in the first two months of a quarter the client may furnish B2B invoices in the IFF (up to ₹50 lakh a
month) and pays tax by the 25th in PMT-06, either
* fixed sum – 35 % of the tax paid in cash in the last quarter's GSTR-3B (or the whole of the last month's cash
  if the previous quarter was filed monthly), or
* self-assessment – the month's actual tax less ITC (as the GSTR-3B draft of the month works it out).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select

from ..core.models import DocType, Source
from ..core.money import ZERO
from ..db.database import Database
from ..db.models import AppSetting, Client, Invoice
from ..importers.parsing import parse_period
from .common import ServiceError, audit

PAISA = Decimal("0.01")
CATEGORIES = {"trader": ("Trader", Decimal("1")), "manufacturer": ("Manufacturer", Decimal("1")),
              "restaurant": ("Restaurant (no alcohol)", Decimal("5")),
              "services": ("Services / mixed supply – section 10(2A)", Decimal("6"))}
IFF_LIMIT = Decimal("5000000")
HEADS = ("igst", "cgst", "sgst", "cess")


def _q(v: Decimal) -> Decimal:
    return v.quantize(PAISA, rounding=ROUND_HALF_UP)


def quarter_months(period: str) -> list[str]:
    y, m = int(period[:4]), int(period[5:])
    start = ((m - 1) // 3) * 3 + 1
    return [f"{y}-{k:02d}" for k in range(start, start + 3)]


def quarter_label(period: str) -> str:
    months = quarter_months(period)
    return f"{date(int(months[0][:4]), int(months[0][5:]), 1):%b} – {date(int(months[2][:4]), int(months[2][5:]), 1):%b %Y}"


@dataclass
class Cmp08:
    quarter: str
    category: str
    rate: Decimal
    turnover: Decimal
    tax_outward: dict[str, Decimal]
    tax_rcm: dict[str, Decimal]
    months: list[str]
    notes: list[str] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return sum(self.tax_outward.values(), ZERO) + sum(self.tax_rcm.values(), ZERO)


@dataclass
class Pmt06:
    period: str
    fixed_sum: dict[str, Decimal] | None
    fixed_basis: str
    self_assessed: dict[str, Decimal] | None
    iff_docs: int = 0
    iff_value: Decimal = ZERO
    notes: list[str] = field(default_factory=list)

    @property
    def iff_over_limit(self) -> bool:
        return self.iff_value > IFF_LIMIT


class CompositionService:
    def __init__(self, db: Database):
        self.db = db

    def category(self, client_id: int) -> str | None:
        with self.db.session() as s:
            row = s.get(AppSetting, f"composition:{client_id}")
            return json.loads(row.value_json).get("category") if row else None

    def set_category(self, client_id: int, category: str | None, user: str | None = None) -> None:
        if category is not None and category not in CATEGORIES:
            raise ServiceError(f"Unknown composition category {category}")
        with self.db.session() as s:
            key = f"composition:{client_id}"
            row = s.get(AppSetting, key)
            if category is None:
                if row is not None:
                    s.delete(row)
            else:
                if row is None:
                    row = AppSetting(key=key, value_json="{}")
                    s.add(row)
                row.value_json = json.dumps({"category": category})
            audit(s, "SETTING", "app_settings", key, {"category": category}, user, client_id)

    # ------------------------------------------------------------ CMP-08
    def cmp08(self, client_id: int, period: str) -> Cmp08:
        from .rcm import RcmService

        p = parse_period(period)
        if not p:
            raise ServiceError(f"Invalid period {period} – use YYYY-MM")
        cat = self.category(client_id)
        if cat is None:
            raise ServiceError("Mark the client as a composition dealer first (choose its category)")
        label, rate = CATEGORIES[cat]
        months = quarter_months(p)
        with self.db.session() as s:
            sales = list(s.scalars(select(Invoice).where(Invoice.client_id == client_id, Invoice.source_type == "SALES",
                                                         Invoice.period.in_(months))))
        turnover = ZERO
        for r in sales:
            turnover += -r.taxable if r.doc_type == DocType.CREDIT_NOTE.value else r.taxable
        half = _q(turnover * rate / 200)
        out = {"igst": ZERO, "cgst": half, "sgst": half, "cess": ZERO}
        rcm = {h: ZERO for h in HEADS}
        svc = RcmService(self.db)
        for m in months:
            reg = svc.month(client_id, m).register_total()
            for h in HEADS:
                rcm[h] += getattr(reg, h)
        res = Cmp08(f"{months[0]}..{months[2]}", label, rate, turnover, out, rcm, months)
        if not sales:
            res.notes.append("No sales register for the quarter – turnover is nil.")
        if cat == "trader":
            res.notes.append("Traders: tax is on the turnover of taxable supplies – remove exempt supplies from the "
                             "turnover if the register includes them.")
        res.notes.append("CMP-08 is due by the 18th of the month after the quarter; tax is paid in cash (no ITC).")
        return res

    def gstr4(self, client_id: int, fy: str) -> dict:
        """GSTR-4 annual summary: the four quarters' CMP-08 figures and inward supplies from registered persons."""
        from ..itc.annual import fy_months
        from .itc import ItcService

        quarters = [self.cmp08(client_id, m) for m in fy_months(fy)[2::3]]
        with self.db.session() as s:
            books = ItcService(self.db)._docs(s, client_id, Source.BOOKS, fy_months(fy))
        inward_taxable = inward_tax = ZERO
        for b in books:
            k = -1 if b.doc_type == DocType.CREDIT_NOTE else 1
            inward_taxable += k * b.taxable
            inward_tax += k * (b.igst + b.cgst + b.sgst + b.cess)
        return {"quarters": quarters, "turnover": sum((q.turnover for q in quarters), ZERO),
                "tax": sum((q.total for q in quarters), ZERO), "inward_taxable": inward_taxable,
                "inward_tax": inward_tax}

    # ------------------------------------------------------------- QRMP
    def pmt06(self, client_id: int, period: str) -> Pmt06:
        from .gstr3b import Gstr3bService
        from .gstr3b_draft import Gstr3bDraftService

        p = parse_period(period)
        if not p:
            raise ServiceError(f"Invalid period {period} – use YYYY-MM")
        months = quarter_months(p)
        if p == months[2]:
            raise ServiceError(f"{p} is the last month of the quarter – the tax is paid with the quarterly GSTR-3B, "
                               "not in PMT-06")
        with self.db.session() as s:
            if s.get(Client, client_id) is None:
                raise ServiceError(f"Client {client_id} not found")
        y, m = int(months[0][:4]), int(months[0][5:])
        prev_end = f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"
        prev_q = quarter_months(prev_end)
        filed = Gstr3bService(self.db).values(client_id, prev_q)
        fixed, basis = None, ""
        if prev_end in filed and "61CASH" in filed[prev_end]:
            cash = filed[prev_end]["61CASH"]
            months_filed = [k for k in prev_q if k in filed]
            if len(months_filed) == 1:  # quarterly return
                fixed = {h: _q(getattr(cash, h) * Decimal("0.35")) for h in HEADS}
                basis = f"35 % of the tax paid in cash in the GSTR-3B for {prev_q[0]}..{prev_end}"
            else:
                fixed = {h: getattr(cash, h) for h in HEADS}
                basis = f"the tax paid in cash in the GSTR-3B for {prev_end} (previous quarter filed monthly)"
        res = Pmt06(p, fixed, basis, None)
        if fixed is None:
            res.notes.append(f"Fixed sum not available – import the GSTR-3B (with Table 6.1) for {prev_end}.")
        try:
            d = Gstr3bDraftService(self.db).draft(client_id, p)
            res.self_assessed = {h: d.setoff.cash.get(h, ZERO) for h in HEADS}
        except ServiceError as exc:
            res.notes.append(f"Self-assessment not available: {exc}")
        with self.db.session() as s:
            b2b = list(s.scalars(select(Invoice).where(Invoice.client_id == client_id, Invoice.source_type == "SALES",
                                                       Invoice.period == p, Invoice.supplier_gstin != "")))
        res.iff_docs = len(b2b)
        res.iff_value = sum(((r.invoice_value or r.taxable + r.igst + r.cgst + r.sgst + r.cess) for r in b2b), ZERO)
        if res.iff_over_limit:
            res.notes.append("B2B invoices exceed ₹50 lakh – the IFF takes up to ₹50 lakh a month; the rest goes in the "
                             "quarterly GSTR-1.")
        res.notes.append("PMT-06 is due by the 25th of the next month; no payment is needed if the cash and credit "
                         "ledger balances cover the tax (self-assessment) or the fixed sum is nil.")
        return res
