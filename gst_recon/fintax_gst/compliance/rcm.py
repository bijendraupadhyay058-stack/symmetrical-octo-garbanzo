"""Reverse charge (section 9(3) / 9(4) / 5(3) IGST) register of a month, and ISD distribution (rule 39).

RCM: purchases marked "reverse charge" in the register are the RCM register. Purchases that look like a notified
reverse-charge service (goods transport agency, advocate, director, sponsorship, security, renting a motor vehicle
or commercial property from an unregistered person, import of services …) but are not marked, and on which the
supplier charged no tax, are listed as "possible RCM – check". An RCM purchase from an unregistered person needs a
self-invoice (section 31(3)(f)). The month's RCM tax is compared with GSTR-3B 3.1(d) (tax payable) and 4(A)(3)
(ITC). The program never decides that a purchase is under RCM – it lists what to check.

ISD: the input tax credit of an Input Service Distributor is distributed to the units of the same PAN in proportion
to their turnover in the relevant period (rule 39(1)(d)); CGST/SGST credit goes as CGST/SGST to a unit in the ISD's
state and as IGST to units in other states; IGST credit goes as IGST.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from ..core.models import DocType, InvoiceRecord
from ..core.money import ZERO
from ..importers.gstr3b import Gstr3bValues

PAISA = Decimal("0.01")
#: (label, keywords, note) – notified reverse-charge supplies (notification 13/2017-CT(R) and later amendments)
RCM_SERVICES = [
    ("Goods transport agency (GTA)", r"\b(gta|transport(er|ation)?|freight|lorry|truck|carriage|cartage|logistics)\b",
     "RCM unless the GTA charges GST under forward charge (5% / 12%)"),
    ("Legal services (advocate)", r"\b(advocate|legal|law\s+(firm|chambers)|lawyer|solicitor|counsel)\b",
     "services of an advocate or firm of advocates to a business entity"),
    ("Arbitral tribunal", r"\barbitra(l|tion|tor)\b", ""),
    ("Sponsorship", r"\bsponsor(ship)?\b", "to a body corporate or partnership firm"),
    ("Director's services", r"\b(director|sitting\s+fee)s?\b", "services of a director to the company"),
    ("Insurance agent", r"\binsurance\s+(agent|commission)\b", "to an insurance company"),
    ("Recovery agent", r"\brecovery\s+agent\b", "to a bank / NBFC"),
    ("Security services", r"\b(security|guard|watch\s*man)\b", "by a person other than a body corporate"),
    ("Renting of motor vehicle", r"\b(cab|taxi|car|vehicle|bus)\s+(hire|rent(al)?|services?)\b|\bmotor\s+vehicle\b",
     "by a non-body corporate not charging 12% GST"),
    ("Renting of commercial property (unregistered)", r"\b(rent|lease|office\s+rent|shop\s+rent)\b",
     "from an unregistered person to a registered person (w.e.f. 10-10-2024)"),
    ("Copyright / royalty", r"\b(royalt(y|ies)|copyright|author)\b", ""),
    ("Import of services", r"\b(import\s+of\s+services?|foreign|overseas|outside\s+india)\b",
     "IGST under section 5(3) of the IGST Act"),
]
_COMPILED = [(label, re.compile(kw, re.I), note) for label, kw, note in RCM_SERVICES]


@dataclass
class RcmLine:
    doc: InvoiceRecord
    status: str  # "RCM" (marked) / "Possible RCM – check"
    service: str = ""
    issues: list[str] = field(default_factory=list)

    @property
    def needs_self_invoice(self) -> bool:
        return self.status == "RCM" and not self.doc.supplier_gstin

    @property
    def tax(self) -> Decimal:
        sign = -1 if self.doc.doc_type == DocType.CREDIT_NOTE else 1
        return (self.doc.igst + self.doc.cgst + self.doc.sgst + self.doc.cess) * sign


@dataclass
class RcmMonth:
    period: str
    lines: list[RcmLine] = field(default_factory=list)
    filed_31d: Gstr3bValues | None = None
    filed_4a3: Gstr3bValues | None = None

    @property
    def marked(self) -> list[RcmLine]:
        return [ln for ln in self.lines if ln.status == "RCM"]

    def register_total(self) -> Gstr3bValues:
        t = Gstr3bValues()
        for ln in self.marked:
            s = -1 if ln.doc.doc_type == DocType.CREDIT_NOTE else 1
            d = ln.doc
            t = Gstr3bValues(t.igst + s * d.igst, t.cgst + s * d.cgst, t.sgst + s * d.sgst, t.cess + s * d.cess,
                             t.taxable + s * d.taxable)
        return t


def service_of(r: InvoiceRecord) -> tuple[str, str]:
    text = f"{r.description} {r.supplier_name} {r.supply_type}"
    for label, pat, note in _COMPILED:
        if pat.search(text):
            return label, note
    return "", ""


def rcm_month(period: str, books: list[InvoiceRecord], filed: dict[str, Gstr3bValues] | None = None) -> RcmMonth:
    out = RcmMonth(period)
    for b in books:
        if b.period != period:
            continue
        service, note = service_of(b)
        tax = b.igst + b.cgst + b.sgst + b.cess
        if b.reverse_charge:
            ln = RcmLine(b, "RCM", service)
            if tax == 0:
                ln.issues.append("no tax in the register – work out the RCM tax and add it")
            if not b.supplier_gstin:
                ln.issues.append("unregistered supplier – issue a self-invoice (section 31(3)(f)) and a payment "
                                 "voucher (section 31(3)(g))")
            out.lines.append(ln)
        elif service and tax == 0:
            ln = RcmLine(b, "Possible RCM – check", service,
                         [f"looks like {service.lower()} with no GST charged" + (f" ({note})" if note else "")])
            out.lines.append(ln)
    if filed is not None:
        out.filed_31d = filed.get("31D")
        out.filed_4a3 = filed.get("4A3")
    return out


# --------------------------------------------------------------------------- ISD
@dataclass
class IsdShare:
    name: str
    gstin: str
    turnover: Decimal
    ratio: Decimal
    igst: Decimal = ZERO
    cgst: Decimal = ZERO
    sgst: Decimal = ZERO
    cess: Decimal = ZERO

    @property
    def total(self) -> Decimal:
        return self.igst + self.cgst + self.sgst + self.cess


def _split(amount: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """Split to the paisa; the rounding difference goes to the largest share so the parts add up exactly."""
    total = sum(weights, ZERO)
    if not amount or not total:
        return [ZERO for _w in weights]
    parts = [(amount * w / total).quantize(PAISA, rounding=ROUND_HALF_UP) for w in weights]
    diff = amount - sum(parts, ZERO)
    if diff:
        i = max(range(len(weights)), key=lambda k: weights[k])
        parts[i] += diff
    return parts


def distribute_isd(itc: Gstr3bValues, isd_state: str, recipients: list[tuple[str, str, Decimal]]) -> list[IsdShare]:
    """``recipients``: (name, GSTIN, turnover of the relevant period). Units with no turnover get no share."""
    shares = [IsdShare(n, g, t, ZERO) for n, g, t in recipients]
    weights = [max(s.turnover, ZERO) for s in shares]
    total = sum(weights, ZERO)
    for s, w in zip(shares, weights):
        s.ratio = (w / total * 100).quantize(Decimal("0.0001")) if total else ZERO
    for s, part in zip(shares, _split(itc.igst, weights)):
        s.igst += part
    for s, part in zip(shares, _split(itc.cess, weights)):
        s.cess += part
    for head in ("cgst", "sgst"):
        for s, part in zip(shares, _split(getattr(itc, head), weights)):
            if s.gstin[:2] == isd_state:
                setattr(s, head, getattr(s, head) + part)
            else:
                s.igst += part  # credit of CGST / SGST goes as IGST to a unit in another state
    return shares
