"""e-Invoice and e-way bill bulk files of a month, and the party address book they need."""
from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from ..core.gstin import normalize_gstin, validate_gstin
from ..db.database import Database
from ..db.models import AppSetting, Client, PartyAddress
from ..importers.payments import party_key
from ..importers.readers import UnsupportedFileError, read_csv, read_excel
from ..outward.einvoice_ewb import PIN, BulkFile, Party, Transport, build_einvoices, build_ewaybills
from .common import ServiceError, audit

HEADERS = {"name": ("name", "party", "party name", "ledger", "ledger name", "particulars", "customer", "customer name",
                    "legal name", "trade name"),
           "gstin": ("gstin/uin", "gstin", "gst no", "gstin of party"),
           "address": ("address", "address 1", "address line 1", "addr1", "billing address", "mailing address"),
           "place": ("place", "city", "town", "location", "district"),
           "pin": ("pincode", "pin code", "pin", "postal code", "zip"),
           "state": ("state", "state name", "state code"),
           "distance": ("distance", "distance km", "distance (km)", "km")}


def _norm(c) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9/ ()]", " ", str(c or "").lower())).strip()


def _state_code(text: str) -> str:
    from ..compliance.tax_checks import pos_code

    return pos_code(text) or ""


class EInvoiceFileService:
    def __init__(self, db: Database):
        self.db = db

    # -------------------------------------------------------- party book
    def parties(self, client_id: int) -> dict[str, Party]:
        with self.db.session() as s:
            rows = list(s.scalars(select(PartyAddress).where(PartyAddress.client_id == client_id)))
        return {r.party_key: Party(r.name, r.address, r.place, r.pin, r.state_code, r.gstin, r.distance_km)
                for r in rows}

    def party_rows(self, client_id: int) -> list[PartyAddress]:
        with self.db.session() as s:
            return list(s.scalars(select(PartyAddress).where(PartyAddress.client_id == client_id)
                                  .order_by(PartyAddress.name)))

    def save_party(self, client_id: int, name: str, address: str, place: str, pin: str, gstin: str = "",
                   state_code: str = "", distance_km: int = 0, user: str | None = None) -> str:
        g = normalize_gstin(gstin)
        if g and not validate_gstin(g)[0]:
            raise ServiceError(f"GSTIN {g} is not valid")
        pin = re.sub(r"\D", "", str(pin or ""))[:6]
        if pin and not PIN.fullmatch(pin):
            raise ServiceError("PIN code must have 6 digits")
        key = g or party_key(name)
        if not key:
            raise ServiceError("Enter the party's GSTIN or name")
        state = state_code or (g[:2] if g else "")
        with self.db.session() as s:
            row = s.scalar(select(PartyAddress).where(PartyAddress.client_id == client_id,
                                                      PartyAddress.party_key == key))
            if row is None:
                row = PartyAddress(client_id=client_id, party_key=key)
                s.add(row)
            row.gstin, row.name, row.address, row.place = g, name.strip()[:200], address.strip()[:200], \
                place.strip()[:100]
            row.pin, row.state_code, row.distance_km = pin, state[:2], int(distance_km or 0)
        return key

    def import_parties(self, client_id: int, path: str | Path, user: str | None = None) -> tuple[int, list[str]]:
        """Party list (e.g. Tally 'List of Ledgers' exported to Excel): name, GSTIN, address, place, PIN, state."""
        path = Path(path)
        tables = [read_csv(path, path.name)] if path.suffix.lower() == ".csv" else read_excel(path)
        saved, problems = 0, []
        for t in tables:
            cols = None
            for n, cells in t.rows:
                if cols is None:
                    names = [_norm(c) for c in cells]
                    found = {f: names.index(o) for f, opts in HEADERS.items() for o in opts if o in names}
                    if "name" in found and ("pin" in found or "address" in found):
                        cols = found
                    continue
                get = {k: (cells[i] if i < len(cells) else None) for k, i in cols.items()}
                name = str(get.get("name") or "").strip()
                if not name:
                    continue
                state = str(get.get("state") or "")
                try:
                    self.save_party(client_id, name, str(get.get("address") or ""), str(get.get("place") or ""),
                                    str(get.get("pin") or ""), str(get.get("gstin") or ""),
                                    _state_code(state) if state else "",
                                    int(float(get.get("distance") or 0)) if str(get.get("distance") or "0").replace(
                                        ".", "", 1).isdigit() else 0, user)
                    saved += 1
                except ServiceError as exc:
                    problems.append(f"row {n} ({name}): {exc}")
        if not saved and not problems:
            raise UnsupportedFileError(f"{path.name}: no party list found – it needs columns for the name and the "
                                       "address or PIN code")
        with self.db.session() as s:
            audit(s, "IMPORT", "party_addresses", path.name, {"saved": saved, "problems": len(problems)}, user,
                  client_id)
        return saved, problems

    # ------------------------------------------------------------- seller
    def seller(self, client_id: int) -> Party:
        with self.db.session() as s:
            client = s.get(Client, client_id)
            if client is None:
                raise ServiceError(f"Client {client_id} not found")
            saved = s.get(AppSetting, f"einv_seller:{client_id}")
            override = json.loads(saved.value_json) if saved else {}
            address = (client.address or "").replace("\n", ", ")
            pin = PIN.search(address)
            place = ""
            if pin:  # 'Shop 12, Market Yard, Pune 411037' -> place 'Pune'
                before = address[:pin.start()].rstrip(" ,-")
                place = before.split(",")[-1].strip()
            party = Party(client.name, address, place, pin.group(1) if pin else "", client.state_code, client.gstin)
        for k, v in override.items():
            if v:
                setattr(party, k, v)
        return party

    def save_seller(self, client_id: int, address: str, place: str, pin: str, user: str | None = None) -> None:
        pin = re.sub(r"\D", "", pin)[:6]
        if pin and not PIN.fullmatch(pin):
            raise ServiceError("PIN code must have 6 digits")
        with self.db.session() as s:
            row = s.get(AppSetting, f"einv_seller:{client_id}")
            if row is None:
                row = AppSetting(key=f"einv_seller:{client_id}", value_json="{}")
                s.add(row)
            row.value_json = json.dumps({"address": address.strip(), "place": place.strip(), "pin": pin})
            audit(s, "SETTING", "app_settings", f"einv_seller:{client_id}", {"place": place, "pin": pin}, user,
                  client_id)

    # -------------------------------------------------------------- files
    def _docs(self, client_id: int, period: str):
        from .gstr1_prep import Gstr1PrepService

        docs, gstin, _state = Gstr1PrepService(self.db).docs(client_id, period)
        return docs, gstin

    def einvoices(self, client_id: int, period: str) -> BulkFile:
        docs, gstin = self._docs(client_id, period)
        return build_einvoices(gstin, self.seller(client_id), docs, self.parties(client_id))

    def ewaybills(self, client_id: int, period: str, transport: Transport | None = None) -> BulkFile:
        from .security import SecurityService

        docs, gstin = self._docs(client_id, period)
        threshold = Decimal(str(SecurityService(self.db).setting("ewb_threshold") or 50000))
        return build_ewaybills(gstin, self.seller(client_id), docs, self.parties(client_id), transport or Transport(),
                               threshold)

    def save(self, client_id: int, kind: str, bulk: BulkFile, path: str | Path, user: str | None = None) -> Path:
        if not bulk.count:
            raise ServiceError("No document to put in the file")
        out = Path(path)
        out.write_text(json.dumps(bulk.payload, indent=1, ensure_ascii=False), encoding="utf-8")
        with self.db.session() as s:
            audit(s, "EXPORT", kind, out.name, {"documents": bulk.count,
                                               "left_out": sum(1 for i in bulk.issues if i.severity == "error")},
                  user, client_id)
        return out
