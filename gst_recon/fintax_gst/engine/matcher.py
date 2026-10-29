"""Deterministic invoice-level reconciliation engine.

The engine is a pure function of its inputs: it takes books records, GSTR-2B
records (and optionally unmatched books records of earlier periods) plus
settings, and returns reconciliation lines. It never touches the database,
files or the UI, so the same code serves the desktop app, the CLI and a
future web API.

Guarantees (enforced by ``_check_integrity``):
* every current-period books record and every GSTR-2B record appears in
  exactly one line; nothing is dropped;
* a record is paired with at most one counterpart (no many-to-many);
* results depend only on record content, uid and settings, not on input order.

Passes, in order (each pass only sees records still unmatched):
  0. duplicate detection within each source (excluded from auto-matching)
  1. exact key: GSTIN + document type + normalised invoice number
  2. loose key: as 1 but leading zeros ignored (invoice-number variation)
  3. amendments: GSTR-2B amendment's original number against books
  4. previous period: GSTR-2B against unmatched books of earlier periods
  5. GSTIN mismatch: same number and value under a different GSTIN (review only)
  6. fuzzy invoice number within a supplier (review only, never auto-confirmed)
  7. whatever remains is missing on the other side
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Callable, Iterable

from rapidfuzz import fuzz

from .. import ENGINE_VERSION
from ..core.gstin import pan_of
from ..core.invoice_no import normalize_invoice_no, same_text
from ..core.models import (
    AMOUNT_FIELDS, Category, DocType, ExceptionStatus, Flag, InvoiceRecord, ReconLine,
    ReconSettings, Source,
)
from ..core.money import ZERO, q2

ProgressFn = Callable[[int, str], None]


class OperationCancelled(Exception):
    """Raised when the user cancels; nothing has been persisted at that point."""


class ReconciliationIntegrityError(RuntimeError):
    pass


class CancelToken:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def check(self) -> None:
        if self.cancelled:
            raise OperationCancelled("Operation cancelled by user")


@dataclass
class ReconResult:
    lines: list[ReconLine]
    settings: ReconSettings
    books: list[InvoiceRecord]
    gstr2b: list[InvoiceRecord]
    prior_books_considered: int = 0
    period_start: date | None = None
    fingerprint: str = ""
    engine_version: str = ENGINE_VERSION
    meta: dict = field(default_factory=dict)


_DIFF_FLAGS = {
    "taxable": Flag.TAXABLE_DIFF, "igst": Flag.IGST_DIFF, "cgst": Flag.CGST_DIFF,
    "sgst": Flag.SGST_DIFF, "cess": Flag.CESS_DIFF,
}
_FIELD_LABEL = {"taxable": "Taxable value", "igst": "IGST", "cgst": "CGST", "sgst": "SGST", "cess": "Cess"}


def _fmt(d: date) -> str:
    return d.strftime("%d-%m-%Y")


class _Engine:
    def __init__(self, books, gstr2b, prior_books, settings, period_start, progress, cancel):
        self.s = settings
        self.books = sorted(books, key=InvoiceRecord.sort_key)
        self.g2b = sorted(gstr2b, key=InvoiceRecord.sort_key)
        self.prior = sorted(prior_books, key=InvoiceRecord.sort_key)
        for r in self.prior:
            r.is_prior_period = True
        self.period_start = period_start
        self.progress = progress or (lambda pct, msg: None)
        self.cancel = cancel
        self.used: set[str] = set()
        self.lines: list[ReconLine] = []
        self.by_uid = {r.uid: r for r in (*self.books, *self.g2b, *self.prior)}
        if len(self.by_uid) != len(self.books) + len(self.g2b) + len(self.prior):
            raise ValueError("Record uids must be unique across all inputs")

    # ------------------------------------------------------------------ helpers
    def _tick(self, pct: int, message: str) -> None:
        if self.cancel is not None:
            self.cancel.check()
        self.progress(pct, message)

    def _free(self, records: Iterable[InvoiceRecord]) -> list[InvoiceRecord]:
        return [r for r in records if r.uid not in self.used]

    def _add(self, line: ReconLine) -> None:
        for r in (line.books, line.gstr2b):
            if r is not None:
                if r.uid in self.used:
                    raise ReconciliationIntegrityError(f"record {r.uid} assigned twice")
                self.used.add(r.uid)
        self.lines.append(line)

    def _within(self, diff: Decimal) -> bool:
        return abs(diff) <= self.s.amount_tolerance

    @staticmethod
    def _mutual_unique(edges: list[tuple[InvoiceRecord, InvoiceRecord]]):
        bdeg: dict[str, int] = defaultdict(int)
        gdeg: dict[str, int] = defaultdict(int)
        for b, g in edges:
            bdeg[b.uid] += 1
            gdeg[g.uid] += 1
        return [(b, g) for b, g in edges if bdeg[b.uid] == 1 and gdeg[g.uid] == 1]

    def _key_pairs(self, books, g2b, bkey, gkey):
        """Pair records sharing a key. A key with one record on each side pairs
        directly; otherwise only mutually unique pairs within the date tolerance
        are formed and the rest stay unmatched for later passes."""
        bidx: dict[tuple, list] = defaultdict(list)
        gidx: dict[tuple, list] = defaultdict(list)
        for b in books:
            k = bkey(b)
            if k is not None:
                bidx[k].append(b)
        for g in g2b:
            k = gkey(g)
            if k is not None:
                gidx[k].append(g)
        pairs = []
        for key in sorted(bidx.keys() & gidx.keys()):
            bs, gs = bidx[key], gidx[key]
            if len(bs) == 1 and len(gs) == 1:
                pairs.append((bs[0], gs[0]))
                continue
            edges = [
                (b, g) for b in bs for g in gs
                if abs((b.invoice_date - g.invoice_date).days) <= self.s.date_tolerance_days
            ]
            pairs.extend(self._mutual_unique(edges))
        return pairs

    # ------------------------------------------------------------ classification
    def _differences(self, b: InvoiceRecord, g: InvoiceRecord):
        flags, reasons, rounding = [], [], []
        for name in AMOUNT_FIELDS:
            d = b.signed(name) - g.signed(name)
            if d == 0:
                continue
            if self._within(d):
                rounding.append(f"{_FIELD_LABEL[name]} {q2(d)}")
            else:
                flags.append(_DIFF_FLAGS[name])
                reasons.append(
                    f"{_FIELD_LABEL[name]} differs: books {q2(b.signed(name))} vs GSTR-2B "
                    f"{q2(g.signed(name))} (difference {q2(d)})"
                )
        if rounding:
            flags.append(Flag.ROUNDING)
            reasons.append(f"Within ₹{self.s.amount_tolerance} tolerance: " + ", ".join(rounding))
        heads_differ = Flag.IGST_DIFF in flags and (Flag.CGST_DIFF in flags or Flag.SGST_DIFF in flags)
        if heads_differ and self._within(b.signed("itc") - g.signed("itc")):
            flags.append(Flag.TAX_HEAD_SWAP)
            reasons.append("Total GST agrees but is charged under a different head (IGST vs CGST/SGST); check place of supply")
        return flags, reasons

    def _common_flags(self, g: InvoiceRecord | None, flags: list, reasons: list) -> None:
        if g is None:
            return
        if g.itc_availability.upper() in ("N", "NO"):
            flags.append(Flag.ITC_NOT_AVAILABLE)
            reasons.append("GSTR-2B shows ITC availability 'No'" + (f" ({g.itc_reason})" if g.itc_reason else ""))
        if g.reverse_charge:
            flags.append(Flag.REVERSE_CHARGE)
            reasons.append("Supply attracts reverse charge – ITC depends on tax paid under RCM")

    def _similarity(self, b: InvoiceRecord, g: InvoiceRecord) -> tuple[int, int, int, int]:
        """Return (confidence, number_score, amount_score, date_score), each 0-100."""
        num = int(round(fuzz.ratio(b.invoice_no_norm, g.invoice_no_norm)))
        base = max(abs(b.taxable), abs(g.taxable), Decimal(1))
        tdiff = abs(b.signed("taxable") - g.signed("taxable"))
        if self._within(tdiff) and self._within(b.signed("itc") - g.signed("itc")):
            amt = 100
        else:
            amt = max(0, 100 - int(tdiff * 500 / base))  # 20 % difference -> 0
        days = abs((b.invoice_date - g.invoice_date).days)
        span = max(self.s.date_tolerance_days * 4, 1)
        dscore = 100 if days == 0 else max(0, 100 - days * 100 // span)
        conf = int(round(0.6 * num + 0.3 * amt + 0.1 * dscore))
        return conf, num, amt, dscore

    def _pair_line(self, b: InvoiceRecord, g: InvoiceRecord, via: str) -> ReconLine:
        flags: list = []
        reasons: list = []
        days = (b.invoice_date - g.invoice_date).days
        if via != "amendment" and not same_text(b.invoice_no, g.invoice_no):
            flags.append(Flag.NUMBER_VARIATION)
            reasons.append(f"Invoice number format differs: books '{b.invoice_no}' vs GSTR-2B '{g.invoice_no}'")
        if days:
            if abs(days) > self.s.date_tolerance_days:
                return self._probable_pair(b, g, Flag.DATE_BEYOND_TOLERANCE, (
                    f"Invoice reference matches but dates differ by {abs(days)} days "
                    f"(books {_fmt(b.invoice_date)}, GSTR-2B {_fmt(g.invoice_date)}; "
                    f"tolerance {self.s.date_tolerance_days} days)"))
            flags.append(Flag.DATE_DIFF)
            reasons.append(
                f"Invoice date differs by {abs(days)} day(s): books {_fmt(b.invoice_date)} vs "
                f"GSTR-2B {_fmt(g.invoice_date)}")
        dflags, dreasons = self._differences(b, g)
        flags += dflags
        reasons += dreasons
        if g.is_amendment:
            flags.append(Flag.AMENDMENT)
            reasons.append(
                f"GSTR-2B record is an amendment of original document '{g.original_invoice_no}'"
                + (f" dated {_fmt(g.original_invoice_date)}" if g.original_invoice_date else ""))
        if b.is_prior_period:
            flags.append(Flag.PRIOR_PERIOD)
            reasons.append(f"Booked in earlier period {b.period}; reflected in GSTR-2B of {g.period}")
        self._common_flags(g, flags, reasons)

        kinds = []
        if Flag.NUMBER_VARIATION in flags:
            kinds.append(Category.NUMBER_VARIATION)
        if Flag.DATE_DIFF in flags:
            kinds.append(Category.DATE_DIFFERENCE)
        if Flag.TAXABLE_DIFF in flags:
            kinds.append(Category.TAXABLE_DIFFERENCE)
        if Flag.IGST_DIFF in flags:
            kinds.append(Category.IGST_DIFFERENCE)
        if Flag.CGST_DIFF in flags or Flag.SGST_DIFF in flags:
            kinds.append(Category.CGST_SGST_DIFFERENCE)
        if Flag.CESS_DIFF in flags:
            kinds.append(Category.CESS_DIFFERENCE)

        if via == "prior":
            category = Category.PREVIOUS_PERIOD
        elif g.is_amendment:
            category = Category.AMENDED
        elif kinds and b.doc_type != DocType.INVOICE:
            category = Category.CDN_DIFFERENCE
        elif not kinds:
            category = Category.FULLY_MATCHED
        elif len(kinds) == 1:
            category = kinds[0]
        else:
            category = Category.MULTIPLE_DIFFERENCES

        amount_flags = {Flag.TAXABLE_DIFF, Flag.IGST_DIFF, Flag.CGST_DIFF, Flag.SGST_DIFF, Flag.CESS_DIFF}
        if amount_flags & set(flags):
            level = 4
        elif Flag.DATE_DIFF in flags:
            level = 3
        elif Flag.NUMBER_VARIATION in flags or via in ("loose", "amendment"):
            level = 2
        else:
            level = 1
        status = ExceptionStatus.PENDING_REVIEW
        if category == Category.FULLY_MATCHED and Flag.ITC_NOT_AVAILABLE not in flags:
            status = ExceptionStatus.NO_ACTION
        confidence = {"exact": 100, "loose": 95, "amendment": 90, "prior": 95}[via]
        return ReconLine(
            line_no=0, category=category, books=b, gstr2b=g, match_level=level, confidence=confidence,
            flags=[f.value for f in flags], reasons=reasons, date_diff_days=days, status=status,
        )

    def _probable_pair(self, b, g, flag: Flag, reason: str, confidence: int | None = None) -> ReconLine:
        flags = [flag]
        reasons = [reason, "Suggested match only – confirm or reject manually"]
        if b.supplier_gstin == g.supplier_gstin or flag == Flag.GSTIN_MISMATCH:
            dflags, dreasons = self._differences(b, g)
            flags += dflags
            reasons += dreasons
        self._common_flags(g, flags, reasons)
        if confidence is None:
            confidence = self._similarity(b, g)[0]
        return ReconLine(
            line_no=0, category=Category.PROBABLE, books=b, gstr2b=g, match_level=5,
            confidence=confidence, flags=[f.value for f in flags], reasons=reasons,
            candidates=[g.uid], date_diff_days=(b.invoice_date - g.invoice_date).days,
        )

    # ------------------------------------------------------------------- passes
    def _duplicates(self) -> None:
        def dup_key(r: InvoiceRecord):
            return (r.supplier_gstin, r.doc_type.value, r.invoice_no_norm, r.fy)

        def groups(records):
            idx = defaultdict(list)
            for r in records:
                idx[dup_key(r)].append(r)
            return {k: v for k, v in idx.items() if len(v) > 1}

        dup_b, dup_g = groups(self.books), groups(self.g2b)
        for source_label, dups, category in (
            ("books", dup_b, Category.DUPLICATE_IN_BOOKS), ("GSTR-2B", dup_g, Category.DUPLICATE_IN_2B),
        ):
            for key in sorted(dups):
                members = dups[key]
                refs = ", ".join(m.reference for m in members)
                for m in members:
                    line = ReconLine(
                        line_no=0, category=category, match_level=None,
                        reasons=[f"{len(members)} entries in {source_label} share supplier GSTIN, document type, "
                                 f"invoice number and financial year: {refs}"],
                        candidates=[o.uid for o in members if o.uid != m.uid],
                    )
                    if category == Category.DUPLICATE_IN_BOOKS:
                        line.books = m
                    else:
                        line.gstr2b = m
                        self._common_flags(m, line.flags, line.reasons)
                    self._add(line)
        # The other side's copy of a duplicated document cannot be paired automatically.
        for dups, others, is_books in ((dup_b, self.g2b, True), (dup_g, self.books, False)):
            for r in self._free(others):
                key = dup_key(r)
                if key in dups:
                    where = "books" if is_books else "GSTR-2B"
                    line = ReconLine(
                        line_no=0, category=Category.PROBABLE, match_level=5,
                        flags=[Flag.COUNTERPART_DUPLICATED.value],
                        reasons=[f"Matching document is entered {len(dups[key])} times in {where}; "
                                 "select the correct entry manually"],
                        candidates=[m.uid for m in dups[key]],
                    )
                    if is_books:
                        line.gstr2b = r
                    else:
                        line.books = r
                    self._add(line)

    def _pass_keys(self, via: str) -> None:
        if via == "exact":
            def key(r):
                return (r.supplier_gstin, r.doc_type.value, r.invoice_no_norm)
        else:
            def key(r):
                return (r.supplier_gstin, r.doc_type.value, r.invoice_no_loose)
        for b, g in self._key_pairs(self._free(self.books), self._free(self.g2b), key, key):
            self._add(self._pair_line(b, g, via))

    def _pass_amendments(self) -> None:
        def bkey(r):
            return (r.supplier_gstin, r.doc_type.value, r.invoice_no_norm)

        def gkey(r):
            if not (r.is_amendment and r.original_invoice_no):
                return None
            return (r.supplier_gstin, r.doc_type.value, normalize_invoice_no(r.original_invoice_no))

        for b, g in self._key_pairs(self._free(self.books), self._free(self.g2b), bkey, gkey):
            line = self._pair_line(b, g, "amendment")
            if line.category == Category.AMENDED:
                line.reasons.insert(0, (
                    f"Books carry the original number '{b.invoice_no}'; supplier amended it to "
                    f"'{g.invoice_no}' in GSTR-2B – update books reference if appropriate"))
            self._add(line)

    def _pass_prior(self) -> None:
        if not self.prior:
            return
        for loose in (False, True):
            if loose and not self.s.enable_loose_number_match:
                continue

            def key(r, loose=loose):
                return (r.supplier_gstin, r.doc_type.value, r.invoice_no_loose if loose else r.invoice_no_norm)

            for b, g in self._key_pairs(self._free(self.prior), self._free(self.g2b), key, key):
                line = self._pair_line(b, g, "prior")
                self._add(line)

    def _pass_gstin_mismatch(self) -> None:
        gidx = defaultdict(list)
        for g in self._free(self.g2b):
            gidx[(g.doc_type.value, g.invoice_no_norm)].append(g)
        edges = []
        for b in self._free(self.books):
            for g in gidx.get((b.doc_type.value, b.invoice_no_norm), []):
                if (g.supplier_gstin != b.supplier_gstin
                        and self._within(b.signed("taxable") - g.signed("taxable"))
                        and self._within(b.signed("itc") - g.signed("itc"))):
                    edges.append((b, g))
        for b, g in self._mutual_unique(edges):
            same_pan = pan_of(b.supplier_gstin) == pan_of(g.supplier_gstin)
            reason = (f"Same invoice number and value but supplier GSTIN differs: books {b.supplier_gstin} vs "
                      f"GSTR-2B {g.supplier_gstin}" + (" (same PAN – different registration of the supplier)"
                                                       if same_pan else " (different PAN)"))
            self._add(self._probable_pair(b, g, Flag.GSTIN_MISMATCH, reason, confidence=80 if same_pan else 70))

    def _pass_fuzzy(self) -> None:
        bgroups, ggroups = defaultdict(list), defaultdict(list)
        for b in self._free(self.books):
            bgroups[(b.supplier_gstin, b.doc_type.value)].append(b)
        for g in self._free(self.g2b):
            ggroups[(g.supplier_gstin, g.doc_type.value)].append(g)
        gap = self.s.fuzzy_min_gap
        for key in sorted(bgroups.keys() & ggroups.keys()):
            cands: dict[str, list] = defaultdict(list)  # uid -> [(conf, other)]
            scores = {}
            for b in bgroups[key]:
                for g in ggroups[key]:
                    conf, num, amt, dsc = self._similarity(b, g)
                    if num >= self.s.fuzzy_threshold or (num >= 60 and amt == 100 and dsc == 100):
                        cands[b.uid].append((conf, g))
                        cands[g.uid].append((conf, b))
                        scores[(b.uid, g.uid)] = (conf, num, amt, dsc)
            for lst in cands.values():
                lst.sort(key=lambda t: (-t[0], t[1].sort_key()))

            def clear_best(uid):
                lst = cands.get(uid)
                if not lst:
                    return None
                if len(lst) > 1 and lst[0][0] - lst[1][0] < gap:
                    return None
                return lst[0][1]

            for b in bgroups[key]:
                g = clear_best(b.uid)
                if g is not None and g.uid not in self.used and clear_best(g.uid) is b:
                    conf, num, amt, dsc = scores[(b.uid, g.uid)]
                    reason = (f"Probable match: invoice number similarity {num}%, amount agreement {amt}%, "
                              f"date agreement {dsc}% (books '{b.invoice_no}' vs GSTR-2B '{g.invoice_no}')")
                    self._add(self._probable_pair(b, g, Flag.FUZZY, reason, confidence=conf))
            for r in (*bgroups[key], *ggroups[key]):
                if r.uid in self.used or not cands.get(r.uid):
                    continue
                others = cands[r.uid]
                line = ReconLine(
                    line_no=0, category=Category.PROBABLE, match_level=5, confidence=others[0][0],
                    flags=[Flag.AMBIGUOUS.value, Flag.FUZZY.value],
                    reasons=["Several possible counterparts – no automatic suggestion: " + ", ".join(
                        f"'{o.invoice_no}' ({c}%)" for c, o in others)],
                    candidates=[o.uid for _, o in others],
                )
                if r.source == Source.BOOKS:
                    line.books = r
                else:
                    line.gstr2b = r
                    self._common_flags(r, line.flags, line.reasons)
                self._add(line)

    def _pass_missing(self) -> None:
        for b in self._free(self.books):
            self._add(ReconLine(
                line_no=0, category=Category.MISSING_IN_2B, books=b,
                reasons=["No matching document in GSTR-2B for the reconciliation period"],
            ))
        for g in self._free(self.g2b):
            line = ReconLine(
                line_no=0, category=Category.MISSING_IN_BOOKS, gstr2b=g,
                reasons=["Document appears in GSTR-2B but not in the purchase register"],
            )
            if self.period_start and g.invoice_date < self.period_start:
                line.flags.append(Flag.DATED_BEFORE_PERIOD.value)
                line.reasons.append(
                    f"Dated {_fmt(g.invoice_date)}, before the reconciliation period – may have been booked "
                    "in an earlier period (import those books to check)")
            self._common_flags(g, line.flags, line.reasons)
            self._add(line)

    # --------------------------------------------------------------------- run
    def run(self) -> list[ReconLine]:
        self._tick(5, "Detecting duplicate documents")
        self._duplicates()
        self._tick(20, "Matching on exact invoice reference")
        self._pass_keys("exact")
        if self.s.enable_loose_number_match:
            self._tick(35, "Matching invoice-number variations")
            self._pass_keys("loose")
        self._tick(45, "Matching amendments")
        self._pass_amendments()
        self._tick(55, "Searching previous-period books")
        self._pass_prior()
        if self.s.enable_gstin_mismatch_check:
            self._tick(65, "Checking GSTIN mismatches")
            self._pass_gstin_mismatch()
        if self.s.enable_fuzzy:
            self._tick(75, "Finding probable matches")
            self._pass_fuzzy()
        self._tick(90, "Classifying unmatched documents")
        self._pass_missing()
        self.lines.sort(key=lambda ln: (ln.primary.sort_key(), ln.gstr2b.uid if ln.gstr2b else ""))
        for i, line in enumerate(self.lines, start=1):
            line.line_no = i
            line.flags = [f.value if isinstance(f, Flag) else f for f in line.flags]
            if line.category != Category.FULLY_MATCHED and line.status == ExceptionStatus.NO_ACTION:
                line.status = ExceptionStatus.PENDING_REVIEW
        self._check_integrity()
        self._tick(100, "Reconciliation complete")
        return self.lines

    def _check_integrity(self) -> None:
        seen: dict[str, int] = defaultdict(int)
        for line in self.lines:
            for r in (line.books, line.gstr2b):
                if r is not None:
                    seen[r.uid] += 1
        for r in (*self.books, *self.g2b):
            if seen.get(r.uid) != 1:
                raise ReconciliationIntegrityError(f"record {r.reference} appears {seen.get(r.uid, 0)} times")
        for r in self.prior:
            if seen.get(r.uid, 0) > 1:
                raise ReconciliationIntegrityError(f"prior record {r.reference} used more than once")
        for side, records in (("books", self.books), ("gstr2b", self.g2b)):
            expected = sum((r.signed("itc") for r in records), ZERO)
            actual = sum((ln.side(side, "itc") for ln in self.lines
                          if (ln.books if side == "books" else ln.gstr2b) is not None
                          and not (side == "books" and ln.books.is_prior_period)), ZERO)
            if expected != actual:
                raise ReconciliationIntegrityError(f"{side} ITC does not reconcile: {expected} vs {actual}")


def fingerprint(books, gstr2b, prior, settings: ReconSettings, period_start: date | None) -> str:
    h = hashlib.sha256()
    h.update(json.dumps(settings.to_dict(), sort_keys=True).encode())
    h.update(str(period_start).encode())
    h.update(ENGINE_VERSION.encode())
    for tag, records in (("B", books), ("G", gstr2b), ("P", prior)):
        for r in sorted(records, key=lambda r: r.uid):
            h.update(f"{tag}|{r.uid}|{r.identity_hash()}|{r.period}\n".encode())
    return h.hexdigest()


def reconcile(
    books: Iterable[InvoiceRecord],
    gstr2b: Iterable[InvoiceRecord],
    settings: ReconSettings | None = None,
    prior_books: Iterable[InvoiceRecord] = (),
    period_start: date | None = None,
    progress: ProgressFn | None = None,
    cancel: CancelToken | None = None,
) -> ReconResult:
    settings = settings or ReconSettings()
    books, gstr2b, prior_books = list(books), list(gstr2b), list(prior_books)
    for r in books:
        if r.source != Source.BOOKS:
            raise ValueError(f"{r.uid} is not a books record")
    for r in gstr2b:
        if r.source == Source.BOOKS:
            raise ValueError(f"{r.uid} is a books record passed as GSTR-2B")
    engine = _Engine(books, gstr2b, prior_books, settings, period_start, progress, cancel)
    lines = engine.run()
    return ReconResult(
        lines=lines, settings=settings, books=engine.books, gstr2b=engine.g2b,
        prior_books_considered=len(prior_books), period_start=period_start,
        fingerprint=fingerprint(books, gstr2b, prior_books, settings, period_start),
    )
