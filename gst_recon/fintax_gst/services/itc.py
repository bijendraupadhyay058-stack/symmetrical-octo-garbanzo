"""ITC review, claim register, rules, IMS comparison, Table 4 working and GSTR-9 Table 8."""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from ..core.models import PAIRED_CATEGORIES, DocType, Source
from ..core.money import ZERO
from ..db.database import Database
from ..db.models import Invoice, ItcClaim, ItcReview, ItcRuleRow, OtherItc, ReconRun, SourceFile
from ..importers.gstr3b import Gstr3bValues
from ..importers.parsing import parse_period
from ..itc.annual import Table8, default_cutoff, fy_months, gstr9_table8
from ..itc.ims import ImsRow, compare_ims, ims_actions_for_books
from ..itc.review import ClaimState, DocReview, buckets, review_lines
from ..itc.rules import DEFAULTS_BY_CODE, Rule, resolve
from ..itc.table4 import ClaimAction, PeriodWorking, build_period
from .common import ServiceError, audit, invoice_to_record
from .gstr3b import Gstr3bService
from .reconciliation import ReconciliationService, months_between

ACTIONS = ("CLAIM", "REVERSE", "RECLAIM")
DECISIONS = ("CONFIRMED", "DISMISSED")


@dataclass
class ClaimResult:
    claimed: list[int]
    skipped: list[tuple[int, str]]


class ItcService:
    def __init__(self, db: Database):
        self.db = db
        self.recon = ReconciliationService(db)
        self.gstr3b = Gstr3bService(db)

    # ----------------------------------------------------------------- rules
    def rules(self, client_id: int | None = None) -> list[Rule]:
        with self.db.session() as s:
            glob = [json.loads(r.definition_json) for r in s.scalars(
                select(ItcRuleRow).where(ItcRuleRow.client_id.is_(None)))]
            cli = [json.loads(r.definition_json) for r in s.scalars(
                select(ItcRuleRow).where(ItcRuleRow.client_id == client_id))] if client_id else []
        return resolve(glob, cli)

    def save_rule(self, rule: Rule, client_id: int | None = None, user: str | None = None) -> None:
        if rule.kind not in ("keyword", "gstin", "builtin", "period"):
            raise ServiceError(f"Unknown rule kind '{rule.kind}'")
        if rule.code not in DEFAULTS_BY_CODE and not rule.code.startswith("CUSTOM_"):
            raise ServiceError("New rules must have a code starting with CUSTOM_")
        if rule.kind == "builtin" and rule.code not in DEFAULTS_BY_CODE:
            raise ServiceError("Built-in rules cannot be created, only configured")
        if rule.severity not in ("high", "medium", "info"):
            raise ServiceError("Severity must be high, medium or info")
        with self.db.session() as s:
            row = s.scalar(select(ItcRuleRow).where(ItcRuleRow.code == rule.code,
                                                    ItcRuleRow.client_id.is_(None) if client_id is None
                                                    else ItcRuleRow.client_id == client_id))
            before = json.loads(row.definition_json) if row else None
            if row is None:
                row = ItcRuleRow(code=rule.code, client_id=client_id)
                s.add(row)
            row.definition_json = json.dumps(rule.to_dict())
            row.updated_by = user or ""
            audit(s, "SAVE", "itc_rule", rule.code, {"client_id": client_id, "before": before,
                                                     "after": rule.to_dict()}, user, client_id)

    def reset_rule(self, code: str, client_id: int | None = None, user: str | None = None) -> None:
        with self.db.session() as s:
            row = s.scalar(select(ItcRuleRow).where(ItcRuleRow.code == code,
                                                    ItcRuleRow.client_id.is_(None) if client_id is None
                                                    else ItcRuleRow.client_id == client_id))
            if row is not None:
                audit(s, "RESET", "itc_rule", code, {"client_id": client_id,
                                                     "before": json.loads(row.definition_json)}, user, client_id)
                s.delete(row)

    # ---------------------------------------------------------------- claims
    def claim_states(self, client_id: int, invoice_ids=None) -> dict[int, ClaimState]:
        out: dict[int, ClaimState] = defaultdict(ClaimState)
        with self.db.session() as s:
            q = select(ItcClaim).where(ItcClaim.client_id == client_id)
            if invoice_ids is not None:
                q = q.where(ItcClaim.invoice_id.in_(list(invoice_ids)))
            for c in s.scalars(q.order_by(ItcClaim.id)):
                st = out[c.invoice_id]
                total = c.igst + c.cgst + c.sgst + c.cess
                if c.action == "CLAIM":
                    st.claimed += total
                elif c.action == "REVERSE":
                    st.reversed += total
                else:
                    st.reclaimed += total
                st.periods.append(f"{c.action.lower()} {c.period}")
        return dict(out)

    def _component_state(self, s, invoice_id: int) -> dict[str, dict[str, Decimal]]:
        state = {a: {k: ZERO for k in ("igst", "cgst", "sgst", "cess")} for a in ACTIONS}
        for c in s.scalars(select(ItcClaim).where(ItcClaim.invoice_id == invoice_id)):
            for k in ("igst", "cgst", "sgst", "cess"):
                state[c.action][k] += getattr(c, k)
        return state

    def _books_doc(self, s, client_id: int, invoice_id: int) -> Invoice:
        inv = s.get(Invoice, invoice_id)
        if inv is None or inv.client_id != client_id:
            raise ServiceError(f"Document {invoice_id} not found for this client")
        if inv.source_type != Source.BOOKS.value:
            raise ServiceError("Only purchase-register (books) documents can be claimed")
        return inv

    def claim(self, client_id: int, invoice_ids: list[int], period: str, user: str | None = None,
              run_id: int | None = None, reason: str = "") -> ClaimResult:
        """Record ITC as claimed in a GSTR-3B period. A document is claimed once only – a second
        claim in any period is refused, which prevents double counting across periods."""
        p = parse_period(period)
        if not p:
            raise ServiceError(f"Invalid claim period '{period}'")
        result = ClaimResult([], [])
        with self.db.session() as s:
            for inv_id in invoice_ids:
                inv = self._books_doc(s, client_id, inv_id)
                prior = s.scalar(select(ItcClaim).where(ItcClaim.invoice_id == inv_id, ItcClaim.action == "CLAIM"))
                if prior is not None:
                    result.skipped.append((inv_id, f"already claimed in {prior.period}"))
                    continue
                s.add(ItcClaim(client_id=client_id, invoice_id=inv_id, period=p, action="CLAIM", igst=inv.igst,
                               cgst=inv.cgst, sgst=inv.sgst, cess=inv.cess, reason=reason, run_id=run_id,
                               user=user or ""))
                result.claimed.append(inv_id)
            audit(s, "CLAIM", "itc_claims", p, {"claimed": result.claimed, "skipped": result.skipped,
                                                "run_id": run_id}, user, client_id)
        return result

    def _adjust(self, action: str, client_id: int, invoice_id: int, period: str, user: str | None, reason: str,
                rule_ref: str, amounts: Gstr3bValues | None) -> None:
        p = parse_period(period)
        if not p:
            raise ServiceError(f"Invalid period '{period}'")
        if not reason.strip():
            raise ServiceError("A reason is required for reversals and reclaims")
        with self.db.session() as s:
            inv = self._books_doc(s, client_id, invoice_id)
            st = self._component_state(s, invoice_id)
            if action == "REVERSE":
                limit = {k: st["CLAIM"][k] - st["REVERSE"][k] + st["RECLAIM"][k] for k in st["CLAIM"]}
                what = "net ITC claimed"
            else:
                limit = {k: st["REVERSE"][k] - st["RECLAIM"][k] for k in st["CLAIM"]}
                what = "ITC reversed and not yet reclaimed"
            amounts = amounts or Gstr3bValues(limit["igst"], limit["cgst"], limit["sgst"], limit["cess"])
            for k in ("igst", "cgst", "sgst", "cess"):
                v = getattr(amounts, k)
                if v < 0 or v > limit[k]:
                    raise ServiceError(f"{action.title()} of {k.upper()} {v} exceeds the {what} ({limit[k]})")
            if amounts.total == 0:
                raise ServiceError(f"Nothing to {action.lower()} – {what} is zero")
            s.add(ItcClaim(client_id=client_id, invoice_id=invoice_id, period=p, action=action, igst=amounts.igst,
                           cgst=amounts.cgst, sgst=amounts.sgst, cess=amounts.cess, reason=reason,
                           rule_ref=rule_ref, user=user or ""))
            audit(s, action, "itc_claims", invoice_id, {"period": p, "invoice": inv.invoice_no, "reason": reason,
                                                        "rule_ref": rule_ref, "total": str(amounts.total)},
                  user, client_id)

    def reverse(self, client_id: int, invoice_id: int, period: str, user: str | None = None, reason: str = "",
                rule_ref: str = "", amounts: Gstr3bValues | None = None) -> None:
        self._adjust("REVERSE", client_id, invoice_id, period, user, reason, rule_ref, amounts)

    def reclaim(self, client_id: int, invoice_id: int, period: str, user: str | None = None, reason: str = "",
                amounts: Gstr3bValues | None = None) -> None:
        self._adjust("RECLAIM", client_id, invoice_id, period, user, reason, "", amounts)

    def claim_eligible_from_run(self, run_id: int, period: str, user: str | None = None,
                                as_of: date | None = None) -> ClaimResult:
        """Claim every books document of a run that is confirmed by GSTR-2B and carries no open
        high/medium flag. Flagged documents are left for the reviewer."""
        reviews, _ = self.review_run(run_id, as_of)
        ctx = self.recon.load(run_id)
        paired = {ln.books.db_id for ln in ctx.result.lines if ln.books and ln.gstr2b
                  and ln.category in PAIRED_CATEGORIES}
        ids, skipped = [], []
        for rv in reviews:
            doc = rv.record
            if doc.source != Source.BOOKS or not doc.db_id:
                continue
            if doc.db_id not in paired:
                skipped.append((doc.db_id, "not confirmed by GSTR-2B"))
            elif rv.worst in ("high", "medium"):
                skipped.append((doc.db_id, "open review flag: " + ", ".join(h.code for h in rv.open_hits)))
            elif rv.claim.is_claimed:
                skipped.append((doc.db_id, "already claimed"))
            else:
                ids.append(doc.db_id)
        result = self.claim(ctx.client.id, ids, period, user, run_id, "Matched with GSTR-2B, no open flags")
        result.skipped = skipped + result.skipped
        return result

    def claim_register(self, client_id: int, periods: list[str] | None = None) -> list[tuple[ItcClaim, Invoice]]:
        with self.db.session() as s:
            q = select(ItcClaim, Invoice).join(Invoice, Invoice.id == ItcClaim.invoice_id).where(
                ItcClaim.client_id == client_id)
            if periods:
                q = q.where(ItcClaim.period.in_(periods))
            return list(s.execute(q.order_by(ItcClaim.period, ItcClaim.id)).all())

    # --------------------------------------------------------------- reviews
    def set_review(self, client_id: int, invoice_id: int, rule_code: str, decision: str, remarks: str = "",
                   user: str | None = None) -> None:
        if decision not in DECISIONS:
            raise ServiceError(f"Decision must be one of {', '.join(DECISIONS)}")
        if decision == "DISMISSED" and not remarks.strip():
            raise ServiceError("Give the reason for dismissing a flag")
        with self.db.session() as s:
            row = s.scalar(select(ItcReview).where(ItcReview.invoice_id == invoice_id,
                                                   ItcReview.rule_code == rule_code))
            before = (row.decision, row.remarks) if row else None
            if row is None:
                row = ItcReview(client_id=client_id, invoice_id=invoice_id, rule_code=rule_code)
                s.add(row)
            row.decision, row.remarks, row.user = decision, remarks, user or ""
            audit(s, "ITC_REVIEW", "invoice", invoice_id, {"rule": rule_code, "before": before,
                                                           "after": [decision, remarks]}, user, client_id)

    def decisions(self, client_id: int) -> dict[tuple[int, str], tuple[str, str]]:
        with self.db.session() as s:
            return {(r.invoice_id, r.rule_code): (r.decision, r.remarks)
                    for r in s.scalars(select(ItcReview).where(ItcReview.client_id == client_id))}

    # ------------------------------------------------------------------- IMS
    def _docs(self, s, client_id: int, source: Source, periods=None, upto: str | None = None):
        it = Invoice.__table__
        q = select(it).where(it.c.client_id == client_id, it.c.source_type == source.value)
        if periods is not None:
            q = q.where(it.c.period.in_(list(periods)))
        if upto is not None:
            q = q.where(it.c.period <= upto)
        names = {f.id: f.file_name for f in s.scalars(select(SourceFile).where(SourceFile.client_id == client_id))}
        return [invoice_to_record(r, names.get(r.source_file_id, "")) for r in s.execute(q)]

    def ims_compare(self, client_id: int, periods: list[str]) -> tuple[list[ImsRow], list[str]]:
        with self.db.session() as s:
            ims = self._docs(s, client_id, Source.IMS, periods)
            if not ims:  # nothing to compare: do not load every purchase document
                return [], [f"No IMS data imported for {', '.join(periods)}"]
            books = self._docs(s, client_id, Source.BOOKS, upto=max(periods))
            g2b = self._docs(s, client_id, Source.GSTR2B, periods)
        return compare_ims(ims, books, g2b, period=min(periods))

    # --------------------------------------------------------------- review
    def review_run(self, run_id: int, as_of: date | None = None, ctx=None) -> tuple[list[DocReview], dict]:
        """Review a run's documents; ``ctx`` is the already loaded run (saves loading it again)."""
        ctx = ctx if ctx is not None and ctx.run.id == run_id else self.recon.load(run_id)
        if not ctx.run.comparison.startswith("BOOKS"):
            return [], {}  # outward runs carry no input tax credit
        cid = ctx.client.id
        periods = months_between(ctx.run.period_from, ctx.run.period_to)
        ims_rows, _ = self.ims_compare(cid, periods)
        lines = ctx.result.lines
        ids = [r.db_id for ln in lines for r in (ln.books,) if r is not None and r.db_id]
        reviews = review_lines(lines, self.rules(cid), as_of or date.today(), self.claim_states(cid, ids),
                               self.decisions(cid), ims_actions_for_books(ims_rows))
        filed = self.gstr3b.values(cid, periods)
        itc_3b = None
        if filed:
            itc_3b = sum((t.get(c, Gstr3bValues()).total for t in filed.values()
                          for c in ("4A1", "4A2", "4A3", "4A4", "4A5")), ZERO)
        isd, imports = self._other_totals(cid, periods)
        return reviews, buckets(reviews, lines, itc_3b, isd, imports)

    def _other(self, client_id: int, periods: list[str]) -> list[dict]:
        with self.db.session() as s:
            return [{"section": o.section, "doc_type": o.doc_type, "igst": o.igst, "cgst": o.cgst, "sgst": o.sgst,
                     "cess": o.cess, "itc_availability": o.itc_availability or "Y", "period": o.period,
                     "doc_no": o.doc_no, "party": o.party, "doc_date": o.doc_date}
                    for o in s.scalars(select(OtherItc).where(OtherItc.client_id == client_id,
                                                              OtherItc.period.in_(periods)))]

    def _other_totals(self, client_id: int, periods: list[str]) -> tuple[Decimal, Decimal]:
        isd = imports = ZERO
        for o in self._other(client_id, periods):
            sign = -1 if str(o["doc_type"]).upper().endswith("C") else 1
            total = (o["igst"] + o["cgst"] + o["sgst"] + o["cess"]) * sign
            if o["section"] in ("IMPG", "IMPGSEZ"):
                imports += total
            else:
                isd += total
        return isd, imports

    # --------------------------------------------------------------- table 4
    def _latest_month_runs(self, s, client_id: int, months: list[str]) -> dict[str, int]:
        runs = s.scalars(select(ReconRun).where(ReconRun.client_id == client_id,
                                                ReconRun.period_from == ReconRun.period_to,
                                                ReconRun.comparison == "BOOKS_VS_GSTR2B",  # not 2A / 8A runs
                                                ReconRun.period_from.in_(months)).order_by(ReconRun.id)).all()
        return {r.period_from: r.id for r in runs}

    def _claim_actions(self, client_id: int, periods: list[str]) -> list[tuple[str, ClaimAction]]:
        out = []
        for c, inv in self.claim_register(client_id, periods):
            out.append((c.period, ClaimAction(invoice_to_record(inv), c.action,
                                              Gstr3bValues(c.igst, c.cgst, c.sgst, c.cess), c.rule_ref)))
        return out

    def table4(self, client_id: int, periods: list[str], as_of: date | None = None,
               loaded=None) -> list[PeriodWorking]:
        """``loaded`` is a run already in memory (the desktop's current run): it is not loaded again."""
        with self.db.session() as s:
            run_for = self._latest_month_runs(s, client_id, periods)
            g2b = self._docs(s, client_id, Source.GSTR2B, periods)
        filed = self.gstr3b.values(client_id, periods)
        actions = self._claim_actions(client_id, periods)
        other = self._other(client_id, periods)
        rules = self.rules(client_id)
        out = []
        for p in periods:
            lines, reviews = [], []
            if p in run_for:
                ctx = loaded if loaded is not None and loaded.run.id == run_for[p] else self.recon.load(run_for[p])
                lines = ctx.result.lines
                reviews, _ = self.review_run(run_for[p], as_of, ctx)
            out.append(build_period(
                p, [r for r in g2b if r.period == p], [o for o in other if o["period"] == p], filed.get(p),
                [ca for per, ca in actions if per == p], lines, reviews, rules))
        return out

    # ---------------------------------------------------------------- annual
    def annual(self, client_id: int, fy: str, cutoff: str | None = None,
               portal_8a: Decimal | None = None) -> Table8:
        cutoff = parse_period(cutoff) if cutoff else default_cutoff(fy)
        months = fy_months(fy)
        span = months_between(months[0], cutoff)
        with self.db.session() as s:
            g2b = self._docs(s, client_id, Source.GSTR2B, span)
            books = [r for r in self._docs(s, client_id, Source.BOOKS) if r.period in span or r.period in months]
            portal = self._docs(s, client_id, Source.GSTR8A, months)
        filed = self.gstr3b.values(client_id, months)
        claims = self._claim_actions(client_id, span)
        return gstr9_table8(fy, g2b, books, filed, claims, cutoff, portal_8a, portal or None)

    def doc_type_of(self, invoice_id: int) -> DocType:
        with self.db.session() as s:
            return DocType(s.get(Invoice, invoice_id).doc_type)
