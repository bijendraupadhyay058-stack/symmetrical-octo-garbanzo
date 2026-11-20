"""Preparer – reviewer sign-off of a client's working papers for a financial year.

Each working paper (area) is *prepared* by one person and *reviewed* by another (four eyes: the preparer cannot
review). The sign-off stores a fingerprint of the data the working is made from – imported documents, decisions,
classifications, marks. When that data changes afterwards the sign-off shows **out of date**: the working must be
prepared and reviewed again. Nothing in the data is locked or changed by a sign-off.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from ..db.database import Database
from ..db.models import (
    Client, Gstr3bEntry, Gstr9cInput, Invoice, ItcPart, ItcTxn, LedgerEntry, LedgerMapping, LedgerSplit,
    MatchDecision, OtherItc, ReconRun, ReviewMark, Rule37aAction, SignOff, SupplierFiling, TaxPosting, TbLedger,
    VoucherLine,
)
from ..itc.annual import fy_months
from .auth import Session, require
from .common import ServiceError, audit

AREAS = {
    "recon": "Purchase register vs GSTR-2B reconciliation",
    "sales": "Sales register vs GSTR-1 reconciliation",
    "itc_register": "ITC classification register",
    "bifurcation": "Ledger classification & bifurcation",
    "table14": "GSTR-9C Table 14 (ITC on expenses)",
    "gstr9": "GSTR-9 working",
    "gstr9c": "GSTR-9C reconciliation",
    "doc_checks": "Duplicates & credit / debit notes",
    "rule37a": "Rule 37A reversal",
}
_INV_COLS = (Invoice.id, Invoice.source_type, Invoice.supplier_gstin, Invoice.doc_type, Invoice.invoice_no,
             Invoice.invoice_date, Invoice.period, Invoice.taxable, Invoice.igst, Invoice.cgst, Invoice.sgst,
             Invoice.cess, Invoice.itc_availability, Invoice.original_invoice_no, Invoice.reverse_charge)


@dataclass
class SignOffStatus:
    area: str
    title: str
    state: str  # not_prepared / prepared / reviewed / changed
    row: SignOff | None

    @property
    def label(self) -> str:
        r = self.row
        if self.state == "not_prepared":
            return "Not prepared"
        if self.state == "prepared":
            return "Prepared – awaiting review"
        if self.state == "reviewed":
            return "Reviewed"
        return "Out of date – data changed after " + ("review" if r and r.reviewed_by else "preparation")


class SignOffService:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------ fingerprint
    def fingerprint(self, client_id: int, fy: str, area: str) -> str:
        if area not in AREAS:
            raise ServiceError(f"Unknown working paper {area!r}")
        months = fy_months(fy)
        h = hashlib.sha256(area.encode())

        def put(rows):
            n = 0
            for r in rows:
                h.update(repr(tuple(r)).encode())
                n += 1
            h.update(f"#{n}".encode())

        def table(s, model, *where):
            t = model.__table__
            put(s.execute(select(t).where(*where).order_by(*t.primary_key.columns)).all())

        def inv(s, *sources):
            q = select(*_INV_COLS).where(Invoice.client_id == client_id, Invoice.period.in_(months))
            if sources:
                q = q.where(Invoice.source_type.in_(sources))
            put(s.execute(q.order_by(Invoice.id)).all())

        def runs(s, comparison):
            rs = list(s.scalars(select(ReconRun.id).where(ReconRun.client_id == client_id,
                                                          ReconRun.financial_year == fy,
                                                          ReconRun.comparison == comparison)))
            h.update(repr(rs).encode())
            table(s, MatchDecision, MatchDecision.client_id == client_id, MatchDecision.run_id.in_(rs or [-1]))

        def itc(s):
            table(s, ItcTxn, ItcTxn.client_id == client_id, ItcTxn.financial_year == fy)
            ids = select(ItcTxn.id).where(ItcTxn.client_id == client_id, ItcTxn.financial_year == fy)
            table(s, ItcPart, ItcPart.client_id == client_id, ItcPart.txn_id.in_(ids))
            table(s, TaxPosting, TaxPosting.client_id == client_id, TaxPosting.financial_year == fy)

        def ledgers(s):
            table(s, TbLedger, TbLedger.client_id == client_id, TbLedger.financial_year == fy)
            ids = select(TbLedger.id).where(TbLedger.client_id == client_id, TbLedger.financial_year == fy)
            table(s, LedgerSplit, LedgerSplit.client_id == client_id, LedgerSplit.ledger_id.in_(ids))

        def gstr9(s):
            inv(s)
            table(s, Gstr3bEntry, Gstr3bEntry.client_id == client_id, Gstr3bEntry.period.in_(months))
            table(s, OtherItc, OtherItc.client_id == client_id, OtherItc.period.in_(months))

        with self.db.session() as s:
            if area == "recon":
                inv(s, "BOOKS", "GSTR2B")
                runs(s, "BOOKS_VS_GSTR2B")
            elif area == "sales":
                inv(s, "SALES", "GSTR1")
                runs(s, "SALES_VS_GSTR1")
            elif area == "itc_register":
                itc(s)
            elif area == "bifurcation":
                ledgers(s)
                table(s, VoucherLine, VoucherLine.client_id == client_id, VoucherLine.financial_year == fy)
                table(s, LedgerMapping, LedgerMapping.client_id == client_id)
            elif area == "table14":
                ledgers(s)
                itc(s)
                table(s, LedgerEntry, LedgerEntry.client_id == client_id)
            elif area == "gstr9":
                gstr9(s)
            elif area == "gstr9c":
                gstr9(s)
                ledgers(s)
                table(s, Gstr9cInput, Gstr9cInput.client_id == client_id, Gstr9cInput.financial_year == fy)
            elif area == "doc_checks":
                inv(s, "BOOKS", "SALES", "GSTR2B")
                table(s, ReviewMark, ReviewMark.client_id == client_id)
            elif area == "rule37a":
                inv(s, "GSTR2B")
                table(s, Rule37aAction, Rule37aAction.client_id == client_id)
                gstins = select(Invoice.supplier_gstin).where(Invoice.client_id == client_id,
                                                               Invoice.source_type == "GSTR2B",
                                                               Invoice.period.in_(months))
                put(s.execute(select(SupplierFiling.gstin, SupplierFiling.period, SupplierFiling.gstr3b_filed,
                                     SupplierFiling.filed_on).where(SupplierFiling.gstin.in_(gstins))
                              .order_by(SupplierFiling.gstin, SupplierFiling.period)).all())
        return h.hexdigest()

    # ------------------------------------------------------------ status
    def _row(self, s, client_id, fy, area) -> SignOff | None:
        return s.scalars(select(SignOff).where(SignOff.client_id == client_id, SignOff.fy == fy,
                                               SignOff.area == area)).first()

    def status(self, client_id: int, fy: str) -> list[SignOffStatus]:
        with self.db.session() as s:
            if s.get(Client, client_id) is None:
                raise ServiceError(f"Client {client_id} not found")
            rows = {r.area: r for r in s.scalars(select(SignOff).where(SignOff.client_id == client_id,
                                                                       SignOff.fy == fy))}
            for r in rows.values():
                s.expunge(r)
        out = []
        for area, title in AREAS.items():
            r = rows.get(area)
            if r is None or not r.prepared_by:
                out.append(SignOffStatus(area, title, "not_prepared", r))
                continue
            now = self.fingerprint(client_id, fy, area)
            signed = r.reviewed_print if r.reviewed_by else r.prepared_print
            state = "changed" if now != signed else ("reviewed" if r.reviewed_by else "prepared")
            out.append(SignOffStatus(area, title, state, r))
        return out

    # ------------------------------------------------------------ actions
    def prepare(self, client_id: int, fy: str, area: str, by: Session, note: str = "") -> SignOff:
        require(by, "prepare_papers")
        fp = self.fingerprint(client_id, fy, area)
        with self.db.session() as s:
            r = self._row(s, client_id, fy, area)
            if r is None:
                r = SignOff(client_id=client_id, fy=fy, area=area)
                s.add(r)
            r.prepared_by, r.prepared_at, r.prepared_note, r.prepared_print = by.username, datetime.now(), note, fp
            r.reviewed_by, r.reviewed_at, r.review_note, r.reviewed_print = "", None, "", ""
            audit(s, "PREPARE", "sign_off", f"{fy} {area}", {"note": note, "print": fp[:16]}, by.username,
                  client_id)
            s.flush()
            s.expunge(r)
        return r

    def review(self, client_id: int, fy: str, area: str, by: Session, note: str = "") -> SignOff:
        require(by, "review_papers")
        fp = self.fingerprint(client_id, fy, area)
        with self.db.session() as s:
            r = self._row(s, client_id, fy, area)
            if r is None or not r.prepared_by:
                raise ServiceError(f"{AREAS[area]} has not been marked as prepared yet")
            if r.reviewed_by:
                raise ServiceError(f"Already reviewed by {r.reviewed_by} on {r.reviewed_at:%d-%m-%Y}")
            if r.prepared_by == by.username:
                raise ServiceError("The preparer cannot review their own working – a different person must review")
            if r.prepared_print != fp:
                raise ServiceError("The data has changed since it was prepared – the preparer must check the working "
                                   "and mark it prepared again before review")
            r.reviewed_by, r.reviewed_at, r.review_note, r.reviewed_print = by.username, datetime.now(), note, fp
            audit(s, "REVIEW", "sign_off", f"{fy} {area}", {"note": note, "print": fp[:16]}, by.username, client_id)
            s.flush()
            s.expunge(r)
        return r

    def reopen(self, client_id: int, fy: str, area: str, by: Session, reason: str) -> None:
        require(by, "prepare_papers")
        if not reason.strip():
            raise ServiceError("Give the reason for reopening (kept in the audit log)")
        with self.db.session() as s:
            r = self._row(s, client_id, fy, area)
            if r is None:
                return
            if r.reviewed_by and not by.can("review_papers"):
                raise ServiceError("Only a partner / manager can reopen a reviewed working")
            audit(s, "REOPEN", "sign_off", f"{fy} {area}", {"reason": reason, "prepared_by": r.prepared_by,
                                                             "reviewed_by": r.reviewed_by}, by.username, client_id)
            s.delete(r)

    # ------------------------------------------------------------ export
    def export_xlsx(self, client_id: int, fy: str, path: str | Path) -> Path:
        from openpyxl import Workbook
        from openpyxl.styles import Font

        with self.db.session() as s:
            c = s.get(Client, client_id)
            name, gstin = c.name, c.gstin
        wb = Workbook()
        ws = wb.active
        ws.title = "Sign-off"
        ws.append([f"{name} ({gstin}) – working paper sign-off – FY {fy}"])
        ws["A1"].font = Font(bold=True, size=12)
        ws.append(["Working paper", "Status", "Prepared by", "Prepared on", "Preparer's note", "Reviewed by",
                   "Reviewed on", "Reviewer's note"])
        for cell in ws[2]:
            cell.font = Font(bold=True)
        for st in self.status(client_id, fy):
            r = st.row
            ws.append([st.title, st.label, r.prepared_by if r else "", r.prepared_at if r else None,
                       r.prepared_note if r else "", r.reviewed_by if r else "", r.reviewed_at if r else None,
                       r.review_note if r else ""])
        for col, wd in zip("ABCDEFGH", (44, 40, 16, 18, 40, 16, 18, 40)):
            ws.column_dimensions[col].width = wd
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(path)
        return path
