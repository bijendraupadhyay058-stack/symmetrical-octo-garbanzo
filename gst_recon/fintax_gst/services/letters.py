"""Generate supplier discrepancy letters for a reconciliation run and keep a register of them."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select

from ..db.database import Database
from ..db.models import LetterRecord
from ..letters.content import SupplierLetter, build_letters
from ..letters.render import LetterContext, render_docx, render_eml, render_pdf, safe_name
from .common import ServiceError, audit, dumps
from .followup import VendorService
from .reconciliation import ReconciliationService

FORMATS = ("docx", "pdf", "eml")


def period_label(p_from: str, p_to: str) -> str:
    fmt = lambda p: date(int(p[:4]), int(p[5:]), 1).strftime("%B %Y")  # noqa: E731
    return fmt(p_from) if p_from == p_to else f"{fmt(p_from)} to {fmt(p_to)}"


class LetterService:
    def __init__(self, db: Database):
        self.db = db
        self.recon = ReconciliationService(db)
        self.vendors = VendorService(db)

    def preview(self, run_id: int, gstins: set[str] | None = None) -> list[SupplierLetter]:
        ctx = self.recon.load(run_id)
        if not ctx.run.comparison.startswith("BOOKS"):
            raise ServiceError("Supplier letters are prepared from purchase (inward) reconciliations")
        return build_letters(ctx.result.lines, gstins)

    def generate(self, run_id: int, out_dir: str | Path, gstins: set[str] | None = None,
                 formats: tuple[str, ...] = FORMATS, reply_days: int = 15, signatory: str = "",
                 letter_date: date | None = None, update_register: bool = True,
                 user: str | None = None) -> list[tuple[SupplierLetter, list[Path]]]:
        bad = set(formats) - set(FORMATS)
        if bad:
            raise ServiceError(f"Unknown letter format(s): {', '.join(sorted(bad))}")
        ctx = self.recon.load(run_id)
        letters = self.preview(run_id, gstins)
        if not letters:
            return []
        client, run = ctx.client, ctx.run
        letter_date = letter_date or date.today()
        vendors = self.vendors.all(client.id)
        folder = Path(out_dir) / f"Letters_{client.gstin}_{run.period_from}_{run.period_to}"
        out = []
        for n, letter in enumerate(letters, start=1):
            v = vendors.get(letter.gstin)
            lc = LetterContext(client.name, client.gstin, client.address or "", period_label(run.period_from,
                                                                                               run.period_to),
                               letter_date, letter_date + timedelta(days=reply_days),
                               f"GST/{run.period_from}/{run.id}/{n:03d}", signatory,
                               client.contact_person or "", (v.email if v else "") or "")
            stem = folder / f"{letter.gstin}_{safe_name(letter.name)}"
            paths = []
            pdf = None
            if "docx" in formats:
                paths.append(render_docx(lc, letter, stem.with_suffix(".docx")))
            if "pdf" in formats or "eml" in formats:
                pdf = render_pdf(lc, letter, stem.with_suffix(".pdf"))
                if "pdf" in formats:
                    paths.append(pdf)
            if "eml" in formats:
                paths.append(render_eml(lc, letter, stem.with_suffix(".eml"), pdf))
                if "pdf" not in formats:
                    pdf.unlink()
            with self.db.session() as s:
                s.add(LetterRecord(client_id=client.id, run_id=run.id, supplier_gstin=letter.gstin,
                                   issues=len(letter.items), amount=letter.amount,
                                   files_json=json.dumps([str(p) for p in paths]), user=user or ""))
                audit(s, "LETTER", "supplier", letter.gstin, {"run_id": run.id, "issues": len(letter.items),
                                                              "amount": letter.amount, "reference": lc.reference},
                      user, client.id)
            if update_register:
                try:
                    note = f"Letter {lc.reference} dated {letter_date:%d-%m-%Y} ({len(letter.items)} item(s))"
                    remarks = f"{v.remarks}\n{note}".strip() if v and v.remarks else note
                    self.vendors.upsert(client.id, letter.gstin, user, name=(v.name if v and v.name else letter.name),
                                        followup_status="Letter issued", next_followup=lc.reply_by, remarks=remarks)
                except ServiceError:
                    pass  # invalid supplier GSTIN – the letter itself is still produced
            out.append((letter, paths))
        return out

    def register(self, client_id: int) -> list[dict]:
        with self.db.session() as s:
            return [{"id": r.id, "run_id": r.run_id, "supplier_gstin": r.supplier_gstin, "issues": r.issues,
                     "amount": r.amount, "files": json.loads(r.files_json), "user": r.user, "at": r.created_at}
                    for r in s.scalars(select(LetterRecord).where(LetterRecord.client_id == client_id)
                                       .order_by(LetterRecord.id.desc()))]


__all__ = ["LetterService", "FORMATS", "period_label", "dumps"]
