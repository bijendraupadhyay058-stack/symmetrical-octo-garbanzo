"""Rule 42 / 43 working for a client: the user's figures, the common capital goods register, the monthly
reversal and the annual true-up (see compliance/rule42.py)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from ..compliance.rule42 import HEADS, ZERO, Rule42Month, Rule42Year, capital_good_tm
from ..db.database import Database
from ..db.models import CapitalGood, CommonCredit
from ..importers.parsing import parse_period
from ..itc.annual import fy_months
from .common import ServiceError, audit


def _prev(period: str) -> str:
    y, m = int(period[:4]), int(period[5:])
    return f"{y - (m == 1):04d}-{(m - 2) % 12 + 1:02d}"


class CommonCreditService:
    def __init__(self, db: Database):
        self.db = db

    # --------------------------------------------------------------- inputs
    def inputs(self, client_id: int, period: str) -> CommonCredit | None:
        with self.db.session() as s:
            return s.scalar(select(CommonCredit).where(CommonCredit.client_id == client_id,
                                                       CommonCredit.period == period))

    def save(self, client_id: int, period: str, t1=ZERO, t2=ZERO, t4=ZERO, non_business: bool = False,
             note: str = "", user: str | None = None) -> None:
        p = parse_period(period)
        if not p:
            raise ServiceError(f"Invalid period {period} – use YYYY-MM")
        vals = {"t1": Decimal(str(t1 or 0)), "t2": Decimal(str(t2 or 0)), "t4": Decimal(str(t4 or 0))}
        if any(v < 0 for v in vals.values()):
            raise ServiceError("Amounts cannot be negative")
        with self.db.session() as s:
            row = s.scalar(select(CommonCredit).where(CommonCredit.client_id == client_id, CommonCredit.period == p))
            if row is None:
                row = CommonCredit(client_id=client_id, period=p)
                s.add(row)
            for k, v in vals.items():
                setattr(row, k, v)
            row.non_business, row.note, row.updated_by = non_business, note, (user or "")[:80]
            audit(s, "SAVE", "common_credit", p, {k: str(v) for k, v in vals.items()} | {"non_business": non_business},
                  user, client_id)

    def clear(self, client_id: int, period: str, user: str | None = None) -> None:
        with self.db.session() as s:
            row = s.scalar(select(CommonCredit).where(CommonCredit.client_id == client_id,
                                                      CommonCredit.period == period))
            if row is not None:
                s.delete(row)
                audit(s, "DELETE", "common_credit", period, {}, user, client_id)

    # -------------------------------------------------------- capital goods
    def goods(self, client_id: int) -> list[CapitalGood]:
        with self.db.session() as s:
            return list(s.scalars(select(CapitalGood).where(CapitalGood.client_id == client_id)
                                  .order_by(CapitalGood.invoice_date, CapitalGood.id)))

    def add_good(self, client_id: int, description: str, invoice_date: date, igst=ZERO, cgst=ZERO, sgst=ZERO,
                 cess=ZERO, invoice_no: str = "", user: str | None = None) -> int:
        if not description.strip():
            raise ServiceError("Describe the capital good")
        amounts = {k: Decimal(str(v or 0)) for k, v in (("igst", igst), ("cgst", cgst), ("sgst", sgst),
                                                         ("cess", cess))}
        if sum(amounts.values(), ZERO) <= 0:
            raise ServiceError("Enter the ITC of the capital good")
        with self.db.session() as s:
            g = CapitalGood(client_id=client_id, description=description.strip()[:200], invoice_no=invoice_no[:100],
                            invoice_date=invoice_date, created_by=(user or "")[:80], **amounts)
            s.add(g)
            s.flush()
            audit(s, "CREATE", "capital_goods", g.id, {"description": g.description, "date": invoice_date.isoformat(),
                                                       **{k: str(v) for k, v in amounts.items()}}, user, client_id)
            return g.id

    def remove_good(self, client_id: int, good_id: int, user: str | None = None) -> None:
        with self.db.session() as s:
            g = s.get(CapitalGood, good_id)
            if g is None or g.client_id != client_id:
                raise ServiceError("Capital good not found")
            audit(s, "DELETE", "capital_goods", good_id, {"description": g.description}, user, client_id)
            s.delete(g)

    # -------------------------------------------------------------- working
    def _turnover(self, client_id: int, period: str) -> tuple[Decimal, Decimal]:
        from .outward import OutwardService

        out = OutwardService(self.db)
        if not out.sales(client_id, [period]):
            return ZERO, ZERO
        w = out.liability(client_id, [period])[0]
        exempt = w.row("31C").sales.taxable + w.row("31E").sales.taxable
        total = exempt + w.row("31A").sales.taxable + w.row("31B").sales.taxable
        return exempt, total

    def month(self, client_id: int, period: str, as_of: date | None = None) -> Rule42Month:
        from .itc import ItcService

        p = parse_period(period)
        if not p:
            raise ServiceError(f"Invalid period {period} – use YYYY-MM")
        work = ItcService(self.db).table4(client_id, [p], as_of)[0]
        books = {r.code: r.books for r in work.rows}
        if all(v.total == 0 for k, v in books.items() if k != "4C"):  # not reconciled: GSTR-2B
            books = {r.code: r.auto_2b for r in work.rows}
        c1 = {h: max(getattr(books["4C"], h), ZERO) for h in HEADS}
        goods = self.goods(client_id)
        for g in goods:  # credit on capital goods bought this month is handled under Rule 43, not Rule 42
            if f"{g.invoice_date:%Y-%m}" == p:
                for h in HEADS:
                    c1[h] = max(c1[h] - getattr(g, h), ZERO)
        inputs = self.inputs(client_id, p)
        exempt, total = self._turnover(client_id, p)
        ratio_from, look = "", p
        for _ in range(24):  # no turnover this month: E and F of the last month that had turnover
            if total:
                break
            look = _prev(look)
            exempt, total = self._turnover(client_id, look)
            ratio_from = look
        m = Rule42Month(p, c1, exempt=exempt, turnover=total, ratio_from=ratio_from if total else "")
        if inputs is not None:
            m.t1, m.t2, m.t4, m.non_business = inputs.t1, inputs.t2, inputs.t4, inputs.non_business
        for g in goods:
            if g.disposed_on and f"{g.disposed_on:%Y-%m}" < p:
                continue
            tm = capital_good_tm({h: getattr(g, h) for h in HEADS}, g.invoice_date, p)
            if tm is not None:
                m.capital_goods.append((g.description, tm))
        return m

    def applies(self, client_id: int, period: str) -> bool:
        """The month's reversal goes into the GSTR-3B draft once its figures are saved or capital goods exist."""
        return self.inputs(client_id, period) is not None or any(
            capital_good_tm({h: getattr(g, h) for h in HEADS}, g.invoice_date, period) is not None
            for g in self.goods(client_id))

    def year(self, client_id: int, fy: str) -> Rule42Year:
        months = [self.month(client_id, p) for p in fy_months(fy) if self.inputs(client_id, p) is not None]
        exempt = total = ZERO
        for p in fy_months(fy):
            e, t = self._turnover(client_id, p)
            exempt += e
            total += t
        return Rule42Year(fy, months, exempt, total)
