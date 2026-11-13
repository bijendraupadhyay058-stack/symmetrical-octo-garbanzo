"""GSTR-3B draft: the month's figures and the payment of tax (Table 6.1).

Set-off of ITC (section 49(5) CGST Act, rule 88A):

1. IGST credit pays IGST first; IGST credit left over pays CGST and SGST (in any order) – and must be used
   up before any CGST or SGST credit is used.
2. CGST credit pays CGST, then IGST; SGST credit pays SGST, then IGST. CGST credit never pays SGST, nor SGST
   credit CGST.
3. Cess credit pays only cess.
4. Tax under reverse charge (3.1(d)) is paid in cash – never with ITC.

Where the law leaves a choice, IGST credit goes first to the head whose own credit falls short, so the least
cash is paid. The working is a draft for the professional; the portal's own offset is final.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

ZERO = Decimal(0)
HEADS = ("igst", "cgst", "sgst", "cess")


@dataclass
class Setoff:
    liability: dict[str, Decimal]  # forward-charge tax payable per head
    rcm: dict[str, Decimal]  # reverse-charge tax payable per head (cash only)
    credit: dict[str, Decimal]  # net ITC available per head (Table 4(C))
    used: dict[tuple[str, str], Decimal] = field(default_factory=dict)  # (credit head, liability head) -> amount
    cash: dict[str, Decimal] = field(default_factory=dict)  # cash per head (forward charge + RCM)
    carried: dict[str, Decimal] = field(default_factory=dict)  # credit left for the next month

    @property
    def total_cash(self) -> Decimal:
        return sum(self.cash.values(), ZERO)

    def paid_by(self, head: str) -> dict[str, Decimal]:
        """For a liability head: amounts paid with each credit head."""
        return {c: self.used.get((c, head), ZERO) for c in HEADS}


def set_off(liability: dict[str, Decimal], credit: dict[str, Decimal], rcm: dict[str, Decimal] | None = None) -> Setoff:
    liab = {h: max(liability.get(h, ZERO), ZERO) for h in HEADS}
    cred = {h: max(credit.get(h, ZERO), ZERO) for h in HEADS}
    rcm = {h: max((rcm or {}).get(h, ZERO), ZERO) for h in HEADS}
    s = Setoff(dict(liab), dict(rcm), dict(cred))

    def use(c: str, h: str, limit: Decimal | None = None) -> None:
        amt = min(cred[c], liab[h], limit if limit is not None else cred[c])
        if amt > 0:
            cred[c] -= amt
            liab[h] -= amt
            s.used[(c, h)] = s.used.get((c, h), ZERO) + amt

    use("igst", "igst")
    if cred["igst"] > 0:  # IGST credit left: first where CGST / SGST credit falls short, then anywhere
        short = {h: max(liab[h] - cred[h], ZERO) for h in ("cgst", "sgst")}
        for h in sorted(short, key=lambda x: -short[x]):
            use("igst", h, short[h])
        for h in ("cgst", "sgst"):
            use("igst", h)
    for c in ("cgst", "sgst"):
        use(c, c)
        use(c, "igst")
    use("cess", "cess")
    s.cash = {h: liab[h] + rcm[h] for h in HEADS}
    s.carried = dict(cred)
    return s
