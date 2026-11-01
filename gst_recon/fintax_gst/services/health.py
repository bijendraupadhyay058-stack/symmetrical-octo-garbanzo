"""Data health check of a client's financial year: problems in the imported data that make the workings wrong or
incomplete, each with what to do and where.

Checks: GSTINs that do not verify; possible duplicate bills (the same supplier's number written two ways); dates in
the future, booked before the bill date or older than the section 16(4) limit; months missing between months that
have data; months not reconciled, or reconciled before the latest import; amounts whose tax is impossible
(tax with no taxable value, tax above 40 %); and suppliers with a cancelled / suspended registration.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from ..core.gstin import validate_gstin
from ..core.invoice_no import loose_invoice_no
from ..core.money import ZERO
from ..db.database import Database
from ..db.models import Client, Invoice, ReconRun
from ..itc.annual import fy_months
from ..itc.deadlines import itc_deadline
from .common import ServiceError

SEVERITY = {"red": 0, "amber": 1, "info": 2}
LABELS = {"BOOKS": "purchase register", "GSTR2B": "GSTR-2B", "SALES": "sales register", "GSTR1": "GSTR-1"}


@dataclass
class HealthItem:
    severity: str  # red / amber / info
    area: str
    title: str
    detail: str
    count: int = 1
    page: str = ""  # page of the program where it is fixed
    examples: list[str] = field(default_factory=list)


@dataclass
class HealthReport:
    client: str
    fy: str
    items: list[HealthItem] = field(default_factory=list)

    @property
    def score(self) -> int:
        w = {"red": 15, "amber": 5, "info": 1}
        return max(0, 100 - sum(w[i.severity] for i in self.items))

    def count(self, severity: str) -> int:
        return sum(1 for i in self.items if i.severity == severity)


class HealthService:
    def __init__(self, db: Database):
        self.db = db

    def check(self, client_id: int, fy: str, today: date | None = None) -> HealthReport:
        today = today or date.today()
        months = fy_months(fy)
        current = f"{today:%Y-%m}"
        with self.db.session() as s:
            client = s.get(Client, client_id)
            if client is None:
                raise ServiceError(f"Client {client_id} not found")
            rep = HealthReport(client.name, fy)
            docs = list(s.execute(select(Invoice.id, Invoice.source_type, Invoice.supplier_gstin,
                                         Invoice.supplier_name, Invoice.invoice_no, Invoice.invoice_date,
                                         Invoice.doc_type, Invoice.period, Invoice.taxable, Invoice.igst,
                                         Invoice.cgst, Invoice.sgst, Invoice.cess, Invoice.source_file_id)
                                  .where(Invoice.client_id == client_id, Invoice.period.in_(months))).all())
            runs = list(s.scalars(select(ReconRun).where(ReconRun.client_id == client_id,
                                                         ReconRun.period_from.in_(months))
                                  .order_by(ReconRun.id)))
        add = rep.items.append
        if not docs:
            add(HealthItem("info", "Data", f"Nothing imported for {fy}", "Import the registers and returns of the "
                           "year to check them.", 0, "workflow"))
            return rep

        # 1. GSTINs that do not verify
        bad: dict[str, set] = defaultdict(set)
        for d in docs:
            if d.supplier_gstin and d.source_type in ("BOOKS", "SALES"):
                ok, problem = validate_gstin(d.supplier_gstin)
                if not ok or problem:
                    bad[d.source_type].add(d.supplier_gstin)
        for src, gs in bad.items():
            add(HealthItem("red", "GSTIN", f"{len(gs)} GSTIN(s) in the {LABELS[src]} do not verify",
                           "A wrong check digit is a typing mistake – these bills will not match the returns. Correct "
                           "them in Tally and re-import, or on the Invoices page.", len(gs),
                           "invoices", sorted(gs)[:5]))

        # 2. possible duplicates written two ways
        groups: dict[tuple, set] = defaultdict(set)
        for d in docs:
            if d.source_type == "BOOKS":
                groups[(d.supplier_gstin, loose_invoice_no(d.invoice_no), d.doc_type)].add(d.invoice_no)
        dups = [(k, v) for k, v in groups.items() if len(v) > 1]
        if dups:
            add(HealthItem("amber", "Duplicates", f"{len(dups)} bill(s) appear twice with the number written "
                           "differently", "e.g. INV-12 and INV/012 from the same supplier – if it is one bill, remove "
                           "the extra entry so the ITC is not counted twice.", len(dups), "invoices",
                           [" / ".join(sorted(v)) for _k, v in dups[:5]]))

        # 3. dates
        future = [d for d in docs if d.invoice_date > today]
        if future:
            add(HealthItem("red", "Dates", f"{len(future)} document(s) dated in the future",
                           "Check the date format of the import (day and month swapped?).", len(future), "imports",
                           [f"{d.invoice_no} {d.invoice_date:%d-%m-%Y}" for d in future[:5]]))
        early = [d for d in docs if d.source_type == "BOOKS" and d.period < f"{d.invoice_date:%Y-%m}"]
        if early:
            add(HealthItem("amber", "Dates", f"{len(early)} purchase(s) booked in a month before the bill date",
                           "The booking month is earlier than the bill – check the voucher dates.", len(early),
                           "invoices", [f"{d.invoice_no} ({d.period})" for d in early[:5]]))
        barred = [d for d in docs if d.source_type == "BOOKS" and d.doc_type != "CRN"
                  and today > itc_deadline(d.invoice_date)[0]]
        if barred:
            add(HealthItem("amber", "Dates", f"{len(barred)} purchase bill(s) past the section 16(4) time limit",
                           "ITC on them can no longer be claimed if not claimed already – see ITC review → Claim plan.",
                           len(barred), "itc"))

        # 4. missing months
        upto = [m for m in months if m < current] or months[:1]
        have: dict[str, set] = defaultdict(set)
        for d in docs:
            have[d.source_type].add(d.period)
        for src in ("BOOKS", "GSTR2B", "SALES"):
            got = have.get(src, set())
            if not got:
                continue
            first, last = min(got), max(got)
            gaps = [m for m in upto if first <= m <= last and m not in got]
            if gaps:
                add(HealthItem("amber", "Missing months", f"{LABELS[src].capitalize()} missing for {len(gaps)} month(s)",
                               ", ".join(gaps) + " – import them (or confirm there was nothing).", len(gaps),
                               "workflow"))

        # 5. reconciliation done and up to date
        files: dict[tuple[str, str], set] = defaultdict(set)
        for d in docs:
            files[(d.source_type, d.period)].add(d.source_file_id)
        latest: dict[tuple[str, str], ReconRun] = {}
        for r in runs:
            if r.period_from == r.period_to:
                latest[(r.comparison, r.period_from)] = r
        not_run, stale = [], []
        for comp, left, right in (("BOOKS_VS_GSTR2B", "BOOKS", "GSTR2B"), ("SALES_VS_GSTR1", "SALES", "GSTR1")):
            for m in sorted(have.get(left, set()) & have.get(right, set())):
                run = latest.get((comp, m))
                if run is None:
                    not_run.append(f"{m} ({LABELS[left]} vs {LABELS[right]})")
                    continue
                used = set(json.loads(run.source_file_ids or "[]"))
                if (files[(left, m)] | files[(right, m)]) - used:
                    stale.append(f"{m} ({LABELS[left]} vs {LABELS[right]})")
        if not_run:
            add(HealthItem("red", "Reconciliation", f"{len(not_run)} month(s) imported but not reconciled",
                           ", ".join(not_run), len(not_run), "workflow"))
        if stale:
            add(HealthItem("amber", "Reconciliation", f"{len(stale)} reconciliation(s) older than the latest import",
                           ", ".join(stale) + " – run them again so the new data is included.", len(stale), "workflow"))

        # 6. impossible amounts
        odd = []
        for d in docs:
            tax = (d.igst or ZERO) + (d.cgst or ZERO) + (d.sgst or ZERO)
            if tax and not d.taxable:
                odd.append(f"{d.invoice_no}: tax without taxable value")
            elif d.taxable and tax > d.taxable * Decimal("0.40"):
                odd.append(f"{d.invoice_no}: tax {tax} is over 40 % of {d.taxable}")
            elif (d.igst or ZERO) and ((d.cgst or ZERO) or (d.sgst or ZERO)):
                odd.append(f"{d.invoice_no}: both IGST and CGST/SGST")
        if odd:
            add(HealthItem("amber", "Amounts", f"{len(odd)} document(s) with impossible tax", "Check the tax columns "
                           "of the import (see also Reconcile → Tax checks).", len(odd), "invoices", odd[:5]))

        # 7. supplier registrations
        from .gstin_status import GstinStatusService

        flags = GstinStatusService(self.db).flags(client_id, months, today)
        high = [f for f in flags if f.severity == "high"]
        if high:
            add(HealthItem("red", "Suppliers", f"{len(high)} supplier(s) cancelled / suspended / composition with ITC",
                           f"ITC at stake ₹{sum((f.itc for f in high), ZERO):,.2f} – see Suppliers → GSTIN status.",
                           len(high), "suppliers", [f"{f.name or f.gstin}: {f.message}" for f in high[:5]]))
        unchecked = [f for f in flags if f.severity == "info"]
        if unchecked:
            add(HealthItem("info", "Suppliers", f"{len(unchecked)} supplier GSTIN(s) not checked recently",
                           "Suppliers → GSTIN status → List to verify.", len(unchecked), "suppliers"))
        rep.items.sort(key=lambda i: (SEVERITY[i.severity], i.area))
        return rep
