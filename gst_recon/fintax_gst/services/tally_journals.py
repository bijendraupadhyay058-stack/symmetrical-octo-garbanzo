"""ITC reversal / re-claim journals for TallyPrime, from the ITC claim register or the 180-day rule."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from ..compliance.tally_journals import DEFAULT_LEDGERS, HEADS, JournalEntry, entry, month_end, to_tally_xml
from ..core.money import q2
from ..db.database import Database
from ..db.models import AppSetting
from ..importers.parsing import parse_period
from .common import ServiceError, audit

SOURCES = {"claims": "ITC claim register (reversals and re-claims of the month)",
           "rule37": "180-day rule (bills to reverse or re-claim in the month)"}


def _key(client_id: int) -> str:
    return f"tally_ledgers:{client_id}"


class TallyJournalService:
    def __init__(self, db: Database):
        self.db = db

    def ledgers(self, client_id: int) -> dict[str, str]:
        with self.db.session() as s:
            row = s.get(AppSetting, _key(client_id))
            saved = json.loads(row.value_json) if row else {}
        return {**DEFAULT_LEDGERS, **{k: v for k, v in saved.items() if k in DEFAULT_LEDGERS and v}}

    def set_ledgers(self, client_id: int, ledgers: dict[str, str], user: str | None = None) -> None:
        clean = {k: v.strip()[:100] for k, v in ledgers.items() if k in DEFAULT_LEDGERS and v and v.strip()}
        with self.db.session() as s:
            row = s.get(AppSetting, _key(client_id))
            if row is None:
                row = AppSetting(key=_key(client_id), value_json="{}")
                s.add(row)
            row.value_json = json.dumps(clean)
            audit(s, "SETTING", "app_settings", _key(client_id), {"after": clean}, user, client_id)

    def entries(self, client_id: int, period: str, source: str = "claims",
                ledgers: dict[str, str] | None = None) -> list[JournalEntry]:
        """The month's journals; ``ledgers`` (e.g. names being edited) override the saved ledger names."""
        p = parse_period(period)
        if not p:
            raise ServiceError(f"Invalid period {period} – use YYYY-MM")
        if source not in SOURCES:
            raise ServiceError(f"Unknown source {source}")
        led = {**self.ledgers(client_id), **{k: v for k, v in (ledgers or {}).items() if k in DEFAULT_LEDGERS and v}}
        on = month_end(p)
        out: list[JournalEntry] = []
        if source == "claims":
            from .itc import ItcService

            for c, inv in ItcService(self.db).claim_register(client_id, [p]):
                if c.action not in ("REVERSE", "RECLAIM"):
                    continue
                verb = "ITC reversed" if c.action == "REVERSE" else "ITC re-claimed"
                why = f" – {c.reason}" if c.reason else ""
                rule = f" ({c.rule_ref})" if c.rule_ref else ""
                e = entry(c.action, on, {h: getattr(c, h) for h in HEADS}, led,
                          f"{verb}{why}{rule}: {inv.supplier_name or inv.supplier_gstin} invoice {inv.invoice_no} "
                          f"dated {inv.invoice_date:%d-%m-%Y}", inv.invoice_no)
                if e:
                    out.append(e)
        else:
            from .rule37 import Rule37Service

            for b in Rule37Service(self.db).track(client_id, as_of=on):
                if b.reversal_period == p and b.itc_to_reverse > 0:
                    e = entry("REVERSE", on, b.share(b.unpaid_at_day180), led,
                              f"ITC reversed – Rule 37, not paid within 180 days (unpaid Rs. {b.unpaid_at_day180}): "
                              f"{b.supplier} invoice {b.invoice_no} dated {b.invoice_date:%d-%m-%Y}", b.invoice_no)
                    if e:
                        out.append(e)
                if b.reclaim_period == p and b.itc_to_reclaim > 0:
                    f = b.itc_to_reclaim / b.itc if b.itc else Decimal(0)
                    e = entry("RECLAIM", on, {h: q2(getattr(b, h) * f) for h in HEADS}, led,
                              f"ITC re-claimed – Rule 37, paid on {b.paid_in_full_on or on:%d-%m-%Y}: {b.supplier} "
                              f"invoice {b.invoice_no} dated {b.invoice_date:%d-%m-%Y}", b.invoice_no)
                    if e:
                        out.append(e)
        return out

    def save_xml(self, client_id: int, entries: list[JournalEntry], path: str | Path, company: str = "",
                 user: str | None = None) -> Path:
        if not entries:
            raise ServiceError("No journal entries for this month")
        out = Path(path)
        out.write_bytes(to_tally_xml(entries, company))
        with self.db.session() as s:
            audit(s, "EXPORT", "tally_journals", out.name, {"entries": len(entries),
                                                           "total": str(sum(e.total for e in entries))},
                  user, client_id)
        return out
