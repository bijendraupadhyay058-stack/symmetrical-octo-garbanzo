"""Document-level ITC review of a reconciliation run, and the ITC summary buckets.

Inputs are plain data (lines, rules, claim states, reviewer decisions, IMS actions),
so the logic is testable without a database. Nothing here concludes that credit
is (in)eligible: each hit carries the statutory reference and guidance for the
reviewer, who confirms or dismisses it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..core.models import PAIRED_CATEGORIES, Category, DocType, Flag, InvoiceRecord, ReconLine
from ..core.money import ZERO
from .deadlines import itc_deadline
from .rules import Rule

SEVERITY_RANK = {"high": 0, "medium": 1, "info": 2}


@dataclass
class ClaimState:
    claimed: Decimal = ZERO  # magnitudes (total of IGST+CGST+SGST+cess)
    reversed: Decimal = ZERO
    reclaimed: Decimal = ZERO
    periods: list[str] = field(default_factory=list)

    @property
    def net(self) -> Decimal:
        return self.claimed - self.reversed + self.reclaimed

    @property
    def is_claimed(self) -> bool:
        return self.claimed > 0


@dataclass
class RuleHit:
    code: str
    title: str
    reference: str
    severity: str
    category: str
    message: str
    guidance: str = ""
    decision: str = ""  # "", CONFIRMED, DISMISSED
    remarks: str = ""

    @property
    def open(self) -> bool:
        return self.decision != "DISMISSED"


@dataclass
class DocReview:
    record: InvoiceRecord
    line_no: int
    line_category: Category
    in_2b: bool
    itc: Decimal  # signed ITC of this document (credit notes negative)
    hits: list[RuleHit] = field(default_factory=list)
    claim: ClaimState = field(default_factory=ClaimState)
    deadline: date | None = None
    days_left: int | None = None

    @property
    def open_hits(self) -> list[RuleHit]:
        return [h for h in self.hits if h.open]

    @property
    def worst(self) -> str:
        sev = [h.severity for h in self.open_hits]
        return min(sev, key=SEVERITY_RANK.get) if sev else ""

    def has(self, category: str, open_only: bool = True) -> bool:
        return any(h.category == category for h in (self.open_hits if open_only else self.hits))


def _hit(rule: Rule, message: str) -> RuleHit:
    return RuleHit(rule.code, rule.title, rule.reference, rule.severity, rule.category, message, rule.guidance)


def review_lines(lines: list[ReconLine], rules: list[Rule], as_of: date,
                 claims: dict[int, ClaimState] | None = None,
                 decisions: dict[tuple[int, str], tuple[str, str]] | None = None,
                 ims_actions: dict[int, str] | None = None) -> list[DocReview]:
    claims = claims or {}
    decisions = decisions or {}
    ims_actions = ims_actions or {}
    by_code = {r.code: r for r in rules}
    keyword_rules = [r for r in rules if r.kind == "keyword"]
    gstin_rules = [r for r in rules if r.kind == "gstin"]
    out: list[DocReview] = []

    def builtin(code: str, d: date) -> Rule | None:
        r = by_code.get(code)
        return r if r is not None and r.applies_on(d) else None

    for ln in lines:
        b, g = ln.books, ln.gstr2b
        if b is not None:
            paired = ln.category in PAIRED_CATEGORIES and g is not None
            rev = DocReview(b, ln.line_no, ln.category, paired, b.signed("itc"),
                            claim=claims.get(b.db_id, ClaimState()) if b.db_id else ClaimState())
            d = b.invoice_date
            for r in keyword_rules:
                if r.applies_on(d):
                    kw = r.keyword_hit(b.supplier_name, b.description, g.supplier_name if g else "")
                    if kw:
                        rev.hits.append(_hit(r, f"'{kw}' found in supplier name / narration"))
            for r in gstin_rules:
                if r.applies_on(d) and b.supplier_gstin in r.gstins:
                    rev.hits.append(_hit(r, f"Supplier {b.supplier_gstin} is on the client's blocked list"))
            if not paired and (r := builtin("S16_2_AA", d)):
                rev.hits.append(_hit(r, f"Not matched to GSTR-2B ({ln.category.value})"))
            if paired and Flag.ITC_NOT_AVAILABLE.value in ln.flags and (r := builtin("ITC_NA_2B", d)):
                reason = f": {g.itc_reason}" if g.itc_reason else ""
                rev.hits.append(_hit(r, "GSTR-2B shows ITC availability 'No'" + reason))
            if (b.reverse_charge or (g is not None and g.reverse_charge)) and (r := builtin("RCM", d)):
                rev.hits.append(_hit(r, "Supply attracts reverse charge"))
            action = ims_actions.get(b.db_id) if b.db_id else None
            if action == "R" and (r := builtin("IMS_REJECTED", d)):
                rev.hits.append(_hit(r, "Rejected in IMS"))
            elif action == "P" and (r := builtin("IMS_PENDING", d)):
                rev.hits.append(_hit(r, "Kept pending in IMS"))
            if b.doc_type != DocType.CREDIT_NOTE and rev.itc > 0:
                deadline, basis = itc_deadline(d)
                rev.deadline, rev.days_left = deadline, (deadline - as_of).days
                r = builtin("S16_4", d)
                if r is not None and not rev.claim.is_claimed:
                    alert = int(r.params.get("alert_days", 60))
                    if rev.days_left < 0:
                        rev.hits.append(_hit(r, f"Not yet claimed and the time limit ({deadline:%d-%m-%Y}) has "
                                                f"passed – {basis}"))
                    elif rev.days_left <= alert:
                        hit = _hit(r, f"Not yet claimed; time limit {deadline:%d-%m-%Y} is {rev.days_left} day(s) away")
                        hit.severity = "medium"
                        rev.hits.append(hit)
                r = builtin("RULE_37_180", d)
                if r is not None and rev.claim.is_claimed and (as_of - d).days > int(r.params.get("days", 180)):
                    rev.hits.append(_hit(r, f"Invoice is {(as_of - d).days} days old – verify payment to supplier"))
            out.append(rev)
        elif g is not None and g.doc_type == DocType.CREDIT_NOTE and ln.category == Category.MISSING_IN_BOOKS:
            rev = DocReview(g, ln.line_no, ln.category, True, g.signed("itc"))
            if r := builtin("CN_2B_NOT_BOOKED", g.invoice_date):
                rev.hits.append(_hit(r, f"Credit note of ₹{-rev.itc} ITC is in GSTR-2B but not in books"))
            out.append(rev)
    for rev in out:
        for h in rev.hits:
            dec = decisions.get((rev.record.db_id, h.code)) if rev.record.db_id else None
            if dec:
                h.decision, h.remarks = dec
        rev.hits.sort(key=lambda h: (SEVERITY_RANK.get(h.severity, 9), h.code))
    return out


BUCKET_LABELS = [
    ("itc_books", "ITC as per books"),
    ("itc_2b", "ITC appearing in GSTR-2B"),
    ("itc_3b", "ITC claimed in GSTR-3B (Table 4(A), filed)"),
    ("claimed_register", "ITC claimed (claim register)"),
    ("not_claimed", "ITC not yet claimed"),
    ("claimed_needs_verification", "ITC claimed but requiring verification"),
    ("reversed", "ITC reversed"),
    ("reclaimed", "ITC reclaimed"),
    ("carried_forward", "ITC carried forward for review (not yet in GSTR-2B)"),
    ("blocked_17_5", "ITC potentially blocked – Section 17(5)"),
    ("time_limit_exposure", "Potential time-limit exposure – Section 16(4)"),
    ("credit_note_adjustments", "Credit-note adjustments (books)"),
    ("cn_in_2b_not_booked", "Credit notes in GSTR-2B not in books"),
    ("reverse_charge", "Reverse-charge ITC (after payment of tax)"),
    ("isd", "ISD credits (GSTR-2B)"),
    ("imports", "Import of goods (GSTR-2B bills of entry)"),
]


def buckets(reviews: list[DocReview], lines: list[ReconLine], itc_3b: Decimal | None = None,
            isd: Decimal = ZERO, imports: Decimal = ZERO) -> dict[str, Decimal]:
    """ITC summary. Each figure is a sum over documents; a document may appear in more than one
    *review* bucket (e.g. blocked and not claimed) – the buckets are views, not a partition."""
    out = {k: ZERO for k, _ in BUCKET_LABELS}
    for ln in lines:
        if ln.books is not None and not ln.books.is_prior_period:
            out["itc_books"] += ln.books.signed("itc")
        if ln.gstr2b is not None:
            out["itc_2b"] += ln.gstr2b.signed("itc")
    for r in reviews:
        if r.record.source.value != "BOOKS":
            out["cn_in_2b_not_booked"] += r.itc
            continue
        sign = -1 if r.record.doc_type == DocType.CREDIT_NOTE else 1
        out["claimed_register"] += r.claim.claimed * sign
        out["reversed"] += r.claim.reversed * sign
        out["reclaimed"] += r.claim.reclaimed * sign
        if not r.claim.is_claimed:
            out["not_claimed"] += r.itc
            if not r.in_2b:
                out["carried_forward"] += r.itc
        elif r.worst in ("high", "medium") or not r.in_2b:
            out["claimed_needs_verification"] += r.claim.net * sign
        if r.has("blocked"):
            out["blocked_17_5"] += r.itc
        if any(h.code == "S16_4" and h.open for h in r.hits):
            out["time_limit_exposure"] += r.itc
        if r.record.doc_type == DocType.CREDIT_NOTE:
            out["credit_note_adjustments"] += r.itc
        if r.has("rcm"):
            out["reverse_charge"] += r.itc
    out["itc_3b"] = itc_3b if itc_3b is not None else ZERO
    out["isd"], out["imports"] = isd, imports
    return out
