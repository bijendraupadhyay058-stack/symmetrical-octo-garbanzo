"""E-mail from the program through the firm's own mail account (SMTP).

Mails are first saved as drafts in the outbox – supplier letters, the one-page client report, document reminders.
Nothing is sent until a user looks at the drafts and sends them. The mail password is kept encrypted with a key
stored next to the database on this computer (a copied database alone does not reveal it), or not kept at all and
asked for when sending. Every mail sent or failed is in the audit log.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import smtplib
import ssl
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select

from ..db.database import Database
from ..db.models import AppSetting, Client, OutboxMail
from .auth import Session, require
from .common import ServiceError, audit

ACCOUNT_KEY = "mail_account"
SECURITY = {"ssl": "SSL (port 465)", "starttls": "STARTTLS (port 587)", "none": "None (port 25 – not advised)"}
PRESETS = {  # common providers: host, port, security
    "Gmail / Google Workspace": ("smtp.gmail.com", 587, "starttls"),
    "Outlook / Microsoft 365": ("smtp.office365.com", 587, "starttls"),
    "Zoho Mail (India)": ("smtp.zoho.in", 465, "ssl"),
    "Yahoo Mail": ("smtp.mail.yahoo.com", 465, "ssl"),
    "Rediffmail Pro": ("smtp.rediffmailpro.com", 587, "starttls"),
}
_ADDR = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[A-Za-z]{2,}$")
KINDS = {"supplier_letter": "Supplier letter", "client_report": "Client report", "reminder": "Document reminder",
         "other": "Other"}


@dataclass
class MailAccount:
    host: str = ""
    port: int = 587
    security: str = "starttls"
    username: str = ""
    sender: str = ""  # From address
    sender_name: str = ""
    save_password: bool = True

    @property
    def ready(self) -> bool:
        return bool(self.host and self.sender)


def split_addresses(text: str) -> list[str]:
    return [a.strip() for a in re.split(r"[;,\s]+", text or "") if a.strip()]


def bad_addresses(text: str) -> list[str]:
    return [a for a in split_addresses(text) if not _ADDR.match(a)]


class MailService:
    def __init__(self, db: Database):
        self.db = db

    # ----------------------------------------------------------- account
    def _keyfile(self) -> Path:
        return Path(self.db.data_dir) / ".fintaxpro-mail.key"

    def _fernet(self, create: bool = False) -> Fernet | None:
        kf = self._keyfile()
        if not kf.exists():
            if not create:
                return None
            kf.parent.mkdir(parents=True, exist_ok=True)
            kf.write_bytes(Fernet.generate_key())
            try:
                os.chmod(kf, 0o600)
            except OSError:  # pragma: no cover - Windows
                pass
        return Fernet(kf.read_bytes().strip())

    def account(self) -> MailAccount:
        with self.db.session() as s:
            row = s.get(AppSetting, ACCOUNT_KEY)
            data = json.loads(row.value_json) if row else {}
        data.pop("password", None)
        fields = {k: v for k, v in data.items() if k in MailAccount.__dataclass_fields__}
        return MailAccount(**fields)

    def has_saved_password(self) -> bool:
        return self._saved_password() is not None

    def _saved_password(self) -> str | None:
        with self.db.session() as s:
            row = s.get(AppSetting, ACCOUNT_KEY)
            token = json.loads(row.value_json).get("password") if row else None
        f = self._fernet()
        if not token or f is None:
            return None
        try:
            return f.decrypt(token.encode()).decode()
        except InvalidToken:
            return None  # the database was moved to another computer: ask again

    def save_account(self, acc: MailAccount, password: str | None, by: Session | None) -> None:
        """``password`` None keeps the saved one; '' removes it."""
        require(by, "settings")
        if not acc.host.strip():
            raise ServiceError("Enter the mail server (SMTP host), e.g. smtp.gmail.com")
        if not _ADDR.match(acc.sender.strip()):
            raise ServiceError(f"'{acc.sender}' is not an e-mail address")
        if acc.security not in SECURITY:
            raise ServiceError(f"Unknown security {acc.security}")
        if not 1 <= int(acc.port) <= 65535:
            raise ServiceError("Port must be between 1 and 65535")
        acc = MailAccount(acc.host.strip(), int(acc.port), acc.security, acc.username.strip(), acc.sender.strip(),
                          acc.sender_name.strip(), bool(acc.save_password))
        with self.db.session() as s:
            row = s.get(AppSetting, ACCOUNT_KEY)
            old = json.loads(row.value_json) if row else {}
            data = asdict(acc)
            if not acc.save_password or password == "":
                pass  # no password kept
            elif password is not None:
                data["password"] = self._fernet(create=True).encrypt(password.encode()).decode()
            elif old.get("password"):
                data["password"] = old["password"]
            if row is None:
                row = AppSetting(key=ACCOUNT_KEY, value_json="{}")
                s.add(row)
            row.value_json = json.dumps(data)
            audit(s, "SETTING", "app_settings", ACCOUNT_KEY, {"host": acc.host, "sender": acc.sender,
                                                              "password_saved": "password" in data}, by.username)

    def _connect(self, acc: MailAccount, password: str | None, timeout: float = 30):
        ctx = ssl.create_default_context()
        if acc.security == "ssl":
            smtp = smtplib.SMTP_SSL(acc.host, acc.port, timeout=timeout, context=ctx)
        else:
            smtp = smtplib.SMTP(acc.host, acc.port, timeout=timeout)
            if acc.security == "starttls":
                smtp.starttls(context=ctx)
        if acc.username:
            if not password:
                smtp.quit()
                raise ServiceError("The mail password is needed")
            smtp.login(acc.username, password)
        return smtp

    def test_account(self, password: str | None = None) -> str:
        acc = self.account()
        if not acc.ready:
            raise ServiceError("Set up the mail account first (Settings → E-mail account)")
        try:
            smtp = self._connect(acc, password or self._saved_password(), timeout=20)
            smtp.quit()
        except smtplib.SMTPAuthenticationError:
            raise ServiceError("The mail server refused the user name or password. For Gmail / Outlook use an "
                               "'app password' (2-step verification must be on).") from None
        except (OSError, smtplib.SMTPException) as exc:
            raise ServiceError(f"Could not connect to {acc.host}:{acc.port} – {exc}") from None
        return f"Connected to {acc.host} as {acc.username or acc.sender}"

    # ------------------------------------------------------------ drafts
    def add_draft(self, kind: str, to: str, subject: str, body: str, attachments: list[str | Path] | None = None,
                  client_id: int | None = None, ref: str = "", cc: str = "", user: str | None = None) -> OutboxMail:
        if kind not in KINDS:
            raise ServiceError(f"Unknown mail kind {kind}")
        with self.db.session() as s:
            m = OutboxMail(client_id=client_id, kind=kind, ref=ref[:80], to_addr=to.strip()[:400],
                           cc_addr=cc.strip()[:400], subject=subject[:300], body=body,
                           attachments_json=json.dumps([str(a) for a in attachments or []]),
                           created_by=(user or "")[:80])
            s.add(m)
            s.flush()
            s.expunge(m)
        return m

    def drafts(self, status: str | None = "draft", client_id: int | None = None) -> list[OutboxMail]:
        with self.db.session() as s:
            q = select(OutboxMail).order_by(OutboxMail.id.desc())
            if status:
                q = q.where(OutboxMail.status == status)
            if client_id:
                q = q.where(OutboxMail.client_id == client_id)
            return list(s.scalars(q))

    def update_draft(self, mail_id: int, user: str | None = None, **fields) -> OutboxMail:
        allowed = {"to_addr", "cc_addr", "subject", "body"}
        with self.db.session() as s:
            m = s.get(OutboxMail, mail_id)
            if m is None:
                raise ServiceError(f"Mail {mail_id} not found")
            if m.status not in ("draft", "failed"):
                raise ServiceError("Only drafts can be changed")
            for k, v in fields.items():
                if k in allowed:
                    setattr(m, k, v)
            s.flush()
            s.expunge(m)
        return m

    def cancel(self, mail_ids: list[int], user: str | None = None) -> int:
        n = 0
        with self.db.session() as s:
            for m in s.scalars(select(OutboxMail).where(OutboxMail.id.in_(mail_ids))):
                if m.status in ("draft", "failed"):
                    m.status = "cancelled"
                    n += 1
            audit(s, "EMAIL_CANCEL", "email_outbox", ",".join(map(str, mail_ids)), {"cancelled": n}, user)
        return n

    def problems(self, m: OutboxMail) -> list[str]:
        out = []
        if not split_addresses(m.to_addr):
            out.append("no recipient")
        bad = bad_addresses(m.to_addr) + bad_addresses(m.cc_addr)
        if bad:
            out.append("not an e-mail address: " + ", ".join(bad))
        missing = [Path(a).name for a in json.loads(m.attachments_json) if not Path(a).exists()]
        if missing:
            out.append("attachment missing: " + ", ".join(missing))
        return out

    def _message(self, acc: MailAccount, m: OutboxMail) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = formataddr((acc.sender_name, acc.sender)) if acc.sender_name else acc.sender
        msg["To"] = ", ".join(split_addresses(m.to_addr))
        if m.cc_addr.strip():
            msg["Cc"] = ", ".join(split_addresses(m.cc_addr))
        msg["Subject"] = m.subject
        msg["Message-ID"] = make_msgid(domain=acc.sender.split("@")[-1])
        msg.set_content(m.body)
        for a in json.loads(m.attachments_json):
            p = Path(a)
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            main, sub = ctype.split("/", 1)
            msg.add_attachment(p.read_bytes(), maintype=main, subtype=sub, filename=p.name)
        return msg

    # -------------------------------------------------------------- send
    def send(self, mail_ids: list[int], by: Session | None, password: str | None = None,
             progress=None) -> tuple[int, list[str]]:
        """Send the chosen drafts; returns (sent, problems). Drafts with problems are not sent."""
        require(by, "letters")
        acc = self.account()
        if not acc.ready:
            raise ServiceError("Set up the mail account first (Settings → E-mail account)")
        with self.db.session() as s:
            mails = list(s.scalars(select(OutboxMail).where(OutboxMail.id.in_(mail_ids),
                                                            OutboxMail.status.in_(("draft", "failed")))))
        if not mails:
            raise ServiceError("Nothing to send – choose drafts in the outbox")
        problems, ready = [], []
        for m in mails:
            p = self.problems(m)
            if p:
                problems.append(f"#{m.id} {m.subject[:50]}: " + "; ".join(p))
            else:
                ready.append(m)
        if not ready:
            return 0, problems
        try:
            smtp = self._connect(acc, password or self._saved_password())
        except smtplib.SMTPAuthenticationError:
            raise ServiceError("The mail server refused the user name or password. For Gmail / Outlook use an "
                               "'app password'.") from None
        except (OSError, smtplib.SMTPException) as exc:
            raise ServiceError(f"Could not connect to {acc.host}:{acc.port} – {exc}. Nothing was sent; the drafts "
                               "stay in the outbox.") from None
        sent = 0
        try:
            for n, m in enumerate(ready, start=1):
                if progress:
                    progress(n, len(ready))
                try:
                    smtp.send_message(self._message(acc, m))
                    ok, err = True, ""
                except (OSError, smtplib.SMTPException) as exc:
                    ok, err = False, str(exc)[:500]
                with self.db.session() as s:
                    row = s.get(OutboxMail, m.id)
                    row.status, row.error = ("sent", "") if ok else ("failed", err)
                    if ok:
                        row.sent_by, row.sent_at = by.username, datetime.now(timezone.utc).replace(tzinfo=None)
                    audit(s, "EMAIL_SENT" if ok else "EMAIL_FAILED", "email_outbox", m.id,
                          {"to": m.to_addr, "subject": m.subject, "kind": m.kind, "error": err}, by.username,
                          m.client_id)
                if ok:
                    sent += 1
                    self._after_send(m, by.username)
                else:
                    problems.append(f"#{m.id} {m.subject[:50]}: {err}")
        finally:
            try:
                smtp.quit()
            except (OSError, smtplib.SMTPException):
                pass
        return sent, problems

    def _after_send(self, m: OutboxMail, user: str) -> None:
        """Keep the client reminder history in step with mails that went out."""
        if m.kind == "reminder" and m.client_id:
            from ..db.models import ClientReminder

            with self.db.session() as s:
                s.add(ClientReminder(client_id=m.client_id, period=m.ref[:7], channel="email",
                                     items_json=json.dumps([m.subject]), user=user[:80]))

    # ------------------------------------------------- drafts from the work
    def letters_to_drafts(self, run_id: int, signatory: str = "", reply_days: int = 15,
                          user: str | None = None) -> list[OutboxMail]:
        """Supplier discrepancy letters of a purchase reconciliation as e-mail drafts with the PDF attached."""
        from .followup import VendorService
        from .letters import LetterService, period_label

        svc = LetterService(self.db)
        ctx = svc.recon.load(run_id)
        folder = Path(self.db.data_dir) / "outbox" / f"letters_run{run_id}_{datetime.now():%Y%m%d%H%M%S}"
        made = svc.generate(run_id, folder, None, ("pdf",), reply_days, signatory, user=user)
        vendors = VendorService(self.db).all(ctx.client.id)
        period = period_label(ctx.run.period_from, ctx.run.period_to)
        out = []
        for letter, paths in made:
            v = vendors.get(letter.gstin)
            body = (f"Dear Sir/Madam,\n\nPlease find attached our letter regarding {len(letter.items)} document(s) "
                    f"for {period} that do not appear correctly in our GSTR-2B (GSTIN {ctx.client.gstin}).\n\n"
                    f"Kindly correct them in your GSTR-1 / IFF or let us know, within {reply_days} days.\n\n"
                    f"Regards,\n{signatory or ctx.client.name}\n{ctx.client.name}")
            out.append(self.add_draft("supplier_letter", (v.email if v else "") or "",
                                      f"GST mismatch in {period} – {ctx.client.name} ({ctx.client.gstin})", body,
                                      paths, ctx.client.id, letter.gstin, user=user))
        return out

    def report_drafts(self, period: str, client_ids: list[int], firm_name: str = "",
                      user: str | None = None) -> list[OutboxMail]:
        from ..reports.client_report import build_client_report
        from .reminders import month_name

        folder = Path(self.db.data_dir) / "outbox" / f"reports_{period}_{datetime.now():%Y%m%d%H%M%S}"
        out = []
        for cid in client_ids:
            with self.db.session() as s:
                c = s.get(Client, cid)
                name, email, contact = c.name, c.email or "", c.contact_person or ""
            pdf = build_client_report(self.db, cid, period, folder, firm_name)
            body = (f"Dear {contact or 'Sir/Madam'},\n\nPlease find attached the GST summary of {name} for "
                    f"{month_name(period)}.\n\nRegards,\n{firm_name}").rstrip()
            out.append(self.add_draft("client_report", email, f"GST summary {month_name(period)} – {name}", body,
                                      [pdf], cid, period, user=user))
        return out

    def reminder_drafts(self, requests, signature: str = "", user: str | None = None) -> list[OutboxMail]:
        from .reminders import ReminderService, month_name

        out = []
        for r in requests:
            text = ReminderService.message(r, signature)
            out.append(self.add_draft("reminder", r.email or "",
                                      f"GST {month_name(r.period)} – documents needed from {r.name}", text, [],
                                      r.client_id, r.period, user=user))
        return out
