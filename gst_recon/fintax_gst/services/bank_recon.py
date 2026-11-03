"""Bank statement vs electronic cash ledger: every GST payment debited in the bank should be credited in the
electronic cash ledger (a deposit against a CPIN / CIN), and every deposit should be traceable to a payment.

Matching: by the 14-digit CPIN when both carry it; otherwise by the same amount within a few days. Results:
matched, amount differs, debited in the bank but not credited in the cash ledger (follow up with the bank; if the
CIN was not generated, a grievance in Form GST PMT-07 on the portal), and deposits not found in the statement
(paid from another account or over the counter, or outside the statement's period).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from ..core.money import ZERO
from ..db.database import Database
from ..db.models import BankLine, Client, LedgerEntry, SourceFile
from ..importers.bank import CPIN, GST_WORDS, read_statement
from ..importers.ledgers import HEADS
from ..importers.pipeline import sha256_of
from .common import ServiceError, audit, dumps

DAYS = 5
MATCHED, AMOUNT, NOT_CREDITED, NOT_IN_BANK = ("Matched", "Amount differs", "Not credited in cash ledger",
                                              "Not in bank statement")


@dataclass
class Pair:
    status: str
    bank: BankLine | None
    deposit: LedgerEntry | None
    how: str = ""

    @property
    def bank_amount(self) -> Decimal | None:
        return self.bank.debit if self.bank else None

    @property
    def ledger_amount(self) -> Decimal | None:
        return sum((getattr(self.deposit, h) for h in HEADS), ZERO) if self.deposit else None


@dataclass
class BankRecon:
    date_from: date | None
    date_to: date | None
    pairs: list[Pair] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def count(self, status: str) -> int:
        return sum(1 for p in self.pairs if p.status == status)


def _cpin(text: str) -> str:
    m = CPIN.search(text or "")
    return m.group(1) if m else ""


class BankReconService:
    def __init__(self, db: Database):
        self.db = db

    def import_statement(self, client_id: int, path: str | Path, user: str | None = None) -> tuple[int, int,
                                                                                                   list[str]]:
        """Save the statement; lines already saved from an overlapping statement are not added again.
        Returns (lines saved, GST payments among them, lines not read)."""
        path = Path(path)
        rows, skipped = read_statement(path)
        digest = sha256_of(path)
        with self.db.session() as s:
            if s.get(Client, client_id) is None:
                raise ServiceError(f"Client {client_id} not found")
            dup = s.scalar(select(SourceFile.id).where(SourceFile.client_id == client_id, SourceFile.sha256 == digest))
            if dup:
                raise ServiceError(f"{path.name} was already imported (import #{dup})")
            have = {(b.txn_date, b.narration, b.debit, b.credit) for b in s.scalars(
                select(BankLine).where(BankLine.client_id == client_id))}
            new = [r for r in rows if (r.txn_date, r.narration, r.debit, r.credit) not in have]
            sf = SourceFile(client_id=client_id, source_type="BANK", file_name=path.name,
                            file_path=str(path.resolve()), sha256=digest, layout="bank_statement", period=None,
                            rows_read=len(rows) + len(skipped), documents_imported=len(new),
                            warnings_json=dumps(skipped + ([f"{len(rows) - len(new)} line(s) already saved from an "
                                                            "earlier statement"] if len(new) < len(rows) else [])),
                            imported_by=user or "")
            s.add(sf)
            s.flush()
            for r in new:
                s.add(BankLine(client_id=client_id, source_file_id=sf.id, txn_date=r.txn_date, narration=r.narration,
                               reference=r.reference, debit=r.debit, credit=r.credit, balance=r.balance,
                               source_row=r.row[:80]))
            gst = sum(1 for r in new if r.is_gst_payment)
            audit(s, "IMPORT", "source_file", sf.id, {"file": path.name, "lines": len(new), "gst_payments": gst},
                  user, client_id)
        return len(new), gst, skipped

    def reconcile(self, client_id: int, date_from: date | None = None, date_to: date | None = None) -> BankRecon:
        with self.db.session() as s:
            q = select(BankLine).where(BankLine.client_id == client_id)
            lines = list(s.scalars(q.order_by(BankLine.txn_date, BankLine.id)))
            deposits = list(s.scalars(select(LedgerEntry).where(
                LedgerEntry.client_id == client_id, LedgerEntry.ledger == "CASH", LedgerEntry.txn == "CR")
                .order_by(LedgerEntry.entry_date, LedgerEntry.id)))
        if not lines:
            raise ServiceError("Import the client's bank statement first")
        date_from = date_from or min(b.txn_date for b in lines)
        date_to = date_to or max(b.txn_date for b in lines)
        out = BankRecon(date_from, date_to)
        pays = [b for b in lines if date_from <= b.txn_date <= date_to and b.debit > 0 and (
            GST_WORDS.search(b.narration) or _cpin(f"{b.narration} {b.reference}"))]
        deps = [d for d in deposits if d.entry_date and date_from - timedelta(days=1) <= d.entry_date
                <= date_to + timedelta(days=DAYS)]
        if not deposits:
            out.notes.append("No electronic cash ledger imported – download it on the GST Portal page (Services → "
                             "Ledgers → Electronic Cash Ledger) and import it.")

        def amt(d):
            return sum((getattr(d, h) for h in HEADS), ZERO)

        used: set[int] = set()
        for b in pays:
            pin = _cpin(f"{b.narration} {b.reference}")
            dep = next((d for d in deps if d.id not in used and pin and pin in (d.reference + " " + d.description)),
                       None)
            if dep is not None:
                used.add(dep.id)
                status = MATCHED if abs(amt(dep) - b.debit) < Decimal("1") else AMOUNT
                out.pairs.append(Pair(status, b, dep, f"CPIN {pin}"))
                continue
            dep = next((d for d in deps if d.id not in used and abs(amt(d) - b.debit) < Decimal("0.01")
                        and -1 <= (d.entry_date - b.txn_date).days <= DAYS), None)
            if dep is not None:
                used.add(dep.id)
                out.pairs.append(Pair(MATCHED, b, dep, "same amount and date"))
            else:
                age = (date.today() - b.txn_date).days
                out.pairs.append(Pair(NOT_CREDITED, b, None, "check with the bank; if the CIN was not generated, "
                                      "raise a grievance in GST PMT-07 on the portal" + (
                                          f" ({age} days old)" if age > 0 else "")))
        for d in deps:
            if d.id not in used and date_from <= d.entry_date <= date_to:
                out.pairs.append(Pair(NOT_IN_BANK, None, d, "paid from another account / over the counter, or outside "
                                      "this statement"))
        out.pairs.sort(key=lambda p: ((p.bank.txn_date if p.bank else p.deposit.entry_date) or date.min))
        return out

    def export_xlsx(self, rec: BankRecon, client_name: str, path: str | Path) -> Path:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill

        wb = Workbook()
        ws = wb.active
        ws.title = "Bank vs cash ledger"
        ws.append([f"{client_name} – GST payments: bank statement vs electronic cash ledger "
                   f"({rec.date_from:%d-%m-%Y} to {rec.date_to:%d-%m-%Y})"])
        ws["A1"].font = Font(bold=True)
        ws.append(["Status", "Bank date", "Narration", "Bank amount", "Ledger date", "CPIN / CIN", "Ledger amount",
                   "How / what to do"])
        for c in ws[2]:
            c.font = Font(bold=True)
        fills = {MATCHED: "C8E6C9", AMOUNT: "FFF3C4", NOT_CREDITED: "FFCDD2", NOT_IN_BANK: "E3F2FD"}
        for p in rec.pairs:
            ws.append([p.status, p.bank.txn_date if p.bank else None, p.bank.narration if p.bank else "",
                       float(p.bank_amount) if p.bank_amount is not None else None,
                       p.deposit.entry_date if p.deposit else None, p.deposit.reference if p.deposit else "",
                       float(p.ledger_amount) if p.ledger_amount is not None else None, p.how])
            for c in ws[ws.max_row]:
                c.fill = PatternFill("solid", fgColor=fills[p.status])
        for col, w in zip("ABCDEFGH", (26, 11, 50, 14, 11, 22, 14, 60)):
            ws.column_dimensions[col].width = w
        for n in rec.notes:
            ws.append([n])
        path = Path(path)
        wb.save(path)
        return path
