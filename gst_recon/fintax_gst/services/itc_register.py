"""ITC classification & manual mapping: the register of inward supplies of a financial year built from the purchase
register and the input tax ledgers of TallyPrime, classified in three independent dimensions (nature, GST treatment,
ITC status), and the annual workings drawn from it (GSTR-9 Tables 6–8, GSTR-9C Tables 12–14, RCM) with the ten
reconciliation controls.

* Source data is never changed: tax-ledger lines are stored as read; a transaction holds a snapshot of its sources.
* The CGST and SGST postings of one voucher are one transaction – the postings are consolidated by voucher (date,
  type, number) and matched to the purchase-register document, never counted twice.
* A manual classification wins over every rule or suggestion; every change is audited with the reason and can be
  undone. A split must add up exactly – taxable value and each tax head – to the transaction.
* Differences are shown, never adjusted; the year is marked final only after the controls pass or the user records
  why it is final despite them.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete, select

from ..core.money import ZERO
from ..db.database import Database
from ..db.models import (
    AppSetting, AuditLog, Client, Invoice, ItcClaim, ItcMapRule, ItcPart, ItcTxn, LedgerMapping, SourceFile,
    TaxPosting,
)
from ..importers.pipeline import sha256_of
from ..importers.tax_ledger import read_tax_ledgers
from ..itc.annual import fy_months
from ..ledgers.itc_classes import (
    AVAILED, CLAIMS, ELIGIBLE, GOODS, NATURES, RCM, REVERSED, SCOPES, STATUSES, TREATMENTS, ledger_of, propose,
)
from .common import ServiceError, audit, dumps

HEADS = ("igst", "cgst", "sgst", "cess")
HALF = Decimal("0.50")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _fy_of(d: date | None) -> str:
    if d is None:
        return ""
    y = d.year if d.month >= 4 else d.year - 1
    return f"{y}-{str(y + 1)[-2:]}"


@dataclass
class PartIn:
    igst: Decimal = ZERO
    cgst: Decimal = ZERO
    sgst: Decimal = ZERO
    cess: Decimal = ZERO
    taxable: Decimal | None = None
    nature: str = "unclassified"
    treatment: str = "fcm"
    status: str = "pending"  # ITC eligibility
    claim: str = "unknown"  # what was done in GSTR-3B
    claim_period: str = ""


@dataclass
class TxnView:
    txn: ItcTxn
    parts: list[ItcPart]

    @property
    def tax(self) -> Decimal:
        t = self.txn
        return t.igst + t.cgst + t.sgst + t.cess

    def label(self, dim: str) -> str:
        names = {"nature": NATURES, "treatment": TREATMENTS, "status": STATUSES, "claim": CLAIMS, "confidence": {
            "high": "High", "medium": "Medium", "low": "Low", "manual": "Manual review"}, "basis": {
            "auto": "Suggested", "rule": "Rule", "manual": "Manual"}}[dim]
        vals = {getattr(p, dim) for p in self.parts}
        if not vals:
            return ""
        if len(vals) > 1:
            return f"Split ({len(self.parts)})"
        return names.get(next(iter(vals)), next(iter(vals)))

    @property
    def is_adjustment(self) -> bool:
        return self.txn.match == "adjust"


@dataclass
class Control:
    code: str
    title: str
    status: str  # pass / warn / fail
    detail: str
    critical: bool = False


@dataclass
class Bucket:
    label: str
    taxable: Decimal = ZERO
    igst: Decimal = ZERO
    cgst: Decimal = ZERO
    sgst: Decimal = ZERO
    cess: Decimal = ZERO
    count: int = 0

    @property
    def tax(self) -> Decimal:
        return self.igst + self.cgst + self.sgst + self.cess

    def add(self, p, sign: int = 1) -> None:
        self.taxable += (p.taxable or ZERO) * sign
        for h in HEADS:
            setattr(self, h, getattr(self, h) + getattr(p, h) * sign)
        self.count += 1

    def heads(self) -> dict[str, Decimal]:
        return {h: getattr(self, h) for h in HEADS}


@dataclass
class ItcWorking:
    client: str
    gstin: str
    fy: str
    views: list[TxnView]
    by_nature: dict[str, Bucket]
    by_treatment: dict[str, Bucket]
    by_status: dict[str, Bucket]
    table6: dict[str, dict[str, Bucket]]  # row -> inputs/services/capital -> bucket (availed)
    table6_3b: dict[str, dict[str, Decimal] | None]  # row -> GSTR-3B figure by head
    table7: dict[str, Bucket]
    table8: object | None
    table12: list[tuple[str, str, Decimal | None, str]]
    table13: list[tuple[str, Decimal, str]]
    table14: list[tuple[str, str, Decimal, Decimal, Decimal, Decimal]]  # row, label, value, tax, eligible, claimed
    rcm: dict[str, Bucket]
    controls: list[Control]
    postings_total: dict[str, Decimal]
    ledger_balances: dict[str, Decimal]
    final: dict | None = None
    notes: list[str] = field(default_factory=list)
    by_claim: dict[str, Bucket] = field(default_factory=dict)
    inelig_claimed: Decimal = ZERO
    table14_status: str = ""

    @property
    def txns(self) -> list[TxnView]:
        return [v for v in self.views if not v.is_adjustment]

    def count(self, pred) -> int:
        return sum(1 for v in self.txns if pred(v))

    @property
    def unclassified(self) -> int:
        return self.count(lambda v: any(p.nature == "unclassified" for p in v.parts))

    @property
    def to_review(self) -> int:
        return self.count(lambda v: any(p.basis == "auto" and p.confidence in ("low", "manual") for p in v.parts))

    def total(self, dim: str, keys) -> Bucket:
        b = Bucket(",".join(keys))
        src = {"nature": self.by_nature, "treatment": self.by_treatment, "status": self.by_status,
               "claim": self.by_claim}[dim]
        for k in keys:
            x = src.get(k)
            if x:
                b.taxable += x.taxable
                for h in HEADS:
                    setattr(b, h, getattr(b, h) + getattr(x, h))
                b.count += x.count
        return b

    @property
    def can_finalise(self) -> tuple[bool, list[str]]:
        bad = [f"{c.code} {c.title}: {c.detail}" for c in self.controls if c.status == "fail" and c.critical]
        return not bad, bad


T6_ROWS = {"6B": "6B Inward supplies other than imports and RCM", "6C": "6C RCM – unregistered persons",
           "6D": "6D RCM – registered persons", "6E": "6E Import of goods (incl. SEZ)", "6F": "6F Import of services",
           "6G": "6G Input Service Distributor", "6H": "6H ITC reclaimed (rule 37 / others)"}
T6_3B = {"6B": ("4A5",), "6C": ("4A3",), "6D": ("4A3",), "6E": ("4A1",), "6F": ("4A2",), "6G": ("4A4",),
         "6H": ("4D1",)}
TREAT_ROW = {"fcm": "6B", "rcm_unreg": "6C", "rcm_reg": "6D", "import_g": "6E", "sez": "6E", "import_s": "6F",
             "isd": "6G", "deemed_exp": "6B", "other": "6B"}


def _type(nature: str) -> str:
    return "inputs" if nature in GOODS else nature


class ItcRegisterService:
    def __init__(self, db: Database):
        self.db = db

    # ---------------------------------------------------------- tax ledgers
    def import_tax_ledgers(self, client_id: int, fy: str, path: str | Path, user: str | None = None):
        path = Path(path)
        tl = read_tax_ledgers(path)
        digest = sha256_of(path)
        with self.db.session() as s:
            if s.get(Client, client_id) is None:
                raise ServiceError(f"Client {client_id} not found")
            dup = s.scalar(select(SourceFile.id).where(SourceFile.client_id == client_id, SourceFile.sha256 == digest,
                                                       SourceFile.source_type == "TAXLEDGER"))
            if dup:
                raise ServiceError(f"{path.name} was already imported (import #{dup})")
            have = {(p.ledger.lower(), p.kind, p.entry_date, p.voucher_type, p.voucher_no, p.particulars, p.amount)
                    for p in s.scalars(select(TaxPosting).where(TaxPosting.client_id == client_id,
                                                                TaxPosting.financial_year == fy))}
            new = [p for p in tl.postings if (p.ledger.lower(), p.kind, p.entry_date, p.voucher_type, p.voucher_no,
                                               p.particulars, p.amount) not in have]
            sf = SourceFile(client_id=client_id, source_type="TAXLEDGER", file_name=path.name,
                            file_path=str(path.resolve()), sha256=digest, layout="tax_ledger", period=None,
                            rows_read=len(tl.postings), documents_imported=len(new),
                            documents_skipped_existing=len(tl.postings) - len(new),
                            warnings_json=dumps(tl.warnings), imported_by=user or "",
                            mapping_json=dumps({"financial_year": fy}))
            s.add(sf)
            s.flush()
            for p in new:
                s.add(TaxPosting(client_id=client_id, financial_year=fy, source_file_id=sf.id, ledger=p.ledger[:200],
                                 head=p.head, kind=p.kind, entry_date=p.entry_date, voucher_type=p.voucher_type[:60],
                                 voucher_no=p.voucher_no[:100], particulars=p.particulars[:300], amount=p.amount,
                                 row_ref=p.row[:80]))
            audit(s, "IMPORT", "tax_ledger", sf.id, {"file": path.name, "fy": fy, "lines": len(new),
                                                      "repeated": len(tl.postings) - len(new),
                                                      "ledgers": tl.ledgers, "warnings": tl.warnings}, user, client_id)
            s.expunge(sf)
        return sf, tl, len(tl.postings) - len(new)

    # ------------------------------------------------------------- build
    def build(self, client_id: int, fy: str, user: str = "") -> dict:
        """(Re)build the register: purchase-register documents of the year, tax-ledger postings consolidated by
        voucher and matched to them; classification proposed for every transaction not classified by hand."""
        months = fy_months(fy)
        stats = {"documents": 0, "vouchers": 0, "matched": 0, "differs": 0, "tax_ledger_only": 0, "adjustments": 0,
                 "removed": 0}
        with self.db.session() as s:
            if s.get(Client, client_id) is None:
                raise ServiceError(f"Client {client_id} not found")
            invoices = list(s.scalars(select(Invoice).where(Invoice.client_id == client_id,
                                                            Invoice.source_type == "BOOKS", Invoice.period.in_(months))))
            postings = list(s.scalars(select(TaxPosting).where(TaxPosting.client_id == client_id,
                                                               TaxPosting.financial_year == fy,
                                                               TaxPosting.kind == "txn")))
            txns = list(s.scalars(select(ItcTxn).where(ItcTxn.client_id == client_id, ItcTxn.financial_year == fy)))
            by_inv = {t.invoice_id: t for t in txns if t.invoice_id is not None}
            by_key = {t.voucher_key: t for t in txns if t.invoice_id is None and t.voucher_key}
            keep: set[int] = set()
            # purchase-register documents
            for inv in invoices:
                k = -1 if inv.doc_type == "CRN" else 1
                hsn = ",".join(sorted({h.get("hsn", "") for h in json.loads(inv.hsn_json or "[]") if h.get("hsn")}))
                t = by_inv.get(inv.id)
                if t is None:
                    t = ItcTxn(client_id=client_id, financial_year=fy, invoice_id=inv.id)
                    s.add(t)
                t.voucher_date, t.period, t.party, t.gstin = inv.invoice_date, inv.period, inv.supplier_name, \
                    inv.supplier_gstin or ""
                t.invoice_no, t.invoice_date, t.doc_type = inv.invoice_no, inv.invoice_date, inv.doc_type
                t.description = inv.description or ""
                t.ledger = (ledger_of(inv.description) or "")[:300]
                t.hsn, t.reverse_charge = hsn[:60], bool(inv.reverse_charge)
                t.taxable = k * inv.taxable
                t.igst, t.cgst, t.sgst, t.cess = k * inv.igst, k * inv.cgst, k * inv.sgst, k * inv.cess
                t.source_ref = f"purchase register {inv.source_rows}"[:300]
                t.match, t.ledger_tax_json, t.voucher_key, t.posting_ids = "register", "", "", "[]"
                s.flush()
                keep.add(t.id)
                stats["documents"] += 1
            # tax-ledger postings consolidated by voucher
            groups: dict[tuple, list[TaxPosting]] = defaultdict(list)
            for p in postings:
                groups[(p.entry_date, p.voucher_type.strip().lower(), p.voucher_no.strip())].append(p)
            doc_txns = [t for t in s.scalars(select(ItcTxn).where(ItcTxn.client_id == client_id,
                                                                  ItcTxn.financial_year == fy,
                                                                  ItcTxn.invoice_id.is_not(None))) if t.id in keep]
            free = {t.id: t for t in doc_txns}
            for (d, vtype, vno), ps in sorted(groups.items(), key=lambda kv: (kv[0][0] or date.min, kv[0][2])):
                stats["vouchers"] += 1
                tax = {h: sum((p.amount for p in ps if p.head == h), ZERO) for h in HEADS}
                total = sum(tax.values(), ZERO)
                party = next((p.particulars for p in ps if p.particulars), "")
                period = f"{d:%Y-%m}" if d else ""
                cand = None
                if vno:
                    cand = next((t for t in free.values() if t.period == period and _norm(t.invoice_no) == _norm(vno)),
                                None)
                if cand is None and party:
                    np = _norm(party)
                    cand = next((t for t in free.values() if t.period == period and np and _norm(t.party) and (
                        np in _norm(t.party) or _norm(t.party) in np) and abs((t.igst + t.cgst + t.sgst + t.cess) - total)
                                 <= Decimal("1")), None)
                ids = json.dumps(sorted(p.id for p in ps))
                if cand is not None:
                    del free[cand.id]
                    cand.ledger_tax_json = json.dumps({h: str(v) for h, v in tax.items()})
                    cand.voucher_key, cand.posting_ids = f"{d}|{vtype}|{vno}", ids
                    cand.voucher_type, cand.voucher_no = ps[0].voucher_type[:60], vno[:100]
                    same = all(abs(getattr(cand, h) - tax[h]) <= HALF for h in HEADS)
                    cand.match = "both" if same else "differs"
                    stats["matched" if same else "differs"] += 1
                    continue
                key = f"{d}|{vtype}|{vno}|{party}"[:200]
                t = by_key.get(key)
                is_adj = total < 0 and not re.search(r"debit note|purchase|credit note", vtype)
                if t is None:
                    t = ItcTxn(client_id=client_id, financial_year=fy, voucher_key=key)
                    s.add(t)
                t.voucher_date, t.period, t.voucher_type, t.voucher_no = d, period, ps[0].voucher_type[:60], vno[:100]
                t.party, t.ledger, t.taxable = party[:200], party[:300], None
                t.description = "; ".join(sorted({p.ledger for p in ps}))[:500]
                t.doc_type = "CRN" if total < 0 else "INV"
                t.reverse_charge = bool(re.search(r"\brcm\b|reverse", " ".join(p.particulars for p in ps), re.I))
                for h in HEADS:
                    setattr(t, h, tax[h])
                t.ledger_tax_json = json.dumps({h: str(v) for h, v in tax.items()})
                t.posting_ids, t.match = ids, "adjust" if is_adj else "taxledger"
                t.source_ref = ("tax ledger " + ", ".join(sorted({p.row_ref for p in ps})))[:300]
                s.flush()
                keep.add(t.id)
                stats["adjustments" if is_adj else "tax_ledger_only"] += 1
            for t in txns:
                if t.id not in keep:
                    parts = list(s.scalars(select(ItcPart).where(ItcPart.txn_id == t.id)))
                    audit(s, "ITC_TXN_REMOVED", "itc_txn", t.id, {"party": t.party, "invoice_no": t.invoice_no,
                                                                 "parts": [self._pdict(p) for p in parts]},
                          user, client_id)
                    for p in parts:
                        s.delete(p)
                    s.delete(t)
                    stats["removed"] += 1
            audit(s, "ITC_REGISTER_BUILD", "itc_register", fy, stats, user, client_id)
        self.classify_auto(client_id, fy)
        return stats

    # ------------------------------------------------------- classification
    @staticmethod
    def _pdict(p: ItcPart) -> dict:
        return {"taxable": None if p.taxable is None else str(p.taxable), **{h: str(getattr(p, h)) for h in HEADS},
                "nature": p.nature, "treatment": p.treatment, "status": p.status, "claim": p.claim,
                "claim_period": p.claim_period, "basis": p.basis,
                "confidence": p.confidence, "reason": p.reason}

    def _rules(self, s, client_id: int, fy: str) -> list[ItcMapRule]:
        return [r for r in s.scalars(select(ItcMapRule).where(ItcMapRule.client_id == client_id,
                                                              ItcMapRule.active.is_(True)))
                if not r.financial_year or r.financial_year == fy]

    def classify_auto(self, client_id: int, fy: str, txn_ids: list[int] | None = None) -> int:
        """Propose nature, treatment and eligibility for every transaction not classified by hand (suggestions and
        rule results are replaced; manual parts never). The ITC claim is a separate fact: it comes from the ITC
        claim register (GSTR-3B actions) or the user, never from the classification."""
        n = 0
        with self.db.session() as s:
            rules = self._rules(s, client_id, fy)
            maps = self._maps(s, client_id)
            claimed = self._claims(s, client_id)
            q = select(ItcTxn).where(ItcTxn.client_id == client_id, ItcTxn.financial_year == fy,
                                     ItcTxn.match != "adjust")
            if txn_ids is not None:
                q = q.where(ItcTxn.id.in_(txn_ids))
            for t in s.scalars(q):
                parts = list(s.scalars(select(ItcPart).where(ItcPart.txn_id == t.id)))
                reg = claimed.get(t.invoice_id) if t.invoice_id else None
                if any(p.basis == "manual" for p in parts):
                    if len(parts) == 1:
                        self._sync_single(parts[0], t)
                    for p in parts:
                        if reg and p.claim == "unknown":
                            p.claim, p.claim_period = reg
                    continue
                pr = propose(t, rules, maps)
                claim, period = "unknown", ""
                if len(parts) == 1 and parts[0].claim != "unknown":
                    claim, period = parts[0].claim, parts[0].claim_period  # a claim recorded earlier stays
                if reg and claim == "unknown":
                    claim, period = reg
                for p in parts:
                    s.delete(p)
                s.add(ItcPart(client_id=client_id, txn_id=t.id, taxable=t.taxable, igst=t.igst, cgst=t.cgst,
                              sgst=t.sgst, cess=t.cess, nature=pr.nature, treatment=pr.treatment, status=pr.status,
                              claim=claim, claim_period=period, basis=pr.basis, confidence=pr.confidence,
                              rule_id=pr.rule_id, reason=pr.reason))
                n += 1
        return n

    @staticmethod
    def _maps(s, client_id: int) -> dict[str, dict]:
        """The client's Ledger Mapping Master (active entries)."""
        return {m.ledger_key: {"acct_class": m.acct_class, "gst_class": m.gst_class, "gst_source": m.gst_source,
                               "eligibility": m.eligibility}
                for m in s.scalars(select(LedgerMapping).where(LedgerMapping.client_id == client_id,
                                                               LedgerMapping.active.is_(True)))}

    @staticmethod
    def _sync_single(p: ItcPart, t: ItcTxn) -> None:
        """A transaction classified whole keeps the source's amounts when the source changes."""
        p.taxable = t.taxable
        for h in HEADS:
            setattr(p, h, getattr(t, h))

    @staticmethod
    def _claims(s, client_id: int) -> dict[int, tuple[str, str]]:
        """Claim state and GSTR-3B period of each purchase-register document from the ITC claim register."""
        acts: dict[int, list[ItcClaim]] = defaultdict(list)
        for c in s.scalars(select(ItcClaim).where(ItcClaim.client_id == client_id).order_by(ItcClaim.period,
                                                                                             ItcClaim.id)):
            acts[c.invoice_id].append(c)
        res = {}
        for inv, rows in acts.items():
            tot = defaultdict(Decimal)
            for c in rows:
                tot[c.action] += c.igst + c.cgst + c.sgst + c.cess
            first = next((c.period for c in rows if c.action == "CLAIM"), "")
            if tot.get("RECLAIM"):
                res[inv] = ("reclaimed", next(c.period for c in rows if c.action == "RECLAIM"))
            elif tot.get("REVERSE"):
                res[inv] = ("reversed", first)
            elif tot.get("CLAIM"):
                res[inv] = ("claimed", first)
        return res

    def set_claim(self, txn_ids: list[int], claim: str, user: str, period: str = "", reason: str = "") -> int:
        """Record what was done with the ITC in GSTR-3B (claimed in which period, not claimed, reversed …). This
        does not change the nature, treatment or eligibility."""
        from ..importers.parsing import parse_period

        if claim not in CLAIMS:
            raise ServiceError(f"Unknown claim state {claim}")
        if claim in ("claimed", "reversed", "temp_reversed", "reclaimed"):
            period = parse_period(period) or ""
            if not period:
                raise ServiceError("Give the GSTR-3B period (YYYY-MM) in which the ITC was claimed / reclaimed")
        n = 0
        with self.db.session() as s:
            for t in s.scalars(select(ItcTxn).where(ItcTxn.id.in_(txn_ids))):
                parts = list(s.scalars(select(ItcPart).where(ItcPart.txn_id == t.id)))
                before = [self._pdict(p) for p in parts]
                for p in parts:
                    p.claim, p.claim_period, p.updated_by = claim, period if claim != "not_claimed" else "", user[:80]
                audit(s, "ITC_CLAIM", "itc_txn", t.id, {"before": before, "after": [self._pdict(p) for p in parts],
                                                        "reason": reason, "party": t.party,
                                                        "invoice_no": t.invoice_no}, user, t.client_id)
                n += 1
        return n

    def set_class(self, txn_ids: list[int], user: str, reason: str = "", nature: str | None = None,
                  treatment: str | None = None, status: str | None = None) -> int:
        """Manual classification of transactions (any of the three dimensions). Overrides rules and suggestions."""
        self._check(nature, treatment, status)
        n = 0
        with self.db.session() as s:
            for t in s.scalars(select(ItcTxn).where(ItcTxn.id.in_(txn_ids))):
                parts = list(s.scalars(select(ItcPart).where(ItcPart.txn_id == t.id)))
                if not parts:
                    parts = [ItcPart(client_id=t.client_id, txn_id=t.id, taxable=t.taxable,
                                     **{h: getattr(t, h) for h in HEADS})]
                    s.add(parts[0])
                before = [self._pdict(p) for p in parts]
                for p in parts:
                    if nature:
                        p.nature = nature
                    if treatment:
                        p.treatment = treatment
                    if status:
                        p.status = status
                    p.basis, p.confidence, p.updated_by = "manual", "high", user[:80]
                    p.reason = (reason or "classified by hand")[:400]
                s.flush()
                audit(s, "ITC_CLASSIFY", "itc_txn", t.id, {"before": before, "after": [self._pdict(p) for p in parts],
                                                           "reason": reason, "party": t.party,
                                                           "invoice_no": t.invoice_no}, user, t.client_id)
                n += 1
        return n

    @staticmethod
    def _check(nature, treatment, status) -> None:
        if nature and nature not in NATURES:
            raise ServiceError(f"Unknown nature {nature}")
        if treatment and treatment not in TREATMENTS:
            raise ServiceError(f"Unknown GST treatment {treatment}")
        if status and status not in STATUSES:
            raise ServiceError(f"Unknown ITC status {status}")

    def split(self, txn_id: int, parts: list[PartIn], user: str, reason: str = "") -> TxnView:
        """Split a transaction; the parts must add up exactly to its taxable value and to each tax head."""
        if not parts:
            raise ServiceError("Give at least one part")
        for p in parts:
            self._check(p.nature, p.treatment, p.status)
        with self.db.session() as s:
            t = s.get(ItcTxn, txn_id)
            if t is None:
                raise ServiceError(f"Transaction #{txn_id} not found")
            for h in HEADS:
                tot = sum((getattr(p, h) for p in parts), ZERO)
                if tot != getattr(t, h):
                    raise ServiceError(f"The parts' {h.upper()} add up to ₹{tot:,.2f}, the invoice has "
                                       f"₹{getattr(t, h):,.2f} – they must be equal")
            if t.taxable is not None:
                tot = sum((p.taxable or ZERO for p in parts), ZERO)
                if tot != t.taxable:
                    raise ServiceError(f"The parts' taxable value adds up to ₹{tot:,.2f}, the invoice has "
                                       f"₹{t.taxable:,.2f} – they must be equal")
            old = list(s.scalars(select(ItcPart).where(ItcPart.txn_id == txn_id)))
            before = [self._pdict(p) for p in old]
            for p in old:
                s.delete(p)
            s.flush()
            new = []
            for p in parts:
                x = ItcPart(client_id=t.client_id, txn_id=txn_id, taxable=p.taxable if t.taxable is not None else None,
                            igst=p.igst, cgst=p.cgst, sgst=p.sgst, cess=p.cess, nature=p.nature,
                            treatment=p.treatment, status=p.status, claim=p.claim, claim_period=p.claim_period,
                            basis="manual", confidence="high",
                            reason=(reason or "split by hand")[:400], updated_by=user[:80])
                s.add(x)
                new.append(x)
            s.flush()
            audit(s, "ITC_SPLIT", "itc_txn", txn_id, {"before": before, "after": [self._pdict(p) for p in new],
                                                      "reason": reason, "party": t.party,
                                                      "invoice_no": t.invoice_no}, user, t.client_id)
        return self.view(txn_id)

    @staticmethod
    def proportional(t: ItcTxn, taxables: list[Decimal]) -> list[PartIn]:
        """Parts with the invoice's tax divided in the ratio of their taxable values – for an invoice at one GST
        rate, where that is the actual tax of each part. The last part takes the rounding."""
        total = sum(taxables, ZERO)
        if t.taxable is None or total != t.taxable:
            raise ServiceError(f"The taxable values must add up to the invoice's ₹{(t.taxable or ZERO):,.2f}")
        out, given = [], {h: ZERO for h in HEADS}
        for i, tx in enumerate(taxables):
            p = PartIn(taxable=tx)
            for h in HEADS:
                v = getattr(t, h) - given[h] if i == len(taxables) - 1 else \
                    (getattr(t, h) * tx / total).quantize(Decimal("0.01")) if total else ZERO
                setattr(p, h, v)
                given[h] += v
            out.append(p)
        return out

    def undo(self, txn_id: int, user: str) -> bool:
        """Put back the classification as it was before the last manual change or split."""
        with self.db.session() as s:
            t = s.get(ItcTxn, txn_id)
            if t is None:
                return False
            last = s.scalar(select(AuditLog).where(AuditLog.entity == "itc_txn", AuditLog.entity_id == str(txn_id),
                                                   AuditLog.action.in_(["ITC_CLASSIFY", "ITC_SPLIT", "ITC_CLAIM"]))
                            .order_by(AuditLog.id.desc()).limit(1))
            if last is None:
                return False
            before = json.loads(last.details_json).get("before") or []
            current = list(s.scalars(select(ItcPart).where(ItcPart.txn_id == txn_id)))
            now = [self._pdict(p) for p in current]
            for p in current:
                s.delete(p)
            s.flush()
            for b in before:
                s.add(ItcPart(client_id=t.client_id, txn_id=txn_id, taxable=None if b["taxable"] is None else
                              Decimal(b["taxable"]), **{h: Decimal(b[h]) for h in HEADS}, nature=b["nature"],
                              treatment=b["treatment"], status=b["status"], claim=b.get("claim", "unknown"),
                              claim_period=b.get("claim_period", ""), basis=b["basis"],
                              confidence=b["confidence"], reason=b["reason"], updated_by=user[:80]))
            audit(s, "ITC_UNDO", "itc_txn", txn_id, {"undone": last.id, "before": now, "after": before}, user,
                  t.client_id)
            # mark the undone entry so a second undo goes one step further back
            last.action = "ITC_UNDONE"
        if not before:
            self.classify_auto(t.client_id, t.financial_year, [txn_id])
        return True

    def history(self, txn_id: int) -> list[AuditLog]:
        with self.db.session() as s:
            return list(s.scalars(select(AuditLog).where(AuditLog.entity == "itc_txn",
                                                         AuditLog.entity_id == str(txn_id)).order_by(AuditLog.id)))

    def mark_reviewed(self, txn_ids: list[int], user: str, reviewed: bool = True) -> int:
        with self.db.session() as s:
            rows = list(s.scalars(select(ItcTxn).where(ItcTxn.id.in_(txn_ids))))
            for t in rows:
                t.reviewed = reviewed
            audit(s, "ITC_REVIEWED", "itc_register", ",".join(map(str, txn_ids))[:200], {"reviewed": reviewed},
                  user, rows[0].client_id if rows else None)
        return len(rows)

    # ------------------------------------------------------------- rules
    def add_rule(self, client_id: int, scope: str, value: str, user: str, value2: str = "", nature: str = "",
                 treatment: str = "", status: str = "", fy: str = "", note: str = "", apply: bool = True) -> ItcMapRule:
        if scope not in SCOPES:
            raise ServiceError(f"Unknown rule scope {scope}")
        if not value.strip():
            raise ServiceError("Give the value the rule matches")
        if not (nature or treatment or status):
            raise ServiceError("Say what the rule sets (nature, GST treatment or ITC status)")
        self._check(nature, treatment, status)
        with self.db.session() as s:
            r = ItcMapRule(client_id=client_id, scope=scope, value=value.strip()[:300], value2=value2.strip()[:300],
                           nature=nature, treatment=treatment, status=status, financial_year=fy, note=note[:300],
                           created_by=user[:80])
            s.add(r)
            s.flush()
            audit(s, "ITC_RULE_ADD", "itc_map_rule", r.id, {"scope": scope, "value": value, "value2": value2,
                                                             "nature": nature, "treatment": treatment,
                                                             "status": status, "fy": fy}, user, client_id)
            s.expunge(r)
        if scope == "ledger" and nature and not fy:
            self._to_master(client_id, value, nature, treatment, status, user)
        if apply:
            for y in ([fy] if fy else self.years(client_id)):
                self.classify_auto(client_id, y)
        return r

    def _to_master(self, client_id: int, ledger: str, nature: str, treatment: str, status: str, user: str) -> None:
        """A ledger rule for every year also goes to the client's Ledger Mapping Master (reused by both screens)."""
        from .mapping_master import MappingMasterService

        acct, gst = {"trading": ("Trading goods", "inputs"), "raw": ("Raw materials", "inputs"),
                     "other_goods": ("Other purchases", "inputs"), "services": ("Indirect expenses – other", "services"),
                     "capital": ("Other fixed assets", "capital"), "nongst": ("Non-GST expenses", "nogst"),
                     "unclassified": (None, None)}[nature]
        if acct is None:
            return
        source = {"fcm": "regular", "rcm_reg": "rcm_reg", "rcm_unreg": "rcm_unreg", "import_g": "import_g",
                  "sez": "import_g", "import_s": "import_s", "isd": "isd"}.get(treatment, "regular")
        elig = {"eligible": "eligible", "partial": "eligible", "blocked": "blocked", "reversal_req": "rule42"}.get(
            status, "")
        from ..ledgers.classify import ledger_key
        from ..ledgers.itc_classes import nature_from_bifurcation

        with self.db.session() as s:
            old = s.scalar(select(LedgerMapping).where(LedgerMapping.client_id == client_id,
                                                       LedgerMapping.ledger_key == ledger_key(ledger)))
            if old is not None and nature_from_bifurcation(old.acct_class, old.gst_class) == nature:
                acct = old.acct_class  # keep the more precise accounting class already in the master
            if old is not None and not old.active:
                return
        MappingMasterService(self.db).save(client_id, ledger, acct, gst, user, source, "", elig,
                                           "from a ledger rule in ITC classification", source="approved")

    def rules(self, client_id: int) -> list[ItcMapRule]:
        with self.db.session() as s:
            return list(s.scalars(select(ItcMapRule).where(ItcMapRule.client_id == client_id).order_by(ItcMapRule.id)))

    def delete_rule(self, rule_id: int, user: str) -> None:
        with self.db.session() as s:
            r = s.get(ItcMapRule, rule_id)
            if r is None:
                raise ServiceError(f"Rule #{rule_id} not found")
            r.active = False
            audit(s, "ITC_RULE_OFF", "itc_map_rule", rule_id, {"scope": r.scope, "value": r.value}, user, r.client_id)
            cid = r.client_id
        for y in self.years(cid):
            self.classify_auto(cid, y)

    def years(self, client_id: int) -> list[str]:
        with self.db.session() as s:
            return sorted(set(s.scalars(select(ItcTxn.financial_year).where(ItcTxn.client_id == client_id))))

    # ------------------------------------------------------------- reads
    def views(self, client_id: int, fy: str) -> list[TxnView]:
        return self.db.cached(("itc_reg", client_id, fy), lambda: self._views(client_id, fy))

    def _views(self, client_id: int, fy: str) -> list[TxnView]:
        with self.db.session() as s:
            txns = list(s.scalars(select(ItcTxn).where(ItcTxn.client_id == client_id, ItcTxn.financial_year == fy)
                                  .order_by(ItcTxn.voucher_date, ItcTxn.id)))
            parts: dict[int, list[ItcPart]] = defaultdict(list)
            for p in s.scalars(select(ItcPart).where(ItcPart.client_id == client_id).order_by(ItcPart.id)):
                parts[p.txn_id].append(p)
            s.expunge_all()
        return [TxnView(t, parts.get(t.id, [])) for t in txns]

    def view(self, txn_id: int) -> TxnView:
        with self.db.session() as s:
            t = s.get(ItcTxn, txn_id)
            if t is None:
                raise ServiceError(f"Transaction #{txn_id} not found")
            ps = list(s.scalars(select(ItcPart).where(ItcPart.txn_id == txn_id).order_by(ItcPart.id)))
            s.expunge_all()
        return TxnView(t, ps)

    # ----------------------------------------------------------- workings
    def working(self, client_id: int, fy: str) -> ItcWorking:
        return self.db.cached(("itc_working", client_id, fy), lambda: self._working(client_id, fy))

    def _working(self, client_id: int, fy: str) -> ItcWorking:
        from .gstr3b import Gstr3bService
        from .itc import ItcService

        months = fy_months(fy)
        with self.db.session() as s:
            c = s.get(Client, client_id)
            if c is None:
                raise ServiceError(f"Client {client_id} not found")
            name, gstin = c.name, c.gstin
            posts = list(s.scalars(select(TaxPosting).where(TaxPosting.client_id == client_id,
                                                            TaxPosting.financial_year == fy)))
            claims = list(s.scalars(select(ItcClaim).where(ItcClaim.client_id == client_id)))
            inv_dates = dict(s.execute(select(Invoice.id, Invoice.invoice_date).where(
                Invoice.id.in_([x.invoice_id for x in claims] or [-1]))).all())
            fin = s.get(AppSetting, f"itc_final:{client_id}:{fy}")
            final = json.loads(fin.value_json) if fin else None
        views = self.views(client_id, fy)
        by_n = {k: Bucket(v) for k, v in NATURES.items()}
        by_t = {k: Bucket(v) for k, v in TREATMENTS.items()}
        by_s = {k: Bucket(v) for k, v in STATUSES.items()}
        by_c = {k: Bucket(v) for k, v in CLAIMS.items()}
        t6 = {r: {k: Bucket(k) for k in ("inputs", "services", "capital")} for r in T6_ROWS}
        t7 = {"reversed": Bucket("Claimed, then reversed"), "temp_reversed": Bucket("Claimed, temporarily reversed")}
        rcm = {k: Bucket(v) for k, v in (("goods", "RCM on input goods"), ("services", "RCM on input services"),
                                         ("capital", "RCM on capital goods"), ("rcm_reg", "RCM – registered suppliers"),
                                         ("rcm_unreg", "RCM – unregistered suppliers"),
                                         ("import_s", "Import of services"))}
        t14: dict[str, list] = {}
        from ..gstr9.expenses import TABLE14, row_for

        labels14 = dict(TABLE14)
        later = ZERO  # ITC of this year's invoices claimed after the year / not yet claimed (12C, 8C)
        earlier = ZERO  # earlier years' invoices claimed in this year (12B)
        start = date(int(fy[:4]), 4, 1)
        for v in views:
            if v.is_adjustment:
                continue
            for p in v.parts:
                by_n[p.nature].add(p)
                by_t.setdefault(p.treatment or "other", Bucket(p.treatment)).add(p)
                by_s[p.status].add(p)
                by_c.setdefault(p.claim or "unknown", Bucket(p.claim)).add(p)
                typ = _type(p.nature)
                tax = p.igst + p.cgst + p.sgst + p.cess
                in_year = p.claim_period in months
                # GSTR-9 Table 6: only ITC actually availed in this year's GSTR-3B – classification and eligibility
                # alone never put an amount there
                if p.claim in AVAILED and in_year and typ in ("inputs", "services", "capital"):
                    if p.claim == "reclaimed":
                        t6["6H"][typ].add(p)
                    else:
                        t6[TREAT_ROW.get(p.treatment or "fcm", "6B")][typ].add(p)
                if p.claim in REVERSED and in_year:
                    t7[p.claim].add(p)
                if p.status in ELIGIBLE and (p.claim == "not_claimed" or (p.claim in AVAILED and p.claim_period
                                                                        and p.claim_period > months[-1])):
                    later += tax
                if p.claim in AVAILED and in_year and v.txn.invoice_date and v.txn.invoice_date < start:
                    earlier += tax
                if p.treatment in RCM or p.treatment == "import_s":
                    rcm[p.treatment].add(p)
                    rcm["goods" if typ == "inputs" else typ if typ in ("services", "capital") else "goods"].add(p)
                head = "14O" if p.nature == "capital" else "14A" if p.nature in GOODS and not v.txn.ledger \
                    else row_for(v.txn.ledger or v.txn.description or "")
                if p.nature in GOODS and head == "14N":
                    head = "14A"
                if p.treatment == "import_g":
                    head = "14D"
                r = t14.setdefault(head, [ZERO, ZERO, ZERO, ZERO])
                r[0] += p.taxable or ZERO
                r[1] += tax
                if p.status in ELIGIBLE:
                    r[2] += tax  # eligible ITC
                if p.claim in AVAILED and in_year:
                    r[3] += tax  # ITC actually claimed
        filed = Gstr3bService(self.db).values(client_id, months)
        has3b = any(set(t) & {"4A1", "4A2", "4A3", "4A4", "4A5"} for t in filed.values())
        t6_3b: dict[str, dict | None] = {}
        for row, codes in T6_3B.items():
            if not has3b:
                t6_3b[row] = None
                continue
            vals = {h: ZERO for h in HEADS}
            for t in filed.values():
                for code in codes:
                    if code in t:
                        for h in HEADS:
                            vals[h] += getattr(t[code], h)
            t6_3b[row] = vals
        try:
            t8 = ItcService(self.db).annual(client_id, fy)
        except ServiceError:
            t8 = None
        # GSTR-9C Table 12
        books = sum((b.tax for k, b in by_s.items() if k != "blocked"), ZERO)
        b12 = earlier + sum((x.igst + x.cgst + x.sgst + x.cess for x in claims if x.action == "CLAIM"
                             and x.period in months and inv_dates.get(x.invoice_id)
                             and inv_dates[x.invoice_id] < start
                             and x.invoice_id not in {v.txn.invoice_id for v in views}), ZERO)
        c12 = later
        d12 = books + b12 - c12
        e12 = None
        try:
            from .gstr9c import Gstr9cService

            st = Gstr9cService(self.db).statement(client_id, fy)
            e12 = next((ln.amount for ln in st.table12 if ln.code == "12E"), None)
        except (ServiceError, ArithmeticError, AttributeError, KeyError):
            e12 = None
        table12 = [("12A", "ITC as per books (register, excluding ineligible)", books, "register"),
                   ("12B", "ITC booked in earlier years claimed in this year", b12, "claim period / claim register"),
                   ("12C", "ITC booked this year to be claimed in later years", c12,
                    "eligible ITC not claimed, or claimed after the year"),
                   ("12D", "ITC as per books (A + B − C)", d12, "computed"),
                   ("12E", "ITC claimed in GSTR-9", e12, "GSTR-9 working (7J)"),
                   ("12F", "Un-reconciled ITC (E − D)", None if e12 is None else e12 - d12, "computed")]
        # Table 13 – possible reasons
        inelig_claimed = sum((p.igst + p.cgst + p.sgst + p.cess for v in views if not v.is_adjustment
                              for p in v.parts if p.status == "blocked" and p.claim in AVAILED), ZERO)
        t13 = []
        for label, amount, why in (
                ("ITC to be claimed in a later year (timing)", c12, "eligible, not claimed / claimed after the year"),
                ("Earlier-year ITC claimed this year", b12, "claim period"),
                ("Ineligible / blocked ITC in the books", by_s["blocked"].tax, "eligibility 'blocked'"),
                ("Ineligible ITC that was claimed – to be reversed", inelig_claimed, "blocked but claimed"),
                ("ITC reversals", by_c["reversed"].tax + by_c["temp_reversed"].tax, "claim reversed"),
                ("Credit notes", sum((v.tax for v in views if v.txn.doc_type == "CRN" and not v.is_adjustment), ZERO),
                 "debit / credit notes"),
                ("RCM ITC", sum((b.tax for k, b in by_t.items() if k in RCM), ZERO), "RCM transactions"),
                ("Tax-ledger postings not in the purchase register",
                 sum((v.tax for v in views if v.txn.match == "taxledger"), ZERO), "unrecorded invoices / wrong posting"),
                ("Claim not verified", by_c["unknown"].tax, "claim state not recorded"),
                ("Unclassified transactions", by_n["unclassified"].tax, "classification pending")):
            if amount:
                t13.append((label, amount, why))
        t14_rows = [(code, labels14[code], *t14[code]) for code, _l in TABLE14 if code in t14]
        # tax ledger totals
        post_tot = {h: sum((p.amount for p in posts if p.head == h and p.kind == "txn"), ZERO) for h in HEADS}
        balances = {}
        for kind in ("opening", "closing"):
            for h in HEADS:
                vals = [p.amount for p in posts if p.head == h and p.kind == kind]
                if vals:
                    balances[f"{kind}:{h}"] = sum(vals, ZERO)
        w = ItcWorking(name, gstin, fy, views, by_n, by_t, by_s, t6, t6_3b, t7, t8, table12, t13, t14_rows, rcm, [],
                       post_tot, balances, final)
        w.by_claim = by_c
        w.inelig_claimed = inelig_claimed
        from .annual_rules import table14_status

        w.table14_status = table14_status(self.db, fy)
        w.controls = self._controls(w, posts, filed)
        return w

    def _controls(self, w: ItcWorking, posts: list[TaxPosting], filed: dict) -> list[Control]:
        out = []
        txns = w.txns
        # 1. ledger reconciliation
        if posts:
            bad = []
            for h in HEADS:
                op, cl = w.ledger_balances.get(f"opening:{h}"), w.ledger_balances.get(f"closing:{h}")
                if op is not None and cl is not None:
                    if abs(op + w.postings_total[h] - cl) > HALF:
                        bad.append(f"{h.upper()}: opening {op} + vouchers {w.postings_total[h]} ≠ closing {cl}")
            adj = [v for v in w.views if v.is_adjustment]
            out.append(Control("C1", "Tax ledgers reconcile to their balances", "fail" if bad else "pass",
                               "; ".join(bad) or f"vouchers agree with the balances; {len(adj)} set-off / adjustment "
                                                 "posting(s) kept apart from purchases", bool(bad)))
        else:
            out.append(Control("C1", "Tax ledgers reconcile to their balances", "warn",
                               "input tax ledgers not imported – register built from the purchase register only"))
        # 2. consolidation / split keeps the totals
        bad = [v for v in txns if v.parts and any(abs(sum((getattr(p, h) for p in v.parts), ZERO) - getattr(v.txn, h))
                                                  > Decimal("0.001") for h in HEADS)]
        out.append(Control("C2", "Splits keep every transaction's tax", "fail" if bad else "pass",
                           f"{len(bad)} transaction(s) whose parts differ from the source" if bad else
                           "parts equal their transactions", bool(bad)))
        # 3. population
        uncl = w.unclassified
        out.append(Control("C3", "Every inward supply classified", "warn" if uncl else "pass",
                           f"{uncl} transaction(s) unclassified (they stay in the population, shown as unclassified)"
                           if uncl else f"{len(txns)} transaction(s), all classified", False))
        # 4. no double counting
        seen, dup = set(), 0
        for v in w.views:
            for pid in json.loads(v.txn.posting_ids or "[]"):
                if pid in seen:
                    dup += 1
                seen.add(pid)
        out.append(Control("C4", "No tax posting counted twice", "fail" if dup else "pass",
                           f"{dup} posting(s) in two transactions" if dup else "each posting in one transaction",
                           bool(dup)))
        diff = [v for v in txns if v.txn.match == "differs"]
        if diff:
            out.append(Control("C4b", "Tax ledger agrees with the purchase register", "warn",
                               f"{len(diff)} voucher(s) with different tax in the tax ledger and the purchase register"))
        # 5. GSTR-3B
        gaps = []
        for row, b3 in w.table6_3b.items():
            if b3 is None or row == "6D":
                continue
            ours = sum((x.tax for x in w.table6[row].values()), ZERO)
            if row == "6C":
                ours += sum((x.tax for x in w.table6["6D"].values()), ZERO)
            theirs = sum(b3.values(), ZERO)
            if abs(ours - theirs) > Decimal("1"):
                gaps.append(f"{row}{'+6D' if row == '6C' else ''}: register ₹{ours:,.2f} vs GSTR-3B ₹{theirs:,.2f}")
        if all(x is None for x in w.table6_3b.values()):
            out.append(Control("C5", "Classified ITC agrees with GSTR-3B", "warn", "GSTR-3B not imported"))
        else:
            out.append(Control("C5", "Classified ITC agrees with GSTR-3B", "warn" if gaps else "pass",
                               "; ".join(gaps) or "Table 6 rows agree with GSTR-3B Table 4"))
        # 6. RCM
        rcm_itc = sum((w.rcm[k].tax for k in RCM), ZERO)
        liab = sum((t["31D"].total for t in filed.values() if "31D" in t), ZERO)
        if rcm_itc or liab:
            ok = abs(rcm_itc - liab) <= Decimal("1")
            out.append(Control("C6", "RCM ITC agrees with RCM tax paid (3.1(d))", "pass" if ok else "warn",
                               f"RCM in the register ₹{rcm_itc:,.2f}; GSTR-3B 3.1(d) ₹{liab:,.2f}" +
                               ("" if ok else " – check payment before claiming")))
        # 7. capital goods vs fixed assets
        cg = w.by_nature["capital"].tax
        from .bifurcation import BifurcationService

        try:
            bs = BifurcationService(self.db).views(self._client_id(w), w.fy)
        except ServiceError:
            bs = []
        fa = [v for v in bs if v.ledger.nature == "asset"]
        if cg and not fa:
            out.append(Control("C7", "Capital goods appear in the fixed asset register", "warn",
                               "capital goods in the register but no fixed-asset ledgers (import the trial balance in "
                               "Ledger classification)"))
        elif fa and not cg:
            out.append(Control("C7", "Capital goods appear in the fixed asset register", "warn",
                               "fixed-asset additions in the trial balance but no capital goods in the register"))
        else:
            out.append(Control("C7", "Capital goods appear in the fixed asset register", "pass",
                               "capital goods and fixed-asset ledgers both present" if cg else "no capital goods"))
        # 8. ineligible – classification and eligibility are not the claim: blocked ITC that was claimed is a risk
        blocked = w.by_status["blocked"].count
        if w.inelig_claimed:
            out.append(Control("C8", "No ineligible ITC claimed", "fail",
                               f"₹{w.inelig_claimed:,.2f} of ITC marked ineligible / blocked was claimed in GSTR-3B – "
                               "reverse it (DRC-03 / next GSTR-3B) or correct the eligibility", True))
        else:
            out.append(Control("C8", "No ineligible ITC claimed", "pass" if not w.to_review else "warn",
                               f"{blocked} transaction(s) blocked, none claimed; {w.to_review} suggestion(s) of low "
                               "confidence still to review"))
        unknown = w.by_claim.get("unknown")
        if unknown and unknown.count:
            out.append(Control("C8b", "ITC claim verified for every transaction", "warn",
                               f"{unknown.count} transaction(s) with the GSTR-3B claim not recorded – Table 6 counts only "
                               "verified claims (claim register, or 'Record claim…')"))
        req = sum(1 for v in txns for p in v.parts if p.status == "reversal_req" and p.claim in ("claimed",))
        if req:
            out.append(Control("C8c", "Reversals required have been made", "warn",
                               f"{req} transaction(s) needing reversal (rules 37 / 42 / 43) claimed but not reversed"))
        # 9. cut-off
        other_fy = [v for v in txns if v.txn.invoice_date and _fy_of(v.txn.invoice_date) != w.fy]
        out.append(Control("C9", "Financial-year cut-off checked", "warn" if other_fy else "pass",
                           f"{len(other_fy)} invoice(s) dated in another financial year (claim year ≠ invoice year – "
                           "check Tables 8 / 13 and 12B/12C)" if other_fy else "all invoices dated in the year"))
        # 10. approval
        crit = [c for c in out if c.status == "fail" and c.critical]
        out.append(Control("C10", "Approved before finalising", "pass" if w.final else "warn",
                           (f"final – {w.final.get('by')} on {w.final.get('on')}" + (
                               f" (despite: {w.final.get('override')})" if w.final.get("override") else ""))
                           if w.final else ("critical controls fail – resolve or record why before finalising"
                                            if crit else "not yet marked final")))
        return out

    def _client_id(self, w: ItcWorking) -> int:
        with self.db.session() as s:
            return s.scalar(select(Client.id).where(Client.gstin == w.gstin))

    def finalise(self, client_id: int, fy: str, user: str, note: str = "", override: str = "") -> dict:
        w = self.working(client_id, fy)
        ok, bad = w.can_finalise
        if not ok and not override.strip():
            raise ServiceError("Not finalised – " + "; ".join(bad) + ". Resolve them, or give the reason for "
                               "finalising despite them.")
        rec = {"by": user, "on": f"{date.today():%d-%m-%Y}", "note": note, "override": override.strip(),
               "failed": bad, "unclassified": w.unclassified}
        with self.db.session() as s:
            key = f"itc_final:{client_id}:{fy}"
            row = s.get(AppSetting, key)
            if row is None:
                row = AppSetting(key=key, value_json="{}")
                s.add(row)
            row.value_json = json.dumps(rec)
            audit(s, "ITC_FINALISE", "itc_register", fy, rec, user, client_id)
        return rec

    def reopen(self, client_id: int, fy: str, user: str) -> None:
        with self.db.session() as s:
            row = s.get(AppSetting, f"itc_final:{client_id}:{fy}")
            if row is not None:
                s.delete(row)
            audit(s, "ITC_REOPEN", "itc_register", fy, {}, user, client_id)

    def remove_year(self, client_id: int, fy: str, user: str) -> int:
        with self.db.session() as s:
            ids = list(s.scalars(select(ItcTxn.id).where(ItcTxn.client_id == client_id,
                                                         ItcTxn.financial_year == fy)))
            s.execute(delete(ItcPart).where(ItcPart.txn_id.in_(ids)))
            s.execute(delete(ItcTxn).where(ItcTxn.id.in_(ids)))
            audit(s, "ITC_REGISTER_REMOVE", "itc_register", fy, {"txns": len(ids)}, user, client_id)
        return len(ids)

    # ------------------------------------------------------------ exports
    def export_xlsx(self, client_id: int, fy: str, path: str | Path) -> Path:
        from ..reports.itc_register_xlsx import build_workbook

        return build_workbook(self, client_id, fy, Path(path))

    def export_pdf(self, client_id: int, fy: str, path: str | Path, firm: str = "") -> Path:
        from ..reports.itc_register_pdf import build_pdf

        return build_pdf(self.working(client_id, fy), Path(path), firm)
