"""Fetch vouchers straight from TallyPrime and keep each response as an imported file (see importers/tally_xml.py)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from ..db.database import Database
from ..importers.parsing import parse_period
from ..importers.tally_xml import DEFAULT_URL, TallyClient
from .common import ServiceError, audit
from .reconciliation import months_between


def month_range(p_from: str, p_to: str | None = None) -> tuple[date, date]:
    import calendar

    a, b = parse_period(p_from), parse_period(p_to or p_from)
    if not a or not b or b < a:
        raise ServiceError(f"Invalid period range {p_from} – {p_to}")
    last = calendar.monthrange(int(b[:4]), int(b[5:]))[1]
    return date(int(a[:4]), int(a[5:]), 1), date(int(b[:4]), int(b[5:]), last)


class TallyService:
    def __init__(self, db: Database):
        self.db = db

    def url(self) -> str:
        from .security import SecurityService

        return SecurityService(self.db).setting("tally_url") or DEFAULT_URL

    def companies(self, url: str | None = None) -> list[str]:
        return TallyClient(url or self.url()).companies()

    def fetch(self, client_id: int, company: str, p_from: str, p_to: str | None = None, url: str | None = None,
              user: str | None = None) -> Path:
        """Fetch the company's vouchers for the months and save them as an XML file to import."""
        from .clients import ClientService

        client = ClientService(self.db).get(client_id)
        start, end = month_range(p_from, p_to)
        data = TallyClient(url or self.url()).fetch(company, start, end)
        folder = self.db.data_dir / "tally"
        folder.mkdir(parents=True, exist_ok=True)
        from ..db.models import utcnow

        months = months_between(f"{start:%Y-%m}", f"{end:%Y-%m}")
        path = folder / f"{client.gstin}_{months[0]}_{months[-1]}_{utcnow():%Y%m%d%H%M%S}.xml"
        path.write_bytes(data)
        with self.db.session() as s:
            audit(s, "TALLY_FETCH", "tally", company[:60], {"file": str(path), "from": months[0], "to": months[-1],
                                                            "bytes": len(data)}, user, client_id)
        return path
