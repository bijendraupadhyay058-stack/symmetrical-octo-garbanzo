"""Return comparison: the returns downloaded from the GST portal compared with each other, month by month.

* **GSTR-3B vs GSTR-2B** – ITC availed in GSTR-3B Table 4(A) against the ITC the GSTR-2B makes available
  (B2B / credit notes, reverse charge, ISD, imports), head by head. More ITC in GSTR-3B than in GSTR-2B is the
  risk (section 16(2)(aa); DRC-01C intimation under rule 88D above the limit).
* **GSTR-1 vs GSTR-3B** – tax liability declared in GSTR-1 against the tax in GSTR-3B Table 3.1(a)+(b), head by
  head. More tax in GSTR-1 than in GSTR-3B is the risk (short payment; DRC-01B intimation under rule 88C).
* **GSTR-2A vs GSTR-2B** – document by document: what the supplier filed (GSTR-2A) against what reached the
  GSTR-2B, including documents that came in a later month's GSTR-2B (supplier filed after the cut-off).

Everything comes from the returns imported; a month whose return is not imported is shown as "not imported",
never as nil. A quarterly (QRMP) client is compared quarter by quarter (GSTR-1 / GSTR-3B are quarterly, the
GSTR-2B of the three months is added up).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from ..core.invoice_no import loose_invoice_no
from ..core.models import InvoiceRecord, Source
from ..core.money import ZERO
from ..db.database import Database
from ..db.models import Client, Gstr1Summary, Gstr3bEntry, Invoice, OtherItc, SourceFile
from ..importers.gstr3b import TABLE4, TABLE31, Gstr3bValues
from ..itc.annual import fy_months
from .common import ServiceError

KINDS = {"3B_2B": "GSTR-3B vs GSTR-2B (ITC)", "1_3B": "GSTR-1 vs GSTR-3B (output tax)",
         "2A_2B": "GSTR-2A vs GSTR-2B (documents)"}
SIDES = {"3B_2B": ("GSTR-3B", "GSTR-2B"), "1_3B": ("GSTR-1", "GSTR-3B"), "2A_2B": ("GSTR-2A", "GSTR-2B")}
RETURN_TYPES = ("GSTR1", "GSTR3B", "GSTR2A", "GSTR2B")
RETURN_LABELS = {"GSTR1": "GSTR-1", "GSTR3B": "GSTR-3B", "GSTR2A": "GSTR-2A", "GSTR2B": "GSTR-2B"}
TOLERANCE = Decimal("1.00")
A_CODES = ("4A1", "4A2", "4A3", "4A4", "4A5")
HEADS = ("igst", "cgst", "sgst", "cess")

# document status in GSTR-2A vs GSTR-2B
MATCHED, LATER, EARLIER, AMOUNT, ONLY_2A, ONLY_2B, NOT_AVAILABLE = (
    "Matched", "In a later GSTR-2B", "In an earlier GSTR-2B", "Amount differs", "Only in GSTR-2A",
    "Only in GSTR-2B", "In GSTR-2B – ITC not available")
DOC_STATUSES = (ONLY_2A, AMOUNT, LATER, EARLIER, NOT_AVAILABLE, ONLY_2B, MATCHED)


def _label(months: list[str]) -> str:
    first = date(int(months[0][:4]), int(months[0][5:]), 1)
    if len(months) == 1:
        return f"{first:%b-%Y}"
    last = date(int(months[-1][:4]), int(months[-1][5:]), 1)
    return f"{first:%b}–{last:%b %Y}"


@dataclass
class MonthRow:
    """One month (or quarter) of a comparison. ``left`` / ``right`` None = that return is not imported."""
    period: str  # last month of the group (the return period)
    months: list[str]
    left: Gstr3bValues | None
    right: Gstr3bValues | None
    left_docs: int | None = None
    right_docs: int | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return _label(self.months)

    @property
    def diff(self) -> Gstr3bValues | None:
        return None if self.left is None or self.right is None else self.left - self.right

    def status(self, left_label: str, right_label: str) -> str:
        if self.left is None and self.right is None:
            return "Not imported"
        if self.left is None:
            return f"{left_label} not imported"
        if self.right is None:
            return f"{right_label} not imported"
        d = self.diff
        if any(abs(getattr(d, h)) > TOLERANCE for h in HEADS):
            return "Difference"
        return "Matches"


@dataclass
class DetailRow:
    """A line of the breakdown of one month: e.g. 4(A)(5) All other ITC – GSTR-3B vs GSTR-2B."""
    period: str
    label: str
    left: Gstr3bValues | None
    right: Gstr3bValues | None
    taxable: bool = False  # compare the taxable value too

    @property
    def diff(self) -> Gstr3bValues | None:
        return None if self.left is None or self.right is None else self.left - self.right


@dataclass
class Finding:
    period: str
    severity: str  # high / medium / info
    text: str
    amount: Decimal = ZERO


@dataclass
class DocRow:
    status: str
    gstin: str
    name: str
    invoice_no: str
    invoice_date: date | None
    doc_type: str
    period_2a: str
    period_2b: str
    itc_2a: Decimal | None
    itc_2b: Decimal | None
    note: str = ""

    @property
    def diff(self) -> Decimal | None:
        return None if self.itc_2a is None or self.itc_2b is None else self.itc_2a - self.itc_2b


@dataclass
class Comparison:
    kind: str
    client: str
    gstin: str
    fy: str
    rows: list[MonthRow]
    details: list[DetailRow] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    docs: list[DocRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        return KINDS[self.kind]

    @property
    def sides(self) -> tuple[str, str]:
        return SIDES[self.kind]

    def total(self, side: str) -> Gstr3bValues:
        """Total of the months where both returns are imported (so the difference is like for like)."""
        out = Gstr3bValues()
        for r in self.rows:
            if r.left is not None and r.right is not None:
                out = out + (r.left if side == "left" else r.right)
        return out

    @property
    def difference(self) -> Gstr3bValues:
        return self.total("left") - self.total("right")

    @property
    def months_with_difference(self) -> int:
        return sum(1 for r in self.rows if r.status(*self.sides) == "Difference")

    def details_for(self, period: str) -> list[DetailRow]:
        return [d for d in self.details if d.period == period]

    def doc_counts(self) -> dict[str, int]:
        out = {s: 0 for s in DOC_STATUSES}
        for d in self.docs:
            out[d.status] += 1
        return out


@dataclass
class Availability:
    """Which returns are imported for which month: period -> return type -> number of documents / rows."""
    months: list[str]
    have: dict[str, dict[str, int]]

    def has(self, kind: str, period: str) -> bool:
        return period in self.have.get(kind, {})


def _sum(values) -> Gstr3bValues:
    out = Gstr3bValues()
    for v in values:
        out = out + v
    return out


def _doc_values(r: InvoiceRecord) -> Gstr3bValues:
    return Gstr3bValues(r.signed("igst"), r.signed("cgst"), r.signed("sgst"), r.signed("cess"), r.signed("taxable"))


class ReturnCompareService:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------ helpers
    def _client(self, client_id: int) -> Client:
        with self.db.session() as s:
            c = s.get(Client, client_id)
            if c is None:
                raise ServiceError(f"Client {client_id} not found")
            s.expunge(c)
        return c

    @staticmethod
    def groups(client: Client, fy: str) -> list[list[str]]:
        months = fy_months(fy)
        from ..compliance.calendar import is_quarterly

        if is_quarterly(client.return_frequency or ""):
            return [months[i:i + 3] for i in range(0, 12, 3)]
        return [[m] for m in months]

    def availability(self, client_id: int, fy: str) -> Availability:
        return self.db.cached(("rc_avail", client_id, fy), lambda: self._availability(client_id, fy))

    def _availability(self, client_id: int, fy: str) -> Availability:
        months = fy_months(fy)
        have: dict[str, dict[str, int]] = {k: {} for k in RETURN_TYPES}
        with self.db.session() as s:
            for src, period in s.execute(select(Invoice.source_type, Invoice.period).where(
                    Invoice.client_id == client_id, Invoice.source_type.in_(["GSTR1", "GSTR2A", "GSTR2B"]),
                    Invoice.period.in_(months))):
                have[src][period] = have[src].get(period, 0) + 1
            for (period,) in s.execute(select(Gstr1Summary.period).where(Gstr1Summary.client_id == client_id,
                                                                         Gstr1Summary.period.in_(months))):
                have["GSTR1"].setdefault(period, 0)
            for (period,) in s.execute(select(OtherItc.period).where(OtherItc.client_id == client_id,
                                                                     OtherItc.period.in_(months))):
                have["GSTR2B"][period] = have["GSTR2B"].get(period, 0) + 1
            for (period,) in s.execute(select(Gstr3bEntry.period).where(
                    Gstr3bEntry.client_id == client_id, Gstr3bEntry.active.is_(True),
                    Gstr3bEntry.period.in_(months))):
                have["GSTR3B"][period] = have["GSTR3B"].get(period, 0) + 1
            for src, period in s.execute(select(SourceFile.source_type, SourceFile.period).where(
                    SourceFile.client_id == client_id, SourceFile.source_type.in_(["GSTR1", "GSTR2A", "GSTR2B"]),
                    SourceFile.period.in_(months))):
                have[src].setdefault(period, 0)  # a nil return imported: no documents, still imported
        return Availability(months, have)

    def _docs(self, client_id: int, source: Source, months: list[str]) -> list[InvoiceRecord]:
        from .common import invoice_to_record

        it = Invoice.__table__
        with self.db.session() as s:
            rows = s.execute(select(it).where(it.c.client_id == client_id, it.c.source_type == source.value,
                                              it.c.period.in_(months))).all()
        return [invoice_to_record(r) for r in rows]

    # ------------------------------------------------------------- build
    def compare(self, kind: str, client_id: int, fy: str) -> Comparison:
        if kind not in KINDS:
            raise ServiceError(f"Unknown comparison {kind}")
        return self.db.cached(("rc", kind, client_id, fy), lambda: self._compare(kind, client_id, fy))

    def _compare(self, kind: str, client_id: int, fy: str) -> Comparison:
        client = self._client(client_id)
        out = Comparison(kind, client.name, client.gstin, fy, [])
        avail = self.availability(client_id, fy)
        groups = self.groups(client, fy)
        {"3B_2B": self._itc, "1_3B": self._liability, "2A_2B": self._docs_2a_2b}[kind](client, fy, groups, avail, out)
        if not any(r.left is not None or r.right is not None for r in out.rows):
            a, b = out.sides
            out.notes.insert(0, f"No {a} or {b} imported for {fy} yet – import the returns downloaded from the GST "
                                "portal (Return comparison → Import from GST portal).")
        return out

    # ---- GSTR-3B vs GSTR-2B -------------------------------------------
    def _itc(self, client: Client, fy: str, groups, avail: Availability, out: Comparison) -> None:
        from ..itc.table4 import build_period
        from .gstr3b import Gstr3bService
        from .itc import ItcService

        months = fy_months(fy)
        filed = Gstr3bService(self.db).values(client.id, months)
        g2b = self._docs(client.id, Source.GSTR2B, months)
        itc = ItcService(self.db)
        other = itc._other(client.id, months)
        rules = itc.rules(client.id)
        excess_year = ZERO
        for grp in groups:
            period = grp[-1]
            has_3b = any(set(filed.get(m, {})) & set(TABLE4) for m in grp)
            has_2b = any(avail.has("GSTR2B", m) for m in grp)
            filed_g: dict[str, Gstr3bValues] = {}
            for m in grp:
                for code, v in filed.get(m, {}).items():
                    filed_g[code] = filed_g.get(code, Gstr3bValues()) + v
            w = build_period(period, [r for r in g2b if r.period in grp], [o for o in other if o["period"] in grp],
                             filed_g if has_3b else None, [], [], [], rules)
            auto = {r.code: r.auto_2b for r in w.rows}
            left = _sum(filed_g.get(c, Gstr3bValues()) for c in A_CODES) if has_3b else None
            right = _sum(auto[c] for c in A_CODES) if has_2b else None
            row = MonthRow(period, grp, left, right,
                           right_docs=sum(avail.have["GSTR2B"].get(m, 0) for m in grp) if has_2b else None)
            out.rows.append(row)
            for code in ("4A1", "4A3", "4A4", "4A5"):
                out.details.append(DetailRow(period, TABLE4[code], filed_g.get(code, Gstr3bValues()) if has_3b
                                             else None, auto[code] if has_2b else None))
            out.details.append(DetailRow(period, "4(A) Total ITC availed / available", left, right))
            for code in ("4B1", "4B2", "4C", "4D2"):
                out.details.append(DetailRow(period, TABLE4[code] + (" (GSTR-2B: ITC marked not available)"
                                                                      if code == "4D2" else ""),
                                             filed_g.get(code, Gstr3bValues()) if has_3b else None,
                                             auto[code] if has_2b and code in ("4C", "4D2") else None))
            if left is None or right is None:
                continue
            for f in w.findings:
                if f.kind == "statutory":
                    out.findings.append(Finding(period, f.severity, f.text, f.amount))
            d = left - right
            excess_year += d.total
            if d.total < -TOLERANCE:
                out.findings.append(Finding(period, "info", f"GSTR-3B claims ₹{-d.total:,.2f} less than the GSTR-2B "
                                            "makes available – ITC kept on hold, ineligible or not yet claimed "
                                            "(it can be claimed later, within the section 16(4) time limit)",
                                            -d.total))
            heads = [h.upper() for h in HEADS if getattr(d, h) > TOLERANCE]
            if heads and d.total <= TOLERANCE:
                out.findings.append(Finding(period, "medium", "Total ITC agrees but GSTR-3B has more "
                                            f"{', '.join(heads)} than GSTR-2B – ITC taken under the wrong tax head",
                                            sum((getattr(d, h) for h in HEADS if getattr(d, h) > 0), ZERO)))
        if excess_year > TOLERANCE:
            out.findings.append(Finding("Year", "high", f"For the months compared, GSTR-3B ITC exceeds GSTR-2B by "
                                        f"₹{excess_year:,.2f} in total – reverse it, or keep evidence that it "
                                        "appears in a later GSTR-2B", excess_year))
        out.notes.append("GSTR-2B side: B2B invoices and notes (ITC available), reverse charge documents, ISD credit "
                         "and imports (bills of entry) of the GSTR-2B; amended documents are taken at their revised "
                         "values.")

    # ---- GSTR-1 vs GSTR-3B --------------------------------------------
    def _liability(self, client: Client, fy: str, groups, avail: Availability, out: Comparison) -> None:
        from ..outward.liability import build_liability
        from .gstr3b import Gstr3bService
        from .itc import ItcService
        from .outward import OutwardService

        months = fy_months(fy)
        filed = Gstr3bService(self.db).values(client.id, months)
        summaries = OutwardService(self.db).summaries(client.id, months)
        rules = ItcService(self.db).rules(client.id)
        short_year = ZERO
        for grp in groups:
            period = grp[-1]
            summ = [x for m in grp for x in summaries.get(m, [])]
            has_1 = any(avail.has("GSTR1", m) for m in grp)
            has_3b = any(set(filed.get(m, {})) & set(TABLE31) for m in grp)
            filed_g: dict[str, Gstr3bValues] = {}
            for m in grp:
                for code, v in filed.get(m, {}).items():
                    filed_g[code] = filed_g.get(code, Gstr3bValues()) + v
            w = build_liability(period, summ, [], filed_g if has_3b else None, rules)
            g1 = {r.code: r.gstr1 for r in w.rows}
            left = (g1["31A"] + g1["31B"]) if has_1 else None
            right = (filed_g.get("31A", Gstr3bValues()) + filed_g.get("31B", Gstr3bValues())) if has_3b else None
            if has_1 and not summ:
                out.notes.append(f"{_label(grp)}: GSTR-1 imported without section totals (Excel / invoice list) – "
                                 "import the GSTR-1 JSON from the portal for the full liability (B2C, exports, "
                                 "notes).")
            out.rows.append(MonthRow(period, grp, left, right,
                                     left_docs=sum(avail.have["GSTR1"].get(m, 0) for m in grp) if has_1 else None))
            for code in ("31A", "31B", "31C", "31E"):
                out.details.append(DetailRow(period, TABLE31[code], g1[code] if has_1 else None,
                                             filed_g.get(code, Gstr3bValues()) if has_3b else None, taxable=True))
            out.details.append(DetailRow(period, "3.1(a) + (b) Tax liability", left, right, taxable=True))
            if w.rcm_outward.taxable and has_1:
                out.details.append(DetailRow(period, "Supplies where the recipient pays tax (reverse charge) – "
                                             "not in the supplier's liability", w.rcm_outward, None, taxable=True))
            if left is None or right is None:
                continue
            for f in w.findings:
                if f.kind in ("statutory", "timing") or (f.kind == "info" and "amendment" in f.text):
                    out.findings.append(Finding(period, f.severity, f.text, f.amount))
            d = left - right
            short_year += d.total
            heads = [h.upper() for h in HEADS if getattr(d, h) > TOLERANCE]
            if heads and d.total <= TOLERANCE:
                out.findings.append(Finding(period, "medium", "Total tax agrees but GSTR-1 has more "
                                            f"{', '.join(heads)} than GSTR-3B – tax paid under the wrong head "
                                            "(IGST in place of CGST/SGST or the other way)",
                                            sum((getattr(d, h) for h in HEADS if getattr(d, h) > 0), ZERO)))
        if short_year > TOLERANCE:
            out.findings.append(Finding("Year", "high", f"For the months compared, GSTR-1 liability exceeds GSTR-3B by "
                                        f"₹{short_year:,.2f} in total – pay the difference with interest (DRC-03) "
                                        "or in a later GSTR-3B", short_year))
        elif short_year < -TOLERANCE:
            out.findings.append(Finding("Year", "info", f"For the months compared, GSTR-3B tax exceeds GSTR-1 by "
                                        f"₹{-short_year:,.2f} – check for invoices left out of GSTR-1",
                                        -short_year))

    # ---- GSTR-2A vs GSTR-2B -------------------------------------------
    def _docs_2a_2b(self, client: Client, fy: str, groups, avail: Availability, out: Comparison) -> None:
        months = fy_months(fy)
        a_docs = self._docs(client.id, Source.GSTR2A, months)
        b_docs = self._docs(client.id, Source.GSTR2B, months)

        def key(r: InvoiceRecord):
            return (r.supplier_gstin, loose_invoice_no(r.invoice_no), r.doc_type.value, r.is_amendment)

        pool: dict[tuple, list[InvoiceRecord]] = defaultdict(list)
        for r in sorted(b_docs, key=lambda r: r.period):
            pool[key(r)].append(r)
        b_have = {m for m in months if avail.has("GSTR2B", m)}
        for a in sorted(a_docs, key=lambda r: (r.period, r.supplier_gstin, r.invoice_no)):
            cands = pool.get(key(a))
            ia = a.signed("itc")
            if not cands:
                later = [m for m in b_have if m > a.period]
                note = "" if later else "GSTR-2B of later months not imported – it may still come there"
                out.docs.append(DocRow(ONLY_2A, a.supplier_gstin, a.supplier_name, a.invoice_no, a.invoice_date,
                                       a.doc_type.value, a.period, "", ia, None, note))
                continue
            b = next((c for c in cands if c.period == a.period), cands[0])
            cands.remove(b)
            ib = b.signed("itc")
            if b.itc_availability == "N":
                status, note = NOT_AVAILABLE, b.itc_reason or "GSTR-2B shows ITC not available"
            elif abs(ia - ib) > TOLERANCE:
                status, note = AMOUNT, f"Tax differs by ₹{ia - ib:,.2f}"
            elif b.period > a.period:
                status, note = LATER, "Supplier filed after the GSTR-2B cut-off – ITC belongs to the later month"
            elif b.period < a.period:
                status, note = EARLIER, ""
            else:
                status, note = MATCHED, ""
            out.docs.append(DocRow(status, a.supplier_gstin, a.supplier_name or b.supplier_name, a.invoice_no,
                                   a.invoice_date, a.doc_type.value, a.period, b.period, ia, ib, note))
        for rest in pool.values():
            for b in rest:
                note = "" if avail.has("GSTR2A", b.period) else "GSTR-2A of this month not imported"
                if b.supplier_period and b.supplier_period[:2].isdigit():
                    note = (note + "; " if note else "") + f"supplier's return period {b.supplier_period}"
                out.docs.append(DocRow(ONLY_2B, b.supplier_gstin, b.supplier_name, b.invoice_no, b.invoice_date,
                                       b.doc_type.value, "", b.period, None, b.signed("itc"), note))
        order = {s: i for i, s in enumerate(DOC_STATUSES)}
        out.docs.sort(key=lambda d: (order[d.status], d.period_2a or d.period_2b, d.gstin, d.invoice_no))

        a_by: dict[str, Gstr3bValues] = defaultdict(Gstr3bValues)
        b_by: dict[str, Gstr3bValues] = defaultdict(Gstr3bValues)
        for r in a_docs:
            a_by[r.period] = a_by[r.period] + _doc_values(r)
        for r in b_docs:
            b_by[r.period] = b_by[r.period] + _doc_values(r)
        for m in months:  # GSTR-2A and GSTR-2B are monthly statements, also for quarterly filers
            has_a, has_b = avail.has("GSTR2A", m), avail.has("GSTR2B", m)
            row = MonthRow(m, [m], a_by[m] if has_a else None, b_by[m] if has_b else None,
                           avail.have["GSTR2A"].get(m) if has_a else None,
                           avail.have["GSTR2B"].get(m) if has_b else None)
            out.rows.append(row)
            ds = [d for d in out.docs if (d.period_2a or d.period_2b) == m]
            for st in DOC_STATUSES:
                sel = [d for d in ds if d.status == st]
                if not sel:
                    continue
                a_v = sum((d.itc_2a or ZERO for d in sel), ZERO)
                b_v = sum((d.itc_2b or ZERO for d in sel), ZERO)
                out.details.append(DetailRow(m, f"{st} – {len(sel)} document(s)", Gstr3bValues(igst=a_v),
                                             Gstr3bValues(igst=b_v)))
        counts = out.doc_counts()
        only_2a = [d for d in out.docs if d.status == ONLY_2A]
        if only_2a:
            out.findings.append(Finding("Year", "high", f"{len(only_2a)} document(s) filed by suppliers (GSTR-2A) not "
                                        "in any GSTR-2B imported – no ITC on them until they reach a GSTR-2B",
                                        sum((d.itc_2a or ZERO for d in only_2a), ZERO)))
        if counts[LATER]:
            amt = sum((d.itc_2b or ZERO for d in out.docs if d.status == LATER), ZERO)
            out.findings.append(Finding("Year", "medium", f"{counts[LATER]} document(s) reached a later month's GSTR-2B "
                                        "(supplier filed late) – claim the ITC in that later month", amt))
        if counts[AMOUNT]:
            amt = sum((abs(d.diff or ZERO) for d in out.docs if d.status == AMOUNT), ZERO)
            out.findings.append(Finding("Year", "medium", f"{counts[AMOUNT]} document(s) with different tax in GSTR-2A "
                                        "and GSTR-2B (amended by the supplier?)", amt))
        if counts[NOT_AVAILABLE]:
            amt = sum((d.itc_2b or ZERO for d in out.docs if d.status == NOT_AVAILABLE), ZERO)
            out.findings.append(Finding("Year", "medium", f"{counts[NOT_AVAILABLE]} document(s) in GSTR-2B with ITC "
                                        "not available (time limit, place of supply, etc.)", amt))
        out.notes.append("Documents are matched on supplier GSTIN, invoice number (written either way), type and "
                         "amendment; GSTR-2A month is the supplier's filing month, GSTR-2B month is the statement "
                         "the document reached.")

    # ----------------------------------------------------- portal imports
    def import_portal_files(self, client_id: int, paths, user: str | None = None) -> list[tuple[str, bool, str]]:
        """Import returns downloaded from the GST portal (GSTR-1, GSTR-3B, GSTR-2A, GSTR-2B as JSON / ZIP / Excel,
        the filed GSTR-3B as PDF). The file's GSTIN decides the client; a file without a GSTIN is taken for the
        client that is open. Returns (file name, saved?, message) for each file; nothing is uploaded anywhere."""
        from ..importers.pipeline import MappingRequired
        from ..importers.readers import UnsupportedFileError
        from .portal import PortalService, recognise

        portal = PortalService(self.db)
        client = self._client(client_id)
        out = []
        for path in paths:
            path = Path(path)
            try:
                pf = portal.inspect(path, client_id)
            except (OSError, ValueError) as exc:
                out.append((path.name, False, f"could not be read: {exc}"))
                continue
            if pf is None:
                out.append((path.name, False, "not a GST portal return (GSTR-1 / 3B / 2A / 2B) – nothing saved"))
                continue
            if pf.client_id is None:
                _kind, seen, _period = recognise(path)
                if seen:
                    out.append((path.name, False, pf.status))
                    continue
                pf.client_id, pf.client_name, pf.gstin = client.id, client.name, client.gstin
                with self.db.session() as s:
                    from ..importers.pipeline import sha256_of

                    dup = s.scalar(select(SourceFile.id).where(SourceFile.client_id == client.id,
                                                               SourceFile.sha256 == sha256_of(path)))
                pf.status = f"Already imported (import #{dup})" if dup else "Ready"
            if not pf.ready:
                out.append((path.name, False, pf.status))
                continue
            try:
                msg = portal.import_file(pf, user)
            except (ServiceError, UnsupportedFileError, MappingRequired, ValueError, OSError) as exc:
                out.append((path.name, False, f"{pf.label}: {exc}"))
                continue
            if pf.client_id != client.id:
                msg += f" – for {pf.client_name} (the GSTIN in the file)"
            out.append((path.name, True, msg))
        return out

    def downloads(self, client_id: int, folder: str | Path, days: int = 7):
        """Returns of this client saved in the folder in the last few days and not imported yet."""
        from .portal import PortalService

        return [pf for pf in PortalService(self.db).scan(folder, days, client_id)
                if pf.kind in RETURN_TYPES and pf.client_id == client_id and pf.ready
                and not (pf.period is None and pf.path.suffix.lower() in (".xlsx", ".xls", ".xlsm", ".csv"))]
        # a spreadsheet without a return period is not a portal download (e.g. a report saved by this program)

    # ------------------------------------------------------------- export
    def export_xlsx(self, comps: list[Comparison], path: str | Path) -> Path:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill

        wb = Workbook()
        wb.remove(wb.active)
        head_fill = PatternFill("solid", fgColor="1F3864")
        red = PatternFill("solid", fgColor="FFCDD2")
        money = "#,##,##0.00"

        def header(ws, cols):
            ws.append(cols)
            for c in ws[ws.max_row]:
                c.font = Font(bold=True, color="FFFFFF")
                c.fill = head_fill

        def f(v):
            return None if v is None else float(v)

        for comp in comps:
            a, b = comp.sides
            ws = wb.create_sheet({"3B_2B": "3B vs 2B", "1_3B": "1 vs 3B", "2A_2B": "2A vs 2B"}[comp.kind])
            ws.append([f"{comp.client} ({comp.gstin}) – {comp.title} – {comp.fy}"])
            ws["A1"].font = Font(bold=True, size=13)
            cols = ["Month", "Status"]
            for side in (a, b, "Difference"):
                cols += [f"{side} {h.upper()}" for h in HEADS] + [f"{side} total"]
            header(ws, cols)
            for r in comp.rows:
                vals = [r.label, r.status(a, b)]
                for v in (r.left, r.right, r.diff):
                    vals += [f(getattr(v, h)) if v is not None else None for h in HEADS] + [
                        f(v.total) if v is not None else None]
                ws.append(vals)
                if vals[1] == "Difference":
                    for c in ws[ws.max_row]:
                        c.fill = red
            tl, tr = comp.total("left"), comp.total("right")
            ws.append(["Total (months with both returns)", ""] + [f(getattr(v, h)) for v in (tl, tr, tl - tr)
                                                                  for h in (*HEADS, "total")])
            ws[ws.max_row][0].font = Font(bold=True)
            for row in ws.iter_rows(min_row=3, min_col=3):
                for c in row:
                    c.number_format = money
            ws.column_dimensions["A"].width = 30
            ws.column_dimensions["B"].width = 22
            d = wb.create_sheet(ws.title + " detail")
            header(d, ["Month", "Line", f"{a} taxable", f"{a} tax", f"{b} taxable", f"{b} tax", "Difference (tax)"])
            labels = {r.period: r.label for r in comp.rows}
            for x in comp.details:
                d.append([labels.get(x.period, x.period), x.label,
                          f(x.left.taxable) if x.left is not None and x.taxable else None,
                          f(x.left.total) if x.left is not None else None,
                          f(x.right.taxable) if x.right is not None and x.taxable else None,
                          f(x.right.total) if x.right is not None else None,
                          f(x.diff.total) if x.diff is not None else None])
            for row in d.iter_rows(min_row=2, min_col=3):
                for c in row:
                    c.number_format = money
            d.column_dimensions["A"].width = 14
            d.column_dimensions["B"].width = 70
            if comp.docs:
                dd = wb.create_sheet("2A vs 2B documents")
                header(dd, ["Status", "Supplier GSTIN", "Supplier", "Invoice no", "Date", "Type", "GSTR-2A month",
                            "GSTR-2B month", "Tax in GSTR-2A", "Tax in GSTR-2B", "Difference", "Note"])
                for x in comp.docs:
                    dd.append([x.status, x.gstin, x.name, x.invoice_no, x.invoice_date, x.doc_type, x.period_2a,
                               x.period_2b, f(x.itc_2a), f(x.itc_2b), f(x.diff), x.note])
                for row in dd.iter_rows(min_row=2, min_col=9, max_col=11):
                    for c in row:
                        c.number_format = money
                for col, w in zip("ABCDEFGHIJKL", (26, 17, 30, 18, 11, 6, 12, 12, 14, 14, 13, 60)):
                    dd.column_dimensions[col].width = w
            if comp.findings or comp.notes:
                fs = wb.create_sheet(ws.title + " findings")
                header(fs, ["Month", "Severity", "Finding", "Amount"])
                for x in comp.findings:
                    fs.append([labels.get(x.period, x.period), x.severity, x.text, f(x.amount)])
                for n in comp.notes:
                    fs.append(["", "note", n, None])
                fs.column_dimensions["C"].width = 110
        path = Path(path)
        wb.save(path)
        return path
