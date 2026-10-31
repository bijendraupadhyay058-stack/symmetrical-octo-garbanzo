"""Return filing register, settlements, and the interest / late fee working of a year.

Nothing here is paid or filed: the working shows what section 50 and section 47 would
levy on the data imported and the dates recorded, with every basis stated, and a
DRC-03 summary of what has not been paid.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from ..compliance.calendar import annual_items, due_items, due_of
from ..compliance.interest import gstr9_late_fee, interest, late_fee
from ..core.money import ZERO
from ..db.database import Database
from ..db.models import Client, InterestSettlement, Invoice, ReturnFiling
from ..importers.gstr3b import Gstr3bValues
from ..importers.parsing import DateParseError, parse_bool, parse_date, parse_period, parse_text
from ..itc.annual import fy_months
from .auth import Session, require
from .common import ServiceError, audit

RETURN_TYPES = ("GSTR-1", "IFF", "GSTR-3B", "PMT-06", "GSTR-9")  # returns whose filing date can be recorded
KINDS = {"SHORT_PAYMENT": "Tax short paid (GSTR-1 above GSTR-3B)",
         "EXCESS_ITC": "ITC in GSTR-3B above GSTR-2B"}
STATUSES = ("SETTLED", "NOT_PAYABLE")
HEADS = ("igst", "cgst", "sgst", "cess")


@dataclass
class LateRow:
    return_type: str
    period: str
    due: date
    filed: date | None
    days: int
    fee_cgst: Decimal | None
    fee_sgst: Decimal | None
    fee_basis: str
    cash: Gstr3bValues | None = None  # GSTR-3B 6.1 tax paid in cash
    interest: dict[str, Decimal] = field(default_factory=dict)  # per head
    interest_paid: Decimal | None = None  # GSTR-3B 6.1 interest paid
    fee_paid: Decimal | None = None  # GSTR-3B 6.1 late fee paid

    @property
    def interest_total(self) -> Decimal:
        return sum(self.interest.values(), ZERO)

    @property
    def fee_total(self) -> Decimal:
        return (self.fee_cgst or ZERO) + (self.fee_sgst or ZERO)


@dataclass
class ExposureRow:
    kind: str  # SHORT_PAYMENT / EXCESS_ITC
    period: str
    head: str
    amount: Decimal
    start: date  # interest runs from the day after
    end: date
    days: int
    interest: Decimal
    status: str  # OPEN, SETTLED, NOT_PAYABLE
    basis: str
    reference: str = ""


@dataclass
class InterestWorking:
    fy: str
    as_of: date
    aato: Decimal | None
    late: list[LateRow] = field(default_factory=list)
    exposures: list[ExposureRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def drc03(self) -> dict[str, dict[str, Decimal]]:
        """Unpaid amounts by head for a DRC-03 summary: tax, interest, late fee.

        A settlement records when the tax was paid (or the ITC reversed); the interest up to that
        date is still listed, since it is often paid separately – remove it if it was paid with it."""
        out = {h: {"tax": ZERO, "interest": ZERO, "fee": ZERO} for h in HEADS}
        for e in self.exposures:
            if e.status == "OPEN" and e.kind == "SHORT_PAYMENT":
                out[e.head]["tax"] += e.amount
            if e.status in ("OPEN", "SETTLED"):
                out[e.head]["interest"] += e.interest
        for r in self.late:
            paid = r.interest_paid or ZERO
            due = r.interest_total
            if due > paid:  # attribute the unpaid interest in proportion to the heads
                for h, v in r.interest.items():
                    out[h]["interest"] += ((due - paid) * v / due).quantize(Decimal("0.01")) if due else ZERO
            fee_paid = r.fee_paid or ZERO
            if r.fee_total > fee_paid:
                share = (r.fee_total - fee_paid) / r.fee_total
                out["cgst"]["fee"] += ((r.fee_cgst or ZERO) * share).quantize(Decimal("0.01"))
                out["sgst"]["fee"] += ((r.fee_sgst or ZERO) * share).quantize(Decimal("0.01"))
        return out


class InterestService:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------ registers
    def filings(self, client_id: int) -> dict[tuple[str, str], ReturnFiling]:
        with self.db.session() as s:
            return {(f.return_type, f.period): f for f in s.scalars(
                select(ReturnFiling).where(ReturnFiling.client_id == client_id))}

    def set_filing(self, client_id: int, return_type: str, period: str, filed_on: date | None, by: Session | None,
                   arn: str = "", nil: bool = False, note: str = "") -> None:
        """Record (or with ``filed_on=None`` remove) the filing of a return. Audited."""
        require(by, "review")
        return_type = return_type.upper().replace("GSTR", "GSTR-").replace("--", "-")
        if return_type not in RETURN_TYPES:
            raise ServiceError(f"Return type must be one of {', '.join(RETURN_TYPES)}")
        if return_type == "GSTR-9":
            if not (len(period) == 7 and period[4] == "-" and period[:4].isdigit()):
                raise ServiceError("GSTR-9 period is the financial year, e.g. 2025-26")
        else:
            norm = parse_period(period)
            if not norm:
                raise ServiceError(f"Invalid period '{period}' (YYYY-MM)")
            period = norm
        with self.db.session() as s:
            row = s.scalar(select(ReturnFiling).where(ReturnFiling.client_id == client_id,
                                                      ReturnFiling.return_type == return_type,
                                                      ReturnFiling.period == period))
            before = {"filed_on": row.filed_on, "arn": row.arn, "nil": row.nil} if row else None
            if filed_on is None:
                if row is not None:
                    s.delete(row)
            else:
                if row is None:
                    row = ReturnFiling(client_id=client_id, return_type=return_type, period=period)
                    s.add(row)
                row.filed_on, row.arn, row.nil, row.note = filed_on, arn.strip()[:30], nil, note.strip()
                row.updated_by = by.username
            audit(s, "RETURN_FILING", "return_filing", f"{return_type}:{period}",
                  {"before": before, "after": {"filed_on": filed_on, "arn": arn, "nil": nil}}, by.username,
                  client_id)

    def import_filings(self, client_id: int, path: str | Path, by: Session | None,
                       apply: bool = True) -> tuple[list[tuple], list[str]]:
        """CSV with Return type, Period, Date of filing and optionally ARN and Nil (yes/no)."""
        from ..importers.column_mapping import normalize_header
        from ..importers.readers import read_csv, read_excel

        require(by, "review")
        path = Path(path)
        tables = [read_csv(path, path.name)] if path.suffix.lower() == ".csv" else read_excel(path)
        rows, problems = [], []
        for t in tables:
            for i, (_n, values) in enumerate(t.rows[:10]):
                names = [normalize_header(v) for v in values]
                col = {k: next((names.index(o) for o in opts if o in names), None) for k, opts in {
                    "type": ("return type", "return", "form", "return name"),
                    "period": ("period", "tax period", "return period", "financial year"),
                    "date": ("date of filing", "filing date", "filed on", "date filed", "date"),
                    "arn": ("arn", "acknowledgement number", "arn no"),
                    "nil": ("nil", "nil return")}.items()}
                if col["type"] is None or col["period"] is None or col["date"] is None:
                    continue
                for n, vals in t.rows[i + 1:]:
                    def cell(k, vals=vals):
                        c = col[k]
                        return vals[c] if c is not None and c < len(vals) else None
                    if not parse_text(cell("type")):
                        continue
                    try:
                        filed = parse_date(cell("date"))
                    except DateParseError as exc:
                        problems.append(f"row {n}: {exc}")
                        continue
                    rows.append((parse_text(cell("type")), parse_text(cell("period")), filed,
                                 parse_text(cell("arn")), bool(parse_bool(cell("nil")))))
                break
        if not rows and not problems:
            raise ServiceError("No heading row with Return type, Period and Date of filing found")
        if apply:
            for rtype, period, filed, arn, nil in rows:
                try:
                    self.set_filing(client_id, rtype, period, filed, by, arn, nil)
                except ServiceError as exc:
                    problems.append(f"{rtype} {period}: {exc}")
        return rows, problems

    def settlements(self, client_id: int) -> dict[tuple[str, str], InterestSettlement]:
        with self.db.session() as s:
            return {(x.kind, x.period): x for x in s.scalars(
                select(InterestSettlement).where(InterestSettlement.client_id == client_id))}

    def set_settlement(self, client_id: int, kind: str, period: str, status: str | None, by: Session | None,
                       settled_on: date | None = None, reference: str = "", note: str = "") -> None:
        """Record how a period's short payment / excess ITC was dealt with (``status=None`` removes it)."""
        require(by, "review")
        kind = kind.upper()
        if kind not in KINDS:
            raise ServiceError(f"Kind must be one of {', '.join(KINDS)}")
        period = parse_period(period) or ""
        if not period:
            raise ServiceError("Invalid period (YYYY-MM)")
        if status is not None:
            status = status.upper()
            if status not in STATUSES:
                raise ServiceError(f"Status must be one of {', '.join(STATUSES)}")
            if status == "SETTLED" and settled_on is None:
                raise ServiceError("Give the date of payment / reversal")
            if status == "NOT_PAYABLE" and not note.strip():
                raise ServiceError("Give the reason why nothing is payable")
        with self.db.session() as s:
            row = s.scalar(select(InterestSettlement).where(InterestSettlement.client_id == client_id,
                                                            InterestSettlement.kind == kind,
                                                            InterestSettlement.period == period))
            before = {"status": row.status, "settled_on": row.settled_on, "note": row.note} if row else None
            if status is None:
                if row is not None:
                    s.delete(row)
            else:
                if row is None:
                    row = InterestSettlement(client_id=client_id, kind=kind, period=period)
                    s.add(row)
                row.status, row.settled_on = status, settled_on
                row.reference, row.note, row.updated_by = reference.strip()[:60], note.strip(), by.username
            audit(s, "INTEREST_SETTLEMENT", "interest_settlement", f"{kind}:{period}",
                  {"before": before, "after": {"status": status, "settled_on": settled_on, "note": note}},
                  by.username, client_id)

    # -------------------------------------------------------------- working
    def working(self, client_id: int, fy: str, as_of: date | None = None) -> InterestWorking:
        from .calendar import CalendarService
        from .gstr3b import Gstr3bService
        from .gstr9c import Gstr9cService
        from .itc import ItcService
        from .outward import OutwardService

        as_of = as_of or date.today()
        months = [m for m in fy_months(fy) if m <= f"{as_of:%Y-%m}"]
        with self.db.session() as s:
            client = s.get(Client, client_id)
            if client is None:
                raise ServiceError(f"Client {client_id} not found")
            freq, state = client.return_frequency, client.state_code
        aato = Gstr9cService(self.db).inputs(client_id, fy).get("AATO", (None, ""))[0]
        w = InterestWorking(fy, as_of, aato)
        if aato is None:
            w.notes.append(f"AATO of the preceding year not entered for FY {fy} (item AATO) – late fees use the "
                           "highest cap.")
        overrides = CalendarService(self.db).overrides()
        filings = self.filings(client_id)
        settled = self.settlements(client_id)
        filed3b = Gstr3bService(self.db).values(client_id, months)
        with self.db.session() as s:
            have = set(s.execute(select(Invoice.source_type, Invoice.period).where(
                Invoice.client_id == client_id, Invoice.period.in_(months),
                Invoice.source_type.in_(["GSTR1", "GSTR2B"])).distinct()).all())
        have |= {("GSTR1", p) for p, rows in OutwardService(self.db).summaries(client_id, months).items() if rows}
        missing: list[str] = []

        due3b: dict[str, date] = {}
        for p in months:
            items = due_items(p, freq, state, overrides)
            for rtype in ("GSTR-1", "GSTR-3B"):
                item = due_of(items, rtype)
                if item is None:
                    continue  # QRMP: no GSTR-1 / GSTR-3B for the first two months of a quarter
                if rtype == "GSTR-3B":
                    due3b[p] = item.due
                f = filings.get((rtype, p))
                if f is None:
                    if item.due < as_of:
                        missing.append(f"{rtype} {p}")
                    continue
                fee = late_fee(p, item.due, f.filed_on, f.nil, aato)
                row = LateRow(rtype, p, item.due, f.filed_on, max((f.filed_on - item.due).days, 0),
                              fee.cgst if fee else None, fee.sgst if fee else None,
                              fee.basis if fee else "before June 2021 – not computed (check notified waivers)")
                if rtype == "GSTR-3B":
                    vals = filed3b.get(p, {})
                    row.cash = vals.get("61CASH")
                    if row.cash is None and any(c.startswith("61") for c in vals):
                        row.cash = Gstr3bValues()  # Table 6.1 imported without a cash row: nothing paid in cash
                    if row.days and row.cash is not None:
                        row.interest = {h: interest(getattr(row.cash, h), item.due, f.filed_on)[1] for h in HEADS}
                    elif row.days:
                        w.notes.append(f"GSTR-3B {p} filed {row.days} day(s) late but its Table 6.1 (tax paid in "
                                       "cash) is not imported – interest on the delay not computed.")
                    paid = vals.get("61INT")
                    row.interest_paid = paid.total if paid is not None else None
                    fee_paid = vals.get("61FEE")
                    row.fee_paid = fee_paid.total if fee_paid is not None else None
                w.late.append(row)
        if missing:
            w.notes.append("Filing date not recorded for " + ", ".join(missing) + " – late fee and interest on "
                           "delay not computed for them.")
        a9 = due_of(annual_items(fy, state, overrides), "GSTR-9")
        f9 = filings.get(("GSTR-9", fy))
        if f9 is not None and a9 is not None:
            from .gstr9 import Gstr9Service

            turnover = next((r.gstr1.taxable for r in Gstr9Service(self.db).working(client_id, fy).table5
                             if r.code == "5N" and r.gstr1 is not None), ZERO)
            fee = gstr9_late_fee(fy, a9.due, f9.filed_on, aato, turnover)
            w.late.append(LateRow("GSTR-9", fy, a9.due, f9.filed_on, max((f9.filed_on - a9.due).days, 0),
                                  fee.cgst if fee else None, fee.sgst if fee else None,
                                  fee.basis if fee else "not computed (before FY 2022-23, or optional at this AATO)"))

        def exposure(kind: str, p: str, values: dict[str, Decimal], start: date, basis: str) -> None:
            st = settled.get((kind, p))
            for h, amount in values.items():
                if amount <= Decimal("1"):
                    continue
                if st is not None and st.status == "NOT_PAYABLE":
                    w.exposures.append(ExposureRow(kind, p, h, amount, start, start, 0, ZERO, "NOT_PAYABLE",
                                                   f"{basis}; not payable: {st.note}", st.reference))
                    continue
                end = st.settled_on if st is not None and st.status == "SETTLED" else as_of
                days, amt = interest(amount, start, end)
                w.exposures.append(ExposureRow(kind, p, h, amount, start, end, days, amt,
                                               "SETTLED" if st is not None else "OPEN", basis,
                                               st.reference if st is not None else ""))

        for lw in OutwardService(self.db).liability(client_id, months):
            if lw.period not in filed3b or lw.period not in due3b or ("GSTR1", lw.period) not in have:
                continue
            short = {}
            for h in HEADS:
                g1 = sum((getattr(lw.row(c).gstr1, h) for c in ("31A", "31B")), ZERO)
                paid = sum((getattr(lw.row(c).filed, h) for c in ("31A", "31B") if lw.row(c).filed is not None),
                           ZERO)
                short[h] = g1 - paid
            if any(v > Decimal("1") for v in short.values()):
                exposure("SHORT_PAYMENT", lw.period, short, due3b[lw.period],
                         "GSTR-1 tax above GSTR-3B 3.1(a)+(b); interest on the whole amount from the GSTR-3B due date")
        itc_periods = [p for p in months if p in filed3b and ("GSTR2B", p) in have]
        for p in months:
            if p in filed3b and p not in itc_periods:
                w.notes.append(f"GSTR-2B {p} not imported – ITC in GSTR-3B not checked against it.")
        for pw in ItcService(self.db).table4(client_id, itc_periods, as_of):
            r = pw.row("4C")
            if r.filed is None or pw.period not in due3b:
                continue
            excess = {h: getattr(r.filed, h) - getattr(r.auto_2b, h) for h in HEADS}
            f = filings.get(("GSTR-3B", pw.period))
            start = f.filed_on if f is not None else due3b[pw.period]
            if any(v > Decimal("1") for v in excess.values()):
                exposure("EXCESS_ITC", pw.period, excess, start,
                         "GSTR-3B 4(C) above GSTR-2B; UPPER LIMIT – assumed utilised when the return was filed "
                         "(rule 88B(3): only the part the credit ledger did not cover is utilised)")
        if any(e.status == "SETTLED" and e.interest for e in w.exposures):
            w.notes.append("Interest up to the settlement date is included in the DRC-03 summary – leave it out if it "
                           "was paid with the tax.")
        return w
