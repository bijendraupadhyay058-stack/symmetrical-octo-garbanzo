"""Client master. Each GSTIN is a separate client; several GSTINs may share a PAN."""
from __future__ import annotations

import re

from sqlalchemy import select

from ..core.gstin import STATE_CODES, normalize_gstin, pan_of, validate_gstin
from ..db.database import Database
from ..db.models import Client
from .common import ServiceError, audit

FIELDS = ("name", "trade_name", "address", "financial_year", "registration_type", "return_frequency",
          "contact_person", "email", "mobile")
_FY = re.compile(r"^\d{4}-\d{2}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ClientService:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _validate(data: dict) -> None:
        if not (data.get("name") or "").strip():
            raise ServiceError("Client name is required")
        fy = data.get("financial_year")
        if fy and (not _FY.match(fy) or int(fy[5:]) != (int(fy[:4]) + 1) % 100):
            raise ServiceError(f"Financial year must look like 2025-26 (got '{fy}')")
        if data.get("return_frequency") and data["return_frequency"] not in ("Monthly", "Quarterly"):
            raise ServiceError("Return frequency must be Monthly or Quarterly")
        if data.get("email") and not _EMAIL.match(data["email"]):
            raise ServiceError(f"Invalid email '{data['email']}'")
        if data.get("mobile") and not re.fullmatch(r"\+?\d{10,13}", data["mobile"]):
            raise ServiceError(f"Invalid mobile number '{data['mobile']}'")

    def create(self, gstin: str, user: str | None = None, **data) -> Client:
        gstin = normalize_gstin(gstin)
        ok, problem = validate_gstin(gstin)
        if not ok or problem:
            raise ServiceError(f"Invalid client GSTIN {gstin}: {problem}")
        self._validate(data)
        with self.db.session() as s:
            if s.scalar(select(Client).where(Client.gstin == gstin)):
                raise ServiceError(f"A client with GSTIN {gstin} already exists")
            client = Client(gstin=gstin, pan=pan_of(gstin), state_code=gstin[:2],
                            state=STATE_CODES.get(gstin[:2], ""),
                            **{k: (data.get(k) or "") for k in FIELDS})
            client.registration_type = client.registration_type or "Regular"
            client.return_frequency = client.return_frequency or "Monthly"
            s.add(client)
            s.flush()
            audit(s, "CREATE", "client", client.id, {"gstin": gstin, **data}, user, client.id)
        return client

    def update(self, client_id: int, user: str | None = None, **changes) -> Client:
        unknown = set(changes) - set(FIELDS)
        if unknown:
            raise ServiceError(f"Cannot update field(s): {', '.join(sorted(unknown))}")
        with self.db.session() as s:
            client = s.get(Client, client_id)
            if client is None:
                raise ServiceError(f"Client {client_id} not found")
            merged = {k: getattr(client, k) for k in FIELDS} | changes
            self._validate(merged)
            before = {k: getattr(client, k) for k in changes}
            for k, v in changes.items():
                setattr(client, k, v)
            audit(s, "UPDATE", "client", client_id, {"before": before, "after": changes}, user, client_id)
        return client

    def get(self, client_id: int) -> Client:
        with self.db.session() as s:
            client = s.get(Client, client_id)
        if client is None:
            raise ServiceError(f"Client {client_id} not found")
        return client

    def by_gstin(self, gstin: str) -> Client:
        gstin = normalize_gstin(gstin)
        with self.db.session() as s:
            client = s.scalar(select(Client).where(Client.gstin == gstin))
        if client is None:
            raise ServiceError(f"No client with GSTIN {gstin}")
        return client

    def resolve(self, ref: str | int) -> Client:
        if isinstance(ref, int) or str(ref).isdigit():
            return self.get(int(ref))
        return self.by_gstin(str(ref))

    def list(self, pan: str | None = None, include_inactive: bool = False) -> list[Client]:
        with self.db.session() as s:
            q = select(Client).order_by(Client.name, Client.gstin)
            if pan:
                q = q.where(Client.pan == pan.upper())
            if not include_inactive:
                q = q.where(Client.active.is_(True))
            return list(s.scalars(q))
