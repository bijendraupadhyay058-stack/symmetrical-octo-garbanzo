"""Advanced ledger classification & bifurcation: the trial balance imported from TallyPrime, each purchase /
expense / fixed-asset ledger classified whole or split into parts, and the summaries that feed GSTR-9 Table 6 and
GSTR-9C Table 14.

Rules kept throughout:

* the imported trial balance is never changed – classification lives in separate split rows, and the parts of a
  ledger must add up to its amount (the difference is shown as unallocated);
* GST on a part comes only from purchase-register invoices chosen for it, figures entered from invoices, or an
  apportionment the user explicitly approved (recorded with the user and date) – never from a percentage alone;
* a suggestion is not a classification until the user approves it; every change is in the audit log and can be
  reversed;
* the working is "ready for GSTR-9 / 9C" only when every ledger is approved and nothing is unallocated. It is a
  working paper for the professional; FIN TAX PRO never files anything.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from sqlalchemy import delete, select

from ..core.money import ZERO
from ..db.database import Database
from ..db.models import AuditLog, Client, Invoice, LedgerMapping, LedgerSplit, SourceFile, TbLedger
from ..importers.pipeline import sha256_of
from ..importers.trial_balance import IN_SCOPE, NATURES, TrialBalance, read_trial_balance
from ..ledgers.classify import (
    ACCT_CLASSES, AVAILED, ELIGIBILITY, GST_CLASSES, GST_SOURCES, INELIGIBLE, ITC_CLASSES, REVERSED, default_head,
    ledger_key, suggest,
)
from .auth import Session, require
from .common import ServiceError, audit, dumps

HEADS = ("igst", "cgst", "sgst", "cess")
PAISA = Decimal("0.01")
TOLERANCE = Decimal("0.50")
#: GSTR-9 Table 6 row for each source of supply
T6_ROW = {"regular": "6B", "rcm_unreg": "6C", "rcm_reg": "6D", "import_g": "6E", "import_s": "6F", "isd": "6G"}
T6_LABEL = {"6B": "6B Inward supplies (other than imports and reverse charge)",
            "6C": "6C Reverse charge – unregistered persons", "6D": "6D Reverse charge – registered persons",
            "6E": "6E Import of goods (including SEZ)", "6F": "6F Import of services", "6G": "6G Input Service Distributor"}
#: GSTR-9 Table 7 row a reversal / ineligible ITC belongs to
T7_ROW = {"rule37": "7A Rule 37", "rule42": "7C/7D Rules 42 and 43", "blocked": "7E Section 17(5)",
          "nonbusiness": "7H Other reversals", "exempt_attr": "7C/7D Rules 42 and 43"}
TABLE14_STATUS = ("Table 14 of GSTR-9C (ITC on expenses) has been optional in recent years under the GSTR-9C "
                  "instructions – check the notification for the year before reporting it. The working is "
                  "prepared either way.")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _q(v: Decimal) -> Decimal:
    return v.quantize(PAISA, rounding=ROUND_HALF_UP)


def _dec(v) -> Decimal | None:
    if v in (None, ""):
        return None
    return v if isinstance(v, Decimal) else Decimal(str(v).replace(",", "").strip())


@dataclass
class SplitIn:
    """A part of a ledger as entered on the screen."""
    amount: Decimal
    acct_class: str
    gst_class: str
    gst_source: str = "regular"
    head_9c: str = ""
    eligibility: str = ""
    taxable: Decimal | None = None
    igst: Decimal | None = None
    cgst: Decimal | None = None
    sgst: Decimal | None = None
    cess: Decimal | None = None
    gst_basis: str = ""
    basis_note: str = ""
    invoice_ids: list[int] = field(default_factory=list)
    percent: Decimal | None = None
    remarks: str = ""


@dataclass
class LedgerView:
    ledger: TbLedger
    splits: list[LedgerSplit]

    @property
    def classified(self) -> Decimal:
        return sum((s.amount for s in self.splits), ZERO)

    @property
    def unallocated(self) -> Decimal:
        return self.ledger.base - self.classified

    @property
    def in_scope(self) -> bool:
        return self.ledger.nature in IN_SCOPE

    @property
    def gst(self) -> dict[str, Decimal | None]:
        out = {}
        for h in ("taxable", *HEADS):
            vals = [getattr(s, h) for s in self.splits if getattr(s, h) is not None]
            out[h] = sum(vals, ZERO) if vals else None
        return out

    def label(self, attr: str) -> str:
        """One class for a single part, 'Split (n)' for several."""
        vals = {getattr(s, attr) for s in self.splits}
        if not vals:
            return ""
        if len(vals) > 1:
            return f"Split ({len(self.splits)})"
        v = vals.pop()
        return {"gst_class": GST_CLASSES, "eligibility": ELIGIBILITY, "gst_source": GST_SOURCES}.get(attr, {}).get(v, v)

    @property
    def warnings(self) -> list[str]:
        out = []
        if not self.in_scope:
            return out
        if abs(self.unallocated) > TOLERANCE:
            out.append(f"₹{self.unallocated:,.2f} not classified")
        for s in self.splits:
            if s.gst_class in ITC_CLASSES and not s.eligibility:
                out.append(f"ITC eligibility of '{s.acct_class}' not decided")
            if s.gst_class in ITC_CLASSES and s.eligibility in AVAILED and s.igst is None and s.cgst is None:
                out.append(f"GST of '{s.acct_class}' not verified from invoices")
            if s.gst_basis == "apportioned":
                out.append(f"GST of '{s.acct_class}' apportioned ({s.basis_note})")
        if self.ledger.nature == "asset" and self.ledger.debit is None and not self.ledger.base_note:
            out.append("closing balance used – enter the additions of the year")
        return out

    @property
    def state(self) -> str:
        if not self.in_scope:
            return "Not for classification"
        if not self.splits:
            return "Pending"
        if not all(s.approved for s in self.splits):
            return f"Suggested ({self.ledger.confidence})" if self.ledger.confidence else "Suggested"
        return "Approved" if abs(self.unallocated) <= TOLERANCE else "Partly classified"


@dataclass
class ClassTotal:
    key: str
    label: str
    value: Decimal = ZERO
    taxable: Decimal = ZERO
    igst: Decimal = ZERO
    cgst: Decimal = ZERO
    sgst: Decimal = ZERO
    cess: Decimal = ZERO
    no_gst_value: Decimal = ZERO  # value of parts without GST figures

    @property
    def tax(self) -> Decimal:
        return self.igst + self.cgst + self.sgst + self.cess

    def add(self, s: LedgerSplit) -> None:
        self.value += s.amount
        if s.igst is None and s.cgst is None and s.sgst is None:
            self.no_gst_value += s.amount
        self.taxable += s.taxable or ZERO
        for h in HEADS:
            setattr(self, h, getattr(self, h) + (getattr(s, h) or ZERO))


@dataclass
class Row14:
    code: str
    label: str
    value: Decimal = ZERO
    gst: Decimal = ZERO
    eligible: Decimal = ZERO
    ineligible: Decimal = ZERO
    availed: Decimal = ZERO
    reversed: Decimal = ZERO
    explanation: list[str] = field(default_factory=list)

    @property
    def difference(self) -> Decimal:
        """GST charged not accounted for as availed, reversed or ineligible (e.g. not availed, or no eligibility)."""
        return self.gst - self.availed - self.reversed - self.ineligible


@dataclass
class BifurcationSummary:
    client: str
    gstin: str
    fy: str
    views: list[LedgerView]
    by_acct: dict[str, ClassTotal]
    by_group: dict[str, ClassTotal]
    by_gst: dict[str, ClassTotal]
    table6: dict[tuple[str, str], ClassTotal]  # (row, gst class) -> totals of availed ITC
    table7: dict[str, ClassTotal]
    table14: list[Row14]
    itc_3b_4a5: dict[str, Decimal] | None
    exceptions: list[tuple[str, str, str]] = field(default_factory=list)  # (severity, ledger, text)
    tb_debit: Decimal = ZERO
    tb_credit: Decimal = ZERO

    @property
    def in_scope(self) -> list[LedgerView]:
        return [v for v in self.views if v.in_scope]

    def count(self, state: str) -> int:
        return sum(1 for v in self.in_scope if v.state.startswith(state))

    @property
    def unallocated(self) -> Decimal:
        return sum((v.unallocated for v in self.in_scope if abs(v.unallocated) > TOLERANCE), ZERO)

    @property
    def classified_value(self) -> Decimal:
        return sum((t.value for k, t in self.by_gst.items() if k != "excluded"), ZERO)

    @property
    def undecided(self) -> int:
        return sum(1 for v in self.in_scope for w in v.warnings if "not decided" in w)

    @property
    def missing_gst(self) -> int:
        return sum(1 for v in self.in_scope for w in v.warnings if "not verified" in w)

    def table6_total(self, row: str) -> ClassTotal:
        t = ClassTotal(row, T6_LABEL.get(row, row))
        for (r, _g), x in self.table6.items():
            if r == row:
                t.value += x.value
                t.taxable += x.taxable
                for h in HEADS:
                    setattr(t, h, getattr(t, h) + getattr(x, h))
        return t

    @property
    def difference_6b(self) -> dict[str, Decimal] | None:
        """ITC of the 6B parts less GSTR-3B 4(A)(5) for the year, by head (None without GSTR-3B)."""
        if self.itc_3b_4a5 is None:
            return None
        t = self.table6_total("6B")
        return {h: getattr(t, h) - self.itc_3b_4a5.get(h, ZERO) for h in HEADS}

    @property
    def ready(self) -> tuple[bool, list[str]]:
        reasons = []
        pending = [v for v in self.in_scope if v.state != "Approved"]
        if not self.in_scope:
            reasons.append("no trial balance imported for the year")
        if pending:
            reasons.append(f"{len(pending)} ledger(s) not approved / fully classified")
        if self.unallocated:
            reasons.append(f"₹{self.unallocated:,.2f} not classified")
        if self.undecided:
            reasons.append(f"{self.undecided} part(s) without an ITC eligibility decision")
        if self.missing_gst:
            reasons.append(f"{self.missing_gst} part(s) with eligible ITC but no GST from invoices")
        d = self.difference_6b
        if d and any(abs(v) > Decimal("1") for v in d.values()):
            reasons.append(f"6B ITC differs from GSTR-3B 4(A)(5) by ₹{sum(d.values(), ZERO):,.2f}")
        return not reasons, reasons


class BifurcationService:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------ import
    def import_tb(self, client_id: int, fy: str, path: str | Path, user: str | None = None,
                  tb: TrialBalance | None = None) -> tuple[SourceFile, TrialBalance, dict]:
        """Save a trial balance for the year. Ledgers already classified keep their parts when the same ledger is in
        the new file; a changed amount shows as unallocated. Ledgers not in the new file are removed (audited)."""
        path = Path(path)
        tb = tb or read_trial_balance(path)
        digest = sha256_of(path)
        stats = {"new": 0, "updated": 0, "changed": 0, "removed": 0, "kept_splits": 0}
        with self.db.session() as s:
            if s.get(Client, client_id) is None:
                raise ServiceError(f"Client {client_id} not found")
            dup = s.scalar(select(SourceFile.id).where(SourceFile.client_id == client_id, SourceFile.sha256 == digest,
                                                       SourceFile.source_type == "TB"))
            if dup:
                raise ServiceError(f"{path.name} was already imported (import #{dup})")
            sf = SourceFile(client_id=client_id, source_type="TB", file_name=path.name, file_path=str(path.resolve()),
                            sha256=digest, layout=tb.layout[:40], period=None, rows_read=len(tb.rows),
                            documents_imported=len(tb.rows), warnings_json=dumps(tb.warnings),
                            imported_by=user or "", mapping_json=dumps({"financial_year": fy}))
            s.add(sf)
            s.flush()
            old = {lg.name.lower(): lg for lg in s.scalars(select(TbLedger).where(
                TbLedger.client_id == client_id, TbLedger.financial_year == fy))}
            seen = set()
            for r in tb.rows:
                key = r.name.lower()
                seen.add(key)
                base, note = r.closing, ""
                if r.nature == "asset" and r.debit is not None:
                    base, note = r.debit, "additions of the year (debits) – opening balance excluded"
                lg = old.get(key)
                if lg is None:
                    s.add(TbLedger(client_id=client_id, financial_year=fy, source_file_id=sf.id, name=r.name[:200],
                                   parent=r.parent[:200], primary_group=(r.primary or "")[:80], nature=r.nature,
                                   opening=r.opening, debit=r.debit, credit=r.credit, closing=r.closing, base=base,
                                   base_note=note, updated_by=user or ""))
                    stats["new"] += 1
                    continue
                stats["updated"] += 1
                if lg.closing != r.closing:
                    stats["changed"] += 1
                    audit(s, "TB_LEDGER_CHANGED", "tb_ledger", lg.id, {"ledger": lg.name, "before": str(lg.closing),
                                                                      "after": str(r.closing)}, user, client_id)
                had_base_note = lg.base_note and not lg.base_note.startswith("additions of the year")
                lg.source_file_id, lg.parent, lg.primary_group = sf.id, r.parent[:200], (r.primary or "")[:80]
                lg.opening, lg.debit, lg.credit, lg.closing = r.opening, r.debit, r.credit, r.closing
                if not had_base_note:  # a base the user entered (e.g. additions) is kept
                    lg.base, lg.base_note = base, note
                lg.nature = lg.nature if lg.nature != "other" or r.nature == "other" else r.nature
                n = len(list(s.scalars(select(LedgerSplit.id).where(LedgerSplit.ledger_id == lg.id))))
                stats["kept_splits"] += n
                if n and lg.status == "approved":
                    total = sum((x for x in s.scalars(select(LedgerSplit.amount).where(
                        LedgerSplit.ledger_id == lg.id))), ZERO)
                    if abs(total - lg.base) > TOLERANCE:
                        lg.status = "partial"
            for key, lg in old.items():
                if key in seen:
                    continue
                splits = list(s.scalars(select(LedgerSplit).where(LedgerSplit.ledger_id == lg.id)))
                audit(s, "TB_LEDGER_REMOVED", "tb_ledger", lg.id, {"ledger": lg.name, "closing": str(lg.closing),
                                                                  "splits": [self._split_dict(x) for x in splits]},
                      user, client_id)
                for x in splits:
                    s.delete(x)
                s.delete(lg)
                stats["removed"] += 1
            audit(s, "IMPORT", "trial_balance", sf.id, {"file": path.name, "fy": fy, **stats,
                                                         "debit": str(tb.total_debit), "credit": str(tb.total_credit),
                                                         "warnings": tb.warnings}, user, client_id)
            s.expunge(sf)
        return sf, tb, stats

    def fetch_from_tally(self, client_id: int, fy: str, company: str, out_dir: str | Path, url: str = "",
                         user: str | None = None):
        from ..importers.tally_xml import DEFAULT_URL, TallyClient
        from ..importers.trial_balance import fetch_from_tally

        start, end = date(int(fy[:4]), 4, 1), date(int(fy[:4]) + 1, 3, 31)
        data, tb = fetch_from_tally(TallyClient(url or DEFAULT_URL), company, start, end)
        out = Path(out_dir) / f"Tally_TB_{''.join(c if c.isalnum() else '_' for c in company)}_{fy}.xml"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        return self.import_tb(client_id, fy, out, user, tb)

    # ------------------------------------------------------------- reads
    def views(self, client_id: int, fy: str) -> list[LedgerView]:
        return self.db.cached(("bif_views", client_id, fy), lambda: self._views(client_id, fy))

    def _views(self, client_id: int, fy: str) -> list[LedgerView]:
        with self.db.session() as s:
            ledgers = list(s.scalars(select(TbLedger).where(TbLedger.client_id == client_id,
                                                            TbLedger.financial_year == fy).order_by(TbLedger.id)))
            ids = [lg.id for lg in ledgers]
            splits: dict[int, list[LedgerSplit]] = defaultdict(list)
            if ids:
                for sp in s.scalars(select(LedgerSplit).where(LedgerSplit.ledger_id.in_(ids)).order_by(LedgerSplit.id)):
                    splits[sp.ledger_id].append(sp)
            s.expunge_all()
        return [LedgerView(lg, splits.get(lg.id, [])) for lg in ledgers]

    def view(self, ledger_id: int) -> LedgerView:
        with self.db.session() as s:
            lg = s.get(TbLedger, ledger_id)
            if lg is None:
                raise ServiceError(f"Ledger #{ledger_id} not found")
            sp = list(s.scalars(select(LedgerSplit).where(LedgerSplit.ledger_id == ledger_id).order_by(LedgerSplit.id)))
            s.expunge_all()
        return LedgerView(lg, sp)

    def years(self, client_id: int) -> list[str]:
        with self.db.session() as s:
            return sorted(set(s.scalars(select(TbLedger.financial_year).where(TbLedger.client_id == client_id))))

    # ----------------------------------------------------------- changes
    @staticmethod
    def _split_dict(x: LedgerSplit) -> dict:
        return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in (
            ("amount", x.amount), ("acct_class", x.acct_class), ("gst_class", x.gst_class), ("gst_source", x.gst_source),
            ("head_9c", x.head_9c), ("eligibility", x.eligibility), ("taxable", x.taxable), ("igst", x.igst),
            ("cgst", x.cgst), ("sgst", x.sgst), ("cess", x.cess), ("gst_basis", x.gst_basis),
            ("basis_note", x.basis_note), ("approved", x.approved))}

    @staticmethod
    def _validate(sp: SplitIn) -> None:
        if sp.acct_class not in ACCT_CLASSES and not sp.acct_class.strip():
            raise ServiceError("Choose the accounting classification of each part")
        if sp.gst_class not in GST_CLASSES:
            raise ServiceError(f"Unknown GST classification '{sp.gst_class}'")
        if sp.gst_source not in GST_SOURCES:
            raise ServiceError(f"Unknown source of supply '{sp.gst_source}'")
        if sp.eligibility and sp.eligibility not in ELIGIBILITY:
            raise ServiceError(f"Unknown ITC eligibility '{sp.eligibility}'")
        has_gst = any(getattr(sp, h) not in (None, ZERO) for h in HEADS)
        if has_gst and sp.gst_basis not in ("invoices", "entered", "apportioned"):
            raise ServiceError("Say where the GST of each part comes from (invoices, entered from invoices, or an "
                               "apportionment you approve)")
        if sp.gst_basis == "apportioned" and not sp.basis_note.strip():
            raise ServiceError("Record how the GST was apportioned (e.g. '50 % of ledger GST ₹36,000, as approved')")
        if sp.gst_class in ("nogst", "exempt", "excluded") and has_gst:
            raise ServiceError(f"A part classified '{GST_CLASSES[sp.gst_class]}' cannot carry GST")

    def save_splits(self, ledger_id: int, parts: list[SplitIn], user: str, approve: bool = True) -> LedgerView:
        """Replace the ledger's parts (each audited). The parts may be fewer than the ledger (the rest shows as
        unallocated) but never more; GST from invoices must not be used in two parts."""
        for p in parts:
            p.amount = _q(_dec(p.amount) or ZERO)
            self._validate(p)
        with self.db.session() as s:
            lg = s.get(TbLedger, ledger_id)
            if lg is None:
                raise ServiceError(f"Ledger #{ledger_id} not found")
            total = sum((p.amount for p in parts), ZERO)
            if lg.base >= 0 and total - lg.base > TOLERANCE or lg.base < 0 and total - lg.base < -TOLERANCE:
                raise ServiceError(f"The parts add up to ₹{total:,.2f}, more than the ledger's ₹{lg.base:,.2f}")
            used = self._used_invoices(s, lg.client_id, exclude_ledger=ledger_id)
            mine: set[int] = set()
            for p in parts:
                for i in p.invoice_ids:
                    if i in used:
                        raise ServiceError(f"Invoice #{i} is already used for the GST of ledger '{used[i]}' – the "
                                           "same GST cannot be counted twice")
                    if i in mine:
                        raise ServiceError(f"Invoice #{i} is used in two parts of this ledger")
                    mine.add(i)
            old = list(s.scalars(select(LedgerSplit).where(LedgerSplit.ledger_id == ledger_id)))
            before = [self._split_dict(x) for x in old]
            for x in old:
                s.delete(x)
            s.flush()
            now = _now()
            for p in parts:
                s.add(LedgerSplit(client_id=lg.client_id, ledger_id=ledger_id, amount=p.amount,
                                  acct_class=p.acct_class.strip()[:60], gst_class=p.gst_class, gst_source=p.gst_source,
                                  head_9c=p.head_9c or ("" if p.gst_class == "excluded" else default_head(
                                      p.acct_class, p.gst_class)), eligibility=p.eligibility or ("na" if p.gst_class in (
                                      "nogst", "exempt", "excluded") else ""),
                                  taxable=_dec(p.taxable), igst=_dec(p.igst), cgst=_dec(p.cgst), sgst=_dec(p.sgst),
                                  cess=_dec(p.cess), gst_basis=p.gst_basis, basis_note=p.basis_note[:300],
                                  invoice_ids=json.dumps(sorted(p.invoice_ids)), percent=_dec(p.percent),
                                  remarks=p.remarks, approved=approve, approved_by=user[:80] if approve else "",
                                  approved_at=now if approve else None))
            lg.status = ("approved" if abs(lg.base - total) <= TOLERANCE else "partial") if approve and parts else \
                ("suggested" if parts else "pending")
            if approve:
                lg.confidence = ""
            lg.updated_by = user[:80]
            audit(s, "LEDGER_CLASSIFY", "tb_ledger", ledger_id, {
                "ledger": lg.name, "amount": str(lg.base), "before": before,
                "after": [{**p.__dict__, "amount": str(p.amount)} for p in parts], "approved": approve},
                user, lg.client_id)
            if approve and len(parts) == 1:
                self._remember(s, lg.client_id, lg.name, parts[0], user)
        return self.view(ledger_id)

    @staticmethod
    def _remember(s, client_id: int, name: str, p: SplitIn, user: str) -> None:
        key = ledger_key(name)[:200]
        m = s.scalar(select(LedgerMapping).where(LedgerMapping.client_id == client_id, LedgerMapping.ledger_key == key))
        if m is None:
            m = LedgerMapping(client_id=client_id, ledger_key=key)
            s.add(m)
        m.acct_class, m.gst_class, m.gst_source = p.acct_class[:60], p.gst_class, p.gst_source
        m.head_9c, m.eligibility, m.approved_by = p.head_9c, p.eligibility, user[:80]

    @staticmethod
    def _used_invoices(s, client_id: int, exclude_ledger: int | None = None) -> dict[int, str]:
        out = {}
        q = select(LedgerSplit.invoice_ids, TbLedger.name).join(TbLedger, TbLedger.id == LedgerSplit.ledger_id).where(
            LedgerSplit.client_id == client_id, LedgerSplit.invoice_ids != "[]")
        if exclude_ledger is not None:
            q = q.where(LedgerSplit.ledger_id != exclude_ledger)
        for ids, name in s.execute(q):
            for i in json.loads(ids or "[]"):
                out[int(i)] = name
        return out

    def classify_whole(self, ledger_ids: list[int], acct_class: str, gst_class: str, user: str,
                       gst_source: str = "regular", head_9c: str = "", eligibility: str = "") -> int:
        """Bulk: each ledger classified whole under one classification (approved; GST to be added from invoices)."""
        n = 0
        for lid in ledger_ids:
            v = self.view(lid)
            if not v.in_scope:
                continue
            self.save_splits(lid, [SplitIn(v.ledger.base, acct_class, gst_class, gst_source, head_9c, eligibility)],
                             user)
            n += 1
        return n

    def suggest_all(self, client_id: int, fy: str, user: str, ledger_ids: list[int] | None = None) -> int:
        """Suggest a classification for pending ledgers (never overwrites an approved or partial one)."""
        with self.db.session() as s:
            saved = {m.ledger_key: {"acct_class": m.acct_class, "gst_class": m.gst_class, "gst_source": m.gst_source,
                                    "head_9c": m.head_9c, "eligibility": m.eligibility}
                     for m in s.scalars(select(LedgerMapping).where(LedgerMapping.client_id == client_id))}
        n = 0
        for v in self.views(client_id, fy):
            if not v.in_scope or (ledger_ids is not None and v.ledger.id not in ledger_ids):
                continue
            if v.splits and (all(x.approved for x in v.splits) or v.ledger.status in ("approved", "partial")):
                continue
            sg = suggest(v.ledger.name, v.ledger.parent or v.ledger.primary_group, v.ledger.nature,
                         saved.get(ledger_key(v.ledger.name)))
            if sg is None:
                continue
            self.save_splits(v.ledger.id, [SplitIn(v.ledger.base, sg.acct_class, sg.gst_class, sg.gst_source,
                                                   sg.head_9c, sg.eligibility, remarks=f"Suggested: {sg.reason}")],
                             user, approve=False)
            with self.db.session() as s:
                lg = s.get(TbLedger, v.ledger.id)
                lg.confidence = sg.confidence
            n += 1
        return n

    def approve(self, ledger_ids: list[int], user: str) -> int:
        """Approve the suggested parts of the ledgers (the user's decision, audited; remembered for other years)."""
        n = 0
        with self.db.session() as s:
            for lid in ledger_ids:
                lg = s.get(TbLedger, lid)
                splits = list(s.scalars(select(LedgerSplit).where(LedgerSplit.ledger_id == lid)))
                if lg is None or not splits or all(x.approved for x in splits):
                    continue
                now = _now()
                for x in splits:
                    x.approved, x.approved_by, x.approved_at = True, user[:80], now
                total = sum((x.amount for x in splits), ZERO)
                lg.status = "approved" if abs(lg.base - total) <= TOLERANCE else "partial"
                audit(s, "LEDGER_APPROVE", "tb_ledger", lid, {"ledger": lg.name, "confidence": lg.confidence,
                                                             "parts": [self._split_dict(x) for x in splits]},
                      user, lg.client_id)
                lg.confidence = ""
                if len(splits) == 1:
                    x = splits[0]
                    self._remember(s, lg.client_id, lg.name, SplitIn(x.amount, x.acct_class, x.gst_class,
                                                                     x.gst_source, x.head_9c, x.eligibility), user)
                n += 1
        return n

    def clear(self, ledger_ids: list[int], user: str) -> int:
        """Reverse the classification of the ledgers (the parts are kept in the audit log)."""
        n = 0
        with self.db.session() as s:
            for lid in ledger_ids:
                lg = s.get(TbLedger, lid)
                splits = list(s.scalars(select(LedgerSplit).where(LedgerSplit.ledger_id == lid)))
                if lg is None or not splits:
                    continue
                audit(s, "LEDGER_UNCLASSIFY", "tb_ledger", lid, {"ledger": lg.name,
                                                                "parts": [self._split_dict(x) for x in splits]},
                      user, lg.client_id)
                for x in splits:
                    s.delete(x)
                lg.status, lg.confidence, lg.updated_by = "pending", "", user[:80]
                n += 1
        return n

    def set_base(self, ledger_id: int, amount, note: str, user: str) -> None:
        """Amount to classify, e.g. a fixed asset's additions of the year instead of its closing balance."""
        amount = _q(_dec(amount) or ZERO)
        if not note.strip():
            raise ServiceError("Say what the amount is (e.g. 'additions per fixed asset register')")
        with self.db.session() as s:
            lg = s.get(TbLedger, ledger_id)
            if lg is None:
                raise ServiceError(f"Ledger #{ledger_id} not found")
            audit(s, "LEDGER_BASE", "tb_ledger", ledger_id, {"ledger": lg.name, "before": str(lg.base),
                                                            "after": str(amount), "note": note}, user, lg.client_id)
            lg.base, lg.base_note, lg.updated_by = amount, note.strip()[:200], user[:80]
            total = sum((x.amount for x in s.scalars(select(LedgerSplit).where(LedgerSplit.ledger_id == ledger_id))),
                        ZERO)
            if lg.status == "approved" and abs(total - amount) > TOLERANCE:
                lg.status = "partial"

    def set_nature(self, ledger_ids: list[int], nature: str, user: str) -> int:
        if nature not in NATURES:
            raise ServiceError(f"Unknown ledger nature {nature}")
        with self.db.session() as s:
            rows = list(s.scalars(select(TbLedger).where(TbLedger.id.in_(ledger_ids))))
            for lg in rows:
                audit(s, "LEDGER_NATURE", "tb_ledger", lg.id, {"ledger": lg.name, "before": lg.nature, "after": nature},
                      user, lg.client_id)
                lg.nature = nature
        return len(rows)

    def set_remarks(self, ledger_id: int, remarks: str, user: str) -> None:
        with self.db.session() as s:
            lg = s.get(TbLedger, ledger_id)
            if lg is not None:
                lg.remarks, lg.updated_by = remarks.strip(), user[:80]

    # ---------------------------------------------------- invoice-wise GST
    def invoices(self, client_id: int, fy: str, text: str = "", limit: int = 500) -> list[dict]:
        """Purchase-register documents of the year not yet used for a ledger part (for invoice-wise GST)."""
        from ..itc.annual import fy_months

        with self.db.session() as s:
            used = self._used_invoices(s, client_id)
            q = select(Invoice).where(Invoice.client_id == client_id, Invoice.source_type == "BOOKS",
                                      Invoice.period.in_(fy_months(fy))).order_by(Invoice.invoice_date)
            out = []
            t = text.strip().lower()
            for r in s.scalars(q):
                if r.id in used:
                    continue
                if t and t not in f"{r.supplier_name} {r.supplier_gstin} {r.invoice_no} {r.description}".lower():
                    continue
                k = -1 if r.doc_type == "CRN" else 1
                out.append({"id": r.id, "supplier": r.supplier_name, "gstin": r.supplier_gstin, "no": r.invoice_no,
                            "date": r.invoice_date, "taxable": k * r.taxable, "igst": k * r.igst, "cgst": k * r.cgst,
                            "sgst": k * r.sgst, "cess": k * r.cess, "description": r.description or ""})
                if len(out) >= limit:
                    break
        return out

    def part_from_invoices(self, client_id: int, invoice_ids: list[int], acct_class: str, gst_class: str,
                           **kw) -> SplitIn:
        """A part whose amount and GST are the chosen purchase-register documents' (taxable value as the amount)."""
        if not invoice_ids:
            raise ServiceError("Choose at least one invoice")
        with self.db.session() as s:
            rows = list(s.scalars(select(Invoice).where(Invoice.id.in_(invoice_ids), Invoice.client_id == client_id)))
        if len(rows) != len(set(invoice_ids)):
            raise ServiceError("Some of the chosen invoices are not this client's")
        tot = {k: ZERO for k in ("taxable", *HEADS)}
        for r in rows:
            k = -1 if r.doc_type == "CRN" else 1
            for f in tot:
                tot[f] += k * (getattr(r, f) or ZERO)
        return SplitIn(tot["taxable"], acct_class, gst_class, taxable=tot["taxable"], igst=tot["igst"],
                       cgst=tot["cgst"], sgst=tot["sgst"], cess=tot["cess"], gst_basis="invoices",
                       basis_note=f"{len(rows)} purchase-register document(s)", invoice_ids=sorted(invoice_ids), **kw)

    # ----------------------------------------------------------- summary
    def summary(self, client_id: int, fy: str) -> BifurcationSummary:
        return self.db.cached(("bif_summary", client_id, fy), lambda: self._summary(client_id, fy))

    def _summary(self, client_id: int, fy: str) -> BifurcationSummary:
        from ..gstr9.expenses import TABLE14
        from ..itc.annual import fy_months
        from .gstr3b import Gstr3bService

        with self.db.session() as s:
            c = s.get(Client, client_id)
            if c is None:
                raise ServiceError(f"Client {client_id} not found")
            name, gstin = c.name, c.gstin
        views = self.views(client_id, fy)
        by_acct: dict[str, ClassTotal] = {}
        by_group: dict[str, ClassTotal] = {}
        by_gst = {k: ClassTotal(k, v) for k, v in GST_CLASSES.items()}
        t6: dict[tuple[str, str], ClassTotal] = {}
        t7: dict[str, ClassTotal] = {}
        rows14 = {code: Row14(code, label) for code, label in TABLE14}
        out_exc: list[tuple[str, str, str]] = []
        for v in views:
            for w in v.warnings:
                out_exc.append(("red" if "not classified" in w else "amber", v.ledger.name, w))
            if v.in_scope and not v.splits:
                out_exc.append(("red", v.ledger.name, "not classified"))
            for sp in v.splits:
                by_acct.setdefault(sp.acct_class, ClassTotal(sp.acct_class, sp.acct_class)).add(sp)
                grp = ACCT_CLASSES.get(sp.acct_class, "Other")
                by_group.setdefault(grp, ClassTotal(grp, grp)).add(sp)
                by_gst[sp.gst_class].add(sp)
                tax = sum((getattr(sp, h) or ZERO for h in HEADS), ZERO)
                if sp.gst_class in ITC_CLASSES and sp.eligibility in AVAILED:
                    row = T6_ROW.get(sp.gst_source, "6B")
                    t6.setdefault((row, sp.gst_class), ClassTotal(f"{row}:{sp.gst_class}",
                                                                  GST_CLASSES[sp.gst_class])).add(sp)
                if sp.eligibility in T7_ROW and tax:
                    t7.setdefault(T7_ROW[sp.eligibility], ClassTotal(sp.eligibility, T7_ROW[sp.eligibility])).add(sp)
                if sp.gst_class == "excluded":
                    continue
                r14 = rows14.get(sp.head_9c or default_head(sp.acct_class, sp.gst_class)) or rows14["14N"]
                r14.value += sp.amount
                r14.gst += tax
                if sp.eligibility in AVAILED:
                    r14.eligible += tax
                    r14.availed += tax
                elif sp.eligibility in INELIGIBLE:
                    r14.ineligible += tax
                elif sp.eligibility in REVERSED:
                    r14.eligible += tax
                    r14.reversed += tax
                elif sp.eligibility == "not_availed":
                    r14.eligible += tax
                if sp.remarks and not sp.remarks.startswith("Suggested") and len(r14.explanation) < 3:
                    r14.explanation.append(sp.remarks[:80])
        cg_purchase = any(sp.gst_class == "capital" for v in views if v.ledger.nature != "asset" for sp in v.splits)
        cg_asset = any(sp.gst_class == "capital" for v in views if v.ledger.nature == "asset" for sp in v.splits)
        if cg_purchase and cg_asset:
            out_exc.append(("amber", "(capital goods)", "Capital goods are classified in both purchase / expense "
                                                        "ledgers and fixed-asset ledgers – make sure no asset is counted "
                                                        "in both (mark the second as 'Counted in another ledger')"))
        filed = Gstr3bService(self.db).values(client_id, fy_months(fy))
        itc_3b = None
        if any("4A5" in t for t in filed.values()):
            itc_3b = {h: sum((getattr(t["4A5"], h) for t in filed.values() if "4A5" in t), ZERO) for h in HEADS}
        debit = sum((v.ledger.closing for v in views if v.ledger.closing > 0), ZERO)
        credit = -sum((v.ledger.closing for v in views if v.ledger.closing < 0), ZERO)
        if views and abs(debit - credit) > Decimal("1"):
            out_exc.insert(0, ("red", "(trial balance)", f"Debit total ₹{debit:,.2f} ≠ credit total ₹{credit:,.2f}"))
        return BifurcationSummary(name, gstin, fy, views, by_acct, by_group, by_gst, t6, t7, list(rows14.values()),
                                  itc_3b, out_exc, debit, credit)

    # --------------------------------------------------------- outputs
    def push_table14(self, client_id: int, fy: str, by: Session) -> int:
        """Send the Table 14 working to the GSTR-9C figures (each figure audited there). Refused while anything is
        unallocated or pending."""
        from ..gstr9.expenses import TABLE14
        from .gstr9c import Gstr9cService

        require(by, "review")
        sm = self.summary(client_id, fy)
        ok, reasons = sm.ready
        blocking = [r for r in reasons if "6B" not in r and "no GST" not in r]
        if blocking:
            raise ServiceError("Not sent – " + "; ".join(blocking))
        svc = Gstr9cService(self.db)
        n = 0
        rows = {r.code: r for r in sm.table14}
        for code, _label in TABLE14:
            r = rows[code]
            if not r.value and not r.gst:
                continue
            for part, amount in (("V", r.value), ("T", r.gst), ("E", r.availed)):
                svc.set_input(client_id, fy, f"{code}-{part}", amount, "From ledger bifurcation", by)
                n += 1
        return n

    def table6_split(self, client_id: int, fy: str) -> dict[str, dict[str, Decimal]] | None:
        """6B ITC by type (ip / cg / is) for the draft GSTR-9 JSON – only when the working is complete and agrees with
        GSTR-3B 4(A)(5) within ₹1 per head; otherwise None (the split is left to the offline tool)."""
        sm = self.summary(client_id, fy)
        ok, _reasons = sm.ready
        if not ok or sm.itc_3b_4a5 is None:
            return None
        out = {}
        for gst, typ in (("inputs", "ip"), ("capital", "cg"), ("services", "is")):
            t = sm.table6.get(("6B", gst))
            out[typ] = {h: (getattr(t, h) if t else ZERO) for h in HEADS}
        return out

    def audit_trail(self, client_id: int, limit: int = 2000) -> list[AuditLog]:
        with self.db.session() as s:
            return list(s.scalars(select(AuditLog).where(
                AuditLog.client_id == client_id,
                AuditLog.action.in_(["LEDGER_CLASSIFY", "LEDGER_APPROVE", "LEDGER_UNCLASSIFY", "LEDGER_BASE",
                                     "LEDGER_NATURE", "TB_LEDGER_CHANGED", "TB_LEDGER_REMOVED"])).order_by(
                AuditLog.id.desc()).limit(limit)))

    def remove_year(self, client_id: int, fy: str, user: str) -> int:
        with self.db.session() as s:
            ids = list(s.scalars(select(TbLedger.id).where(TbLedger.client_id == client_id,
                                                           TbLedger.financial_year == fy)))
            s.execute(delete(LedgerSplit).where(LedgerSplit.ledger_id.in_(ids)))
            s.execute(delete(TbLedger).where(TbLedger.id.in_(ids)))
            audit(s, "TB_REMOVE", "trial_balance", fy, {"ledgers": len(ids)}, user, client_id)
        return len(ids)

    def export_xlsx(self, client_id: int, fy: str, path: str | Path) -> Path:
        from ..reports.bifurcation_xlsx import build_workbook

        return build_workbook(self, client_id, fy, Path(path))

    def export_pdf(self, client_id: int, fy: str, path: str | Path, firm: str = "") -> Path:
        from ..reports.bifurcation_pdf import build_pdf

        return build_pdf(self.summary(client_id, fy), Path(path), firm)
