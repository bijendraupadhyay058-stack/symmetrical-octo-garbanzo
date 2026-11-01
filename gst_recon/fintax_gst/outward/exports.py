"""Exports and SEZ supplies, and the refund (RFD-01) working.

Export invoices (sales register supply type export / SEZ / LUT, or place of supply 96/97) are checked against the
shipping bills:

* **with payment of IGST** – the IGST refund is processed from GSTR-1 Table 6A and the shipping bill: the shipping
  bill must exist and carry the same IGST;
* **under LUT / bond (without payment)** – goods must be exported within three months of the invoice (rule 96A),
  otherwise IGST is payable with interest; services must be paid for in convertible foreign exchange within one year;
* **SEZ** – no shipping bill; the SEZ officer's endorsement is needed for a refund.

Refund of accumulated ITC (rule 89):

* zero-rated supplies without payment – refund = turnover of zero-rated supply × net ITC ÷ adjusted total turnover;
* inverted duty structure – refund = (turnover of inverted rated supply × net ITC ÷ adjusted total turnover)
  − (tax payable on that supply × net ITC ÷ ITC availed on inputs and input services), where net ITC is the ITC on
  inputs only.

Both are limited to the balance in the electronic credit ledger. These are workings for the refund application;
the figures entered are the user's.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from ..compliance.tax_checks import pos_code
from ..core.invoice_no import loose_invoice_no
from ..core.money import ZERO
from .gstr1_json import SaleDoc

PAISA = Decimal("0.01")
SEZ = re.compile(r"sez", re.I)
EXPORT_WORDS = re.compile(r"exp|export|lut|bond|wopay|wpay|zero", re.I)
OK, CHECK, ACTION = "OK", "Check", "Action needed"


@dataclass
class ShippingBill:
    sb_no: str
    sb_date: date
    port: str
    invoice_no: str
    igst: Decimal = ZERO
    value: Decimal | None = None


@dataclass
class ExportLine:
    doc: SaleDoc
    kind: str  # "Export with IGST" / "Export under LUT" / "SEZ with IGST" / "SEZ under LUT"
    goods: bool
    sb: ShippingBill | None = None
    status: str = OK
    note: str = ""


def is_export(d: SaleDoc) -> bool:
    return bool(EXPORT_WORDS.search(d.supply_type or "") or SEZ.search(d.supply_type or "")
                or (pos_code(d.place_of_supply) or "") in ("96", "97"))


def _goods(d: SaleDoc) -> bool:
    hsn = [str(h.get("hsn") or "") for h in (d.hsn_lines or [])]
    return not hsn or not all(h.startswith("99") for h in hsn if h)


def check_exports(docs: list[SaleDoc], bills: list[ShippingBill], as_of: date) -> list[ExportLine]:
    by_inv: dict[str, list[ShippingBill]] = {}
    for b in bills:
        by_inv.setdefault(loose_invoice_no(b.invoice_no), []).append(b)
    out = []
    for d in sorted(docs, key=lambda x: (x.date, x.number)):
        if d.doc_type != "INV" or not is_export(d):
            continue
        sez = bool(SEZ.search(d.supply_type or ""))
        paid = d.igst > 0
        kind = f"{'SEZ' if sez else 'Export'} {'with IGST' if paid else 'under LUT'}"
        ln = ExportLine(d, kind, _goods(d))
        sb = (by_inv.get(loose_invoice_no(d.number)) or [None])[0]
        ln.sb = sb
        if sez:
            ln.note = "SEZ supply: keep the SEZ officer's endorsement (needed for the refund)"
        elif not ln.goods:
            ln.note = ("service export under LUT: payment in foreign exchange must be received within one year "
                       f"(by {d.date.replace(year=d.date.year + 1):%d-%m-%Y}) – keep the FIRC / BRC"
                       if not paid else "service export with IGST: refund through RFD-01 with the FIRC / BRC")
        elif paid:
            if sb is None:
                ln.status, ln.note = ACTION, ("no shipping bill found – the IGST refund (GSTR-1 Table 6A ↔ shipping "
                                              "bill) cannot be processed; check the invoice number on the shipping bill")
            elif abs(sb.igst - d.igst) > Decimal("1"):
                ln.status, ln.note = CHECK, (f"IGST on the shipping bill ₹{sb.igst:,.2f} differs from the invoice "
                                             f"₹{d.igst:,.2f} – the refund is held until they agree")
            else:
                ln.note = f"shipping bill {sb.sb_no} of {sb.sb_date:%d-%m-%Y} ({sb.port}) – refund-ready"
        else:
            limit = d.date + timedelta(days=90)
            if sb is not None:
                ln.note = f"exported on shipping bill {sb.sb_no} of {sb.sb_date:%d-%m-%Y}"
                if sb.sb_date > limit:
                    ln.status = CHECK
                    ln.note += f" – after three months of the invoice (by {limit:%d-%m-%Y}); see rule 96A"
            elif as_of > limit:
                ln.status, ln.note = ACTION, (f"not exported within three months (by {limit:%d-%m-%Y}) – IGST is "
                                              "payable with interest (rule 96A) unless the time is extended")
            else:
                ln.status, ln.note = CHECK, f"shipping bill awaited – export by {limit:%d-%m-%Y}"
        out.append(ln)
    return out


# ---------------------------------------------------------------------------- refund
@dataclass
class RefundInputs:
    kind: str  # "zero_rated" (rule 89(4)) / "inverted" (rule 89(5))
    period_from: str
    period_to: str
    turnover_zero_rated: Decimal = ZERO
    turnover_inverted: Decimal = ZERO
    adjusted_total_turnover: Decimal = ZERO
    net_itc: Decimal = ZERO  # zero-rated: inputs + input services; inverted: inputs only
    itc_inputs_and_services: Decimal = ZERO  # inverted only
    tax_payable_inverted: Decimal = ZERO  # inverted only
    credit_ledger_balance: Decimal | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class RefundResult:
    formula: str
    amount: Decimal  # before the credit ledger limit
    admissible: Decimal
    steps: list[tuple[str, Decimal]]


def _q(v: Decimal) -> Decimal:
    return v.quantize(PAISA, rounding=ROUND_HALF_UP)


def compute_refund(i: RefundInputs) -> RefundResult:
    if i.adjusted_total_turnover <= 0:
        raise ValueError("Adjusted total turnover must be more than zero")
    if i.kind == "zero_rated":
        amount = _q(i.turnover_zero_rated * i.net_itc / i.adjusted_total_turnover)
        steps = [("Turnover of zero-rated supply of goods and services", i.turnover_zero_rated),
                 ("Net ITC (inputs and input services)", i.net_itc),
                 ("Adjusted total turnover", i.adjusted_total_turnover),
                 ("Refund = zero-rated turnover × net ITC ÷ adjusted total turnover", amount)]
        formula = "Rule 89(4)"
    elif i.kind == "inverted":
        if i.itc_inputs_and_services <= 0:
            raise ValueError("ITC availed on inputs and input services must be more than zero")
        first = i.turnover_inverted * i.net_itc / i.adjusted_total_turnover
        second = i.tax_payable_inverted * i.net_itc / i.itc_inputs_and_services
        amount = max(_q(first - second), ZERO)
        steps = [("Turnover of inverted rated supply", i.turnover_inverted), ("Net ITC (inputs only)", i.net_itc),
                 ("Adjusted total turnover", i.adjusted_total_turnover),
                 ("A = inverted turnover × net ITC ÷ adjusted total turnover", _q(first)),
                 ("Tax payable on inverted rated supply", i.tax_payable_inverted),
                 ("ITC availed on inputs and input services", i.itc_inputs_and_services),
                 ("B = tax payable × net ITC ÷ ITC on inputs and input services", _q(second)),
                 ("Refund = A − B", amount)]
        formula = "Rule 89(5)"
    else:
        raise ValueError(f"Unknown refund type {i.kind}")
    admissible = amount if i.credit_ledger_balance is None else min(amount, max(i.credit_ledger_balance, ZERO))
    if i.credit_ledger_balance is not None:
        steps.append(("Balance in the electronic credit ledger", i.credit_ledger_balance))
    steps.append(("Refund admissible (lower of the two)", admissible))
    return RefundResult(formula, amount, admissible, steps)
