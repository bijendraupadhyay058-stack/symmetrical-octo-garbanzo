"""GSTR-9C reconciliation statement: preparer inputs (audited figures, reasons) and the statement."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from ..core.models import Source
from ..core.money import ZERO
from ..db.database import Database
from ..db.models import Gstr9cInput, Invoice
from ..gstr9.reconciliation_9c import INPUT_ITEMS, REASON_ITEMS, Gstr9cStatement, build_9c
from ..itc.annual import fy_months
from .auth import Session, require
from .common import ServiceError, audit, invoice_to_record
from .gstr9 import Gstr9Service
from .outward import OutwardService


class Gstr9cService:
    def __init__(self, db: Database):
        self.db = db

    def inputs(self, client_id: int, fy: str) -> dict[str, tuple[Decimal | None, str]]:
        with self.db.session() as s:
            return {r.item: (r.amount, r.note or "") for r in s.scalars(select(Gstr9cInput).where(
                Gstr9cInput.client_id == client_id, Gstr9cInput.financial_year == fy))}

    def set_input(self, client_id: int, fy: str, item: str, amount, note: str = "",
                  by: Session | None = None) -> None:
        """Record an audited figure (``amount``) or a reason (``note``); ``amount=None`` and an empty
        note remove the entry, so the default applies again."""
        require(by, "review")
        item = item.upper()
        if item not in INPUT_ITEMS and item not in REASON_ITEMS:
            raise ServiceError(f"Unknown GSTR-9C item '{item}'. Amounts: {', '.join(INPUT_ITEMS)}; "
                               f"reasons: {', '.join(REASON_ITEMS)}")
        if amount is not None and not isinstance(amount, Decimal):
            try:
                amount = Decimal(str(amount).replace(",", "").strip())
            except InvalidOperation:
                raise ServiceError(f"'{amount}' is not an amount") from None
        if item in REASON_ITEMS and amount is not None:
            raise ServiceError(f"{item} holds a reason – give it as a note")
        with self.db.session() as s:
            row = s.scalar(select(Gstr9cInput).where(Gstr9cInput.client_id == client_id,
                                                     Gstr9cInput.financial_year == fy, Gstr9cInput.item == item))
            before = {"amount": row.amount, "note": row.note} if row else None
            if amount is None and not note.strip():
                if row is not None:
                    s.delete(row)
            else:
                if row is None:
                    row = Gstr9cInput(client_id=client_id, financial_year=fy, item=item)
                    s.add(row)
                row.amount, row.note, row.updated_by = amount, note.strip(), by.username
            audit(s, "GSTR9C_INPUT", "gstr9c", f"{fy}:{item}", {"before": before,
                                                                 "after": {"amount": amount, "note": note}},
                  by.username, client_id)

    def import_expenses(self, client_id: int, fy: str, path, by: Session | None = None, apply: bool = True):
        """Read an expense ledger into Table 14. With ``apply`` the row totals replace the Table 14 figures
        (each change audited); without it the lines are only returned for preview."""
        from pathlib import Path

        from ..gstr9.expenses import TABLE14, read_expense_ledger, totals_by_row

        require(by, "review")
        lines = read_expense_ledger(path)
        if not lines:
            raise ServiceError("The expense ledger has no lines")
        if apply:
            totals = totals_by_row(lines)
            note = f"Expense ledger {Path(path).name}"
            current = self.inputs(client_id, fy)
            for code, _label in TABLE14:
                v, t, e = totals.get(code, (None, None, None))
                for part, amount in (("V", v), ("T", t), ("E", e)):
                    item = f"{code}-{part}"
                    if amount is None and item not in current:
                        continue
                    self.set_input(client_id, fy, item, amount, note if amount is not None else "", by)
        return lines

    def books_itc(self, client_id: int, fy: str) -> Decimal:
        it = Invoice.__table__
        with self.db.session() as s:
            rows = s.execute(select(it).where(it.c.client_id == client_id, it.c.source_type == Source.BOOKS.value,
                                              it.c.period.in_(fy_months(fy))))
            return sum((invoice_to_record(r).signed("itc") for r in rows), ZERO)

    def statement(self, client_id: int, fy: str) -> Gstr9cStatement:
        g9 = Gstr9Service(self.db).working(client_id, fy)
        sales = OutwardService(self.db).sales(client_id, fy_months(fy))
        return build_9c(fy, g9, sales, self.books_itc(client_id, fy), self.inputs(client_id, fy))
