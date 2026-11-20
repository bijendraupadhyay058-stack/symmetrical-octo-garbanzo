"""Tax audit helpers: Form 3CD clause 44 break-up of expenditure, and a books-vs-returns check for the year.

Clause 44 (break-up of total expenditure of entities registered or not registered under GST):
* registered suppliers – from the purchase register (taxable value): goods / services exempt from GST (no tax
  charged), suppliers under the composition scheme (marked by the user; suppliers whose every bill is without tax
  are suggested), and other registered suppliers;
* unregistered suppliers – the reverse-charge register of purchases from persons without GSTIN;
* the rest of the total expenditure in the accounts (entered from the profit and loss account and fixed asset
  additions) is not in any register and is shown separately, to be classified by the auditor.
Expenditure in the registers is taken at taxable value (without GST).

Books check: month by month, output tax in the sales register vs GSTR-3B, and ITC in the purchase register vs
GSTR-2B vs GSTR-3B, with the differences.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from ..core.models import DocType, Source
from ..core.money import ZERO
from ..db.database import Database
from ..db.models import AppSetting, RcmEntry
from ..itc.annual import fy_months
from .common import ServiceError, audit


@dataclass
class SupplierSpend:
    gstin: str
    name: str
    taxable: Decimal = ZERO
    taxed: Decimal = ZERO  # part of it on which GST was charged
    untaxed: Decimal = ZERO
    bills: int = 0
    category: str = ""  # Composition / Exempt / Registered (mixed) / Registered


@dataclass
class Clause44:
    fy: str
    total_expenditure: Decimal | None
    exempt: Decimal = ZERO
    composition: Decimal = ZERO
    other_registered: Decimal = ZERO
    unregistered: Decimal = ZERO
    suppliers: list[SupplierSpend] = field(default_factory=list)
    suggested_composition: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def registered_total(self) -> Decimal:
        return self.exempt + self.composition + self.other_registered

    @property
    def in_registers(self) -> Decimal:
        return self.registered_total + self.unregistered

    @property
    def not_in_registers(self) -> Decimal | None:
        return None if self.total_expenditure is None else self.total_expenditure - self.in_registers


class TaxAuditService:
    def __init__(self, db: Database):
        self.db = db

    def _key(self, client_id: int, fy: str) -> str:
        return f"clause44:{client_id}:{fy}"

    def settings(self, client_id: int, fy: str) -> dict:
        with self.db.session() as s:
            row = s.get(AppSetting, self._key(client_id, fy))
            return json.loads(row.value_json) if row else {}

    def save_settings(self, client_id: int, fy: str, total_expenditure=None, composition: list[str] | None = None,
                      user: str | None = None) -> None:
        cur = self.settings(client_id, fy)
        if total_expenditure is not None:
            try:
                cur["total_expenditure"] = str(Decimal(str(total_expenditure).replace(",", "").strip()))
            except Exception:  # noqa: BLE001 - reported as a plain message
                raise ServiceError(f"'{total_expenditure}' is not an amount") from None
        if composition is not None:
            cur["composition"] = sorted({g.strip().upper() for g in composition if g.strip()})
        with self.db.session() as s:
            row = s.get(AppSetting, self._key(client_id, fy))
            if row is None:
                row = AppSetting(key=self._key(client_id, fy), value_json="{}")
                s.add(row)
            row.value_json = json.dumps(cur)
            audit(s, "SETTING", "app_settings", self._key(client_id, fy), cur, user, client_id)

    def clause44(self, client_id: int, fy: str) -> Clause44:
        from .itc import ItcService

        cfg = self.settings(client_id, fy)
        comp = set(cfg.get("composition", []))
        total = Decimal(cfg["total_expenditure"]) if cfg.get("total_expenditure") else None
        months = fy_months(fy)
        with self.db.session() as s:
            books = ItcService(self.db)._docs(s, client_id, Source.BOOKS, months)
            rcm = list(s.scalars(select(RcmEntry).where(RcmEntry.client_id == client_id, RcmEntry.period.in_(months))))
        out = Clause44(fy, total)
        by: dict[str, SupplierSpend] = {}
        for b in books:
            k = -1 if b.doc_type == DocType.CREDIT_NOTE else 1
            sp = by.setdefault(b.supplier_gstin, SupplierSpend(b.supplier_gstin, b.supplier_name))
            sp.name = sp.name or b.supplier_name
            sp.taxable += k * b.taxable
            sp.bills += 1
            if b.igst + b.cgst + b.sgst + b.cess:
                sp.taxed += k * b.taxable
            else:
                sp.untaxed += k * b.taxable
        for sp in by.values():
            if sp.gstin in comp:
                sp.category = "Composition"
                out.composition += sp.taxable
            else:
                out.exempt += sp.untaxed
                out.other_registered += sp.taxed
                sp.category = "Exempt" if not sp.taxed else ("Registered (part exempt)" if sp.untaxed else "Registered")
                if not sp.taxed and sp.untaxed:
                    out.suggested_composition.append(sp.gstin)
        out.unregistered = sum((e.taxable for e in rcm), ZERO)
        out.suppliers = sorted(by.values(), key=lambda x: -x.taxable)
        if not books:
            out.notes.append("No purchase register for the year – registered expenditure is nil.")
        if out.suggested_composition:
            out.notes.append(f"{len(out.suggested_composition)} supplier(s) never charged GST – if they are under the "
                             "composition scheme, mark them; otherwise their bills are shown as exempt.")
        if total is None:
            out.notes.append("Enter the total expenditure as per the accounts (P&L and capital additions).")
        elif out.not_in_registers and out.not_in_registers < 0:
            out.notes.append("The registers add up to more than the total expenditure entered – check the total.")
        out.notes.append("Unregistered expenditure covers only the RCM register; salaries, depreciation and other "
                         "expenditure not in any register are in 'not in the registers' for the auditor to classify.")
        return out

    def export_xlsx(self, c: Clause44, client_name: str, gstin: str, path: str | Path) -> Path:
        from openpyxl import Workbook
        from openpyxl.styles import Font

        wb = Workbook()
        ws = wb.active
        ws.title = "Clause 44"
        ws.append([f"Form 3CD clause 44 – {client_name} ({gstin}) – FY {c.fy}"])
        ws["A1"].font = Font(bold=True)
        ws.append(["", "Amount (₹)"])
        rows = [("1. Total amount of expenditure incurred during the year", c.total_expenditure),
                ("2. Expenditure in respect of entities registered under GST:", None),
                ("   (a) relating to goods or services exempt from GST", c.exempt),
                ("   (b) relating to entities falling under composition scheme", c.composition),
                ("   (c) relating to other registered entities", c.other_registered),
                ("   (d) total payment to registered entities", c.registered_total),
                ("3. Expenditure relating to entities not registered under GST (RCM register)", c.unregistered),
                ("4. Expenditure not in the registers (to classify)", c.not_in_registers)]
        for label, v in rows:
            ws.append([label, float(v) if v is not None else None])
        for n in c.notes:
            ws.append([n])
        ws.column_dimensions["A"].width = 80
        ws.column_dimensions["B"].width = 18
        d = wb.create_sheet("Suppliers")
        d.append(["GSTIN", "Supplier", "Category", "Bills", "Taxable value", "With GST", "Without GST"])
        for cc in d[1]:
            cc.font = Font(bold=True)
        for sp in c.suppliers:
            d.append([sp.gstin, sp.name, sp.category, sp.bills, float(sp.taxable), float(sp.taxed), float(sp.untaxed)])
        for col, w in zip("ABCDEFG", (18, 34, 22, 8, 16, 16, 16)):
            d.column_dimensions[col].width = w
        path = Path(path)
        wb.save(path)
        return path

    # ------------------------------------------------------------ books check
    def books_check(self, client_id: int, fy: str) -> list[dict]:
        from .compliance import ComplianceService

        cc = ComplianceService(self.db).client_summary(client_id, fy)
        rows = []
        for m in cc.months:
            if not m.has_data:
                continue
            rows.append({"period": m.period, "output_books": m.output_sales, "output_3b": m.output_3b,
                         "output_diff": (m.output_sales - m.output_3b) if m.output_sales is not None
                         and m.output_3b is not None else None,
                         "itc_books": m.itc_books if m.purchase_docs else None,
                         "itc_2b": m.itc_2b if m.gstr2b_docs else None, "itc_3b": m.itc_3b,
                         "itc_diff": (m.itc_3b - m.itc_books) if m.itc_3b is not None and m.purchase_docs else None})
        return rows
