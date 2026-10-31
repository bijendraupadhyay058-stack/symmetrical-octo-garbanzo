"""IMS (Invoice Management System) comparison with books and GSTR-2B.

Works on exported IMS data only. The software never performs IMS actions or
changes anything on the GST portal; observations tell the user what to check
or do on the portal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..core.models import DocType, InvoiceRecord
from ..core.money import fmt_inr
from ..importers.parsing import IMS_ACTIONS

IMS_START = date(2024, 10, 1)


@dataclass
class ImsRow:
    ims: InvoiceRecord
    books: InvoiceRecord | None
    gstr2b: InvoiceRecord | None
    observations: list[tuple[str, str]] = field(default_factory=list)  # (severity, text)

    @property
    def action(self) -> str:
        return self.ims.ims_action or "N"

    @property
    def action_label(self) -> str:
        return IMS_ACTIONS.get(self.action, self.action)

    @property
    def worst(self) -> str:
        order = {"high": 0, "medium": 1, "info": 2}
        return min((s for s, _ in self.observations), key=order.get, default="")


def _index(records: list[InvoiceRecord]) -> tuple[dict, dict]:
    exact, loose = {}, {}
    for r in sorted(records, key=InvoiceRecord.sort_key):
        exact.setdefault((r.supplier_gstin, r.doc_type, r.invoice_no_norm), r)
        loose.setdefault((r.supplier_gstin, r.doc_type, r.invoice_no_loose), r)
    return exact, loose


def _find(r: InvoiceRecord, idx: tuple[dict, dict]) -> InvoiceRecord | None:
    exact, loose = idx
    return exact.get((r.supplier_gstin, r.doc_type, r.invoice_no_norm)) or \
        loose.get((r.supplier_gstin, r.doc_type, r.invoice_no_loose))


def compare_ims(ims: list[InvoiceRecord], books: list[InvoiceRecord], gstr2b: list[InvoiceRecord],
                tolerance: Decimal = Decimal("1.00"), period: str = "") -> tuple[list[ImsRow], list[str]]:
    notes = []
    if period and period < f"{IMS_START:%Y-%m}":
        notes.append(f"IMS applies from October 2024; period {period} predates it.")
    bidx, gidx = _index(books), _index(gstr2b)
    rows = []
    for r in sorted(ims, key=InvoiceRecord.sort_key):
        b, g = _find(r, bidx), _find(r, gidx)
        row = ImsRow(r, b, g)
        a = row.action
        note = r.doc_type == DocType.CREDIT_NOTE
        obs = row.observations
        if a == "R":
            if b is not None:
                obs.append(("high", "Rejected in IMS but recorded in books – do not claim ITC; confirm the rejection "
                                    "with the client and supplier" if not note else
                            "Credit note rejected in IMS but recorded in books – confirm treatment with supplier"))
            if g is not None:
                obs.append(("high", "Rejected in IMS but present in GSTR-2B – recompute GSTR-2B on the portal "
                                    "after the IMS action"))
        elif a == "P":
            if g is not None:
                obs.append(("medium", "Pending in IMS but present in GSTR-2B – check whether GSTR-2B was generated "
                                      "before the action; recompute if required"))
            if b is not None:
                obs.append(("info", "Kept pending – ITC deferred to the period in which it is accepted "
                                    "(subject to Section 16(4))"))
        else:  # accepted or no action (deemed accepted)
            if b is None:
                obs.append(("high", ("Credit note accepted in IMS but not recorded in books – reduce ITC"
                                     if note else "Accepted / deemed accepted in IMS but not recorded in books – "
                                                  "record it, or reject/keep pending in IMS before GSTR-2B is "
                                                  "generated")))
            if g is None:
                obs.append(("medium", "Accepted in IMS but not in GSTR-2B of this period – GSTR-2B may need "
                                      "recomputation"))
        if b is not None:
            diffs = [n for n in ("taxable", "igst", "cgst", "sgst", "cess")
                     if abs(getattr(r, n) - getattr(b, n)) > tolerance]
            if diffs:
                obs.append(("medium", "Values differ from books: " + ", ".join(
                    f"{n.upper()} IMS {fmt_inr(getattr(r, n))} vs books {fmt_inr(getattr(b, n))}" for n in diffs)))
        if r.is_amendment:
            obs.append(("info", f"Amendment of original document '{r.original_invoice_no}'"))
        if not obs:
            obs.append(("info", "Consistent with books and GSTR-2B"))
        rows.append(row)
    return rows, notes


def ims_actions_for_books(rows: list[ImsRow]) -> dict[int, str]:
    """books invoice db id -> IMS action, for the ITC review."""
    return {r.books.db_id: r.action for r in rows if r.books is not None and r.books.db_id}
