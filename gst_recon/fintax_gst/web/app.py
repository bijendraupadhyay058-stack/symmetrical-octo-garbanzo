"""FastAPI application: read-only dashboards and report downloads for phones and browsers.

Security
--------
* Every page needs a FIN TAX PRO login (same users, roles and lockout as the desktop).
  When no users exist the server only accepts connections from this computer.
* The session cookie is HMAC-signed, HttpOnly, SameSite=Strict, expires after
  ``SESSION_MINUTES`` and is marked Secure when served over HTTPS.
* Pages are read-only. The one exception is file upload, which is off until an
  administrator enables it (setting ``web_uploads``): an upload is previewed first and
  saved only on confirmation, by a user with the *import* permission, through the same
  import pipeline as the desktop. Every form carries a CSRF token bound to the session.
* Responses are not cached (``Cache-Control: no-store``) and a strict Content Security
  Policy is sent; there are no external scripts, fonts or trackers.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import tempfile
import time
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from jinja2 import DictLoader, Environment, select_autoescape
from starlette.background import BackgroundTask

from .. import __version__
from ..compliance.summary import RAG_LABEL
from ..core.models import fy_of, relabel, side_labels
from ..core.money import fmt_inr
from ..db.database import Database
from ..engine.summary import category_summary, dashboard, is_pending, supplier_summary
from ..services.auth import ROLES, SETUP_SESSION, AuthService, Session
from ..services.common import ServiceError, audit
from ..services.compliance import ComplianceService
from ..services.reconciliation import ReconciliationService, months_between
from .templates import ICON, TEMPLATES

SESSION_MINUTES = 30
COOKIE = "ftp_session"
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def _money(v) -> str:
    return "" if v is None else fmt_inr(v)


class Signer:
    def __init__(self, secret: bytes):
        self.secret = secret

    def dumps(self, data: dict) -> str:
        body = base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode()
        sig = hmac.new(self.secret, body.encode(), hashlib.sha256).hexdigest()
        return f"{body}.{sig}"

    def loads(self, token: str) -> dict | None:
        body, _, sig = (token or "").rpartition(".")
        if not body or not hmac.compare_digest(sig, hmac.new(self.secret, body.encode(), hashlib.sha256).hexdigest()):
            return None
        try:
            data = json.loads(base64.urlsafe_b64decode(body.encode()))
        except ValueError:
            return None
        return data if data.get("exp", 0) > time.time() else None


MAX_UPLOAD_MB = 25
PENDING_MINUTES = 15
UPLOAD_SOURCES = [("BOOKS", "Purchase register"), ("GSTR2B", "GSTR-2B"), ("GSTR2A", "GSTR-2A"),
                  ("SALES", "Sales register"), ("GSTR1", "GSTR-1"), ("IMS", "IMS download"),
                  ("GSTR3B", "GSTR-3B"), ("GSTR8A", "GSTR-9 Table 8A document details")]
UPLOAD_SUFFIXES = {".xlsx", ".xlsm", ".xls", ".csv", ".json", ".zip"}


def _safe_name(name: str) -> str:
    import re

    name = Path(name or "upload").name
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")[:120] or "upload"


def create_app(db: Database, secret: bytes | None = None, https: bool = False) -> FastAPI:
    app = FastAPI(title="FIN TAX PRO", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    env = Environment(loader=DictLoader(TEMPLATES), autoescape=select_autoescape(default=True))
    env.globals.update(money=_money, rag=RAG_LABEL)
    signer = Signer(secret or secrets.token_bytes(32))
    auth = AuthService(db)
    recon = ReconciliationService(db)
    compliance = ComplianceService(db)

    @app.middleware("http")
    async def headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = ("default-src 'self'; style-src 'self' 'unsafe-inline'; "
                                                   "img-src 'self' data:; form-action 'self'; frame-ancestors 'none'")
        return resp

    def session_of(request: Request) -> Session | None:
        if not auth.has_users():
            host = request.client.host if request.client else ""
            return SETUP_SESSION if host in LOCAL_HOSTS else None
        data = signer.loads(request.cookies.get(COOKIE, ""))
        if not data:
            return None
        return Session(data["u"], data["r"], data.get("n", ""))

    def uploads_enabled() -> bool:
        from ..services.security import SecurityService

        return bool(SecurityService(db).setting("web_uploads"))

    def page(name: str, request: Request, user: Session | None, status: int = 200, **ctx) -> HTMLResponse:
        can_upload = bool(user and user.can("import") and uploads_enabled())
        html = env.get_template(name).render(user=user, role=ROLES.get(user.role, user.role) if user else "",
                                             can_upload=can_upload, **ctx)
        return HTMLResponse(html, status_code=status)

    def csrf_of(request: Request) -> str:
        token = request.cookies.get(COOKIE, "") or "local-setup"
        return hmac.new(signer.secret, b"csrf|" + token.encode(), hashlib.sha256).hexdigest()

    def csrf_ok(request: Request, value: str) -> bool:
        return hmac.compare_digest(value or "", csrf_of(request))

    def guard(request: Request, permission: str = "view"):
        user = session_of(request)
        if user is None:
            return None, RedirectResponse("/login", status_code=303)
        if not user.can(permission):
            return None, HTMLResponse("Not permitted for your role", status_code=403)
        return user, None

    def file_response(path: Path, media: str, tmpdir: tempfile.TemporaryDirectory) -> FileResponse:
        return FileResponse(path, media_type=media, filename=path.name, background=BackgroundTask(tmpdir.cleanup))

    # ------------------------------------------------------------- login
    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request):
        return page("login", request, None)

    @app.post("/login")
    def login(request: Request, username: str = Form(...), password: str = Form(...)):
        try:
            s = auth.login(username, password)
        except ServiceError as exc:
            return page("login", request, None, status=401, error=str(exc))
        resp = RedirectResponse("/", status_code=303)
        token = signer.dumps({"u": s.username, "r": s.role, "n": s.full_name, "exp": time.time() + SESSION_MINUTES * 60})
        resp.set_cookie(COOKIE, token, max_age=SESSION_MINUTES * 60, httponly=True, samesite="strict", secure=https)
        return resp

    @app.get("/logout")
    def logout():
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(COOKIE)
        return resp

    # -------------------------------------------------------- dashboards
    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, fy: str | None = None):
        user, denied = guard(request)
        if denied:
            return denied
        fy = fy or fy_of(date.today())
        start = int(fy_of(date.today())[:4])
        fys = [f"{y}-{str(y + 1)[-2:]}" for y in range(start, start - 6, -1)]
        if fy not in fys:
            fys.insert(0, fy)
        clients = compliance.annual_dashboard(fy)
        counts = {k: sum(1 for c in clients if c.rag == k) for k in RAG_LABEL}
        from ..services.calendar import CalendarService

        upcoming = [u for u in CalendarService(db).upcoming(days=21) if u.status != "imported"][:30]
        return page("dashboard", request, user, fy=fy, fys=fys, clients=clients, counts=counts, upcoming=upcoming,
                    pending=sum(c.pending for c in clients), can_export=user.can("export"))

    @app.get("/client/{client_id}", response_class=HTMLResponse)
    def client(request: Request, client_id: int, fy: str | None = None):
        user, denied = guard(request)
        if denied:
            return denied
        try:
            c = compliance.client_summary(client_id, fy or fy_of(date.today()))
        except ServiceError:
            return HTMLResponse("Client not found", status_code=404)
        runs = sorted(recon.list_runs(client_id), key=lambda r: r.id, reverse=True)[:50]
        return page("client", request, user, c=c, runs=runs, can_export=user.can("export"))

    @app.get("/run/{run_id}", response_class=HTMLResponse)
    def run(request: Request, run_id: int):
        user, denied = guard(request)
        if denied:
            return denied
        try:
            ctx = recon.load(run_id)
        except ServiceError:
            return HTMLResponse("Run not found", status_code=404)
        comparison = ctx.run.comparison
        lab = lambda t: relabel(t, comparison)  # noqa: E731
        left, right = side_labels(comparison)
        lines = ctx.result.lines
        d = dashboard(lines)
        cards = [(lab("Total Purchase Invoices"), d["total_purchase_invoices"]),
                 ("Matched", f"{d['match_percentage']}%"), ("Pending review", d["pending_cases"]),
                 (lab("ITC as per Books"), "₹" + fmt_inr(d["itc_as_per_books"])),
                 (lab("ITC as per GSTR-2B"), "₹" + fmt_inr(d["itc_as_per_gstr2b"])),
                 (lab("ITC at risk"), "₹" + fmt_inr(d["itc_at_risk"]))]
        cats = [(lab(r.category.value), r.lines, r.books.itc, r.gstr2b.itc) for r in category_summary(lines) if r.lines]
        pend = [ln for ln in lines if is_pending(ln) and ln.category.name != "FULLY_MATCHED"]
        liability = None
        if comparison.startswith("SALES"):
            from ..services.outward import OutwardService
            liability = OutwardService(db).liability(ctx.client.id, months_between(ctx.run.period_from,
                                                                                   ctx.run.period_to))
        return page("run", request, user, run=ctx.run, client=ctx.client, left=left, right=right, cards=cards,
                    categories=cats, suppliers=supplier_summary(lines)[:25],
                    pending=[(ln, ln.books or ln.gstr2b) for ln in pend[:200]], pending_total=len(pend),
                    party="Customer" if comparison.startswith("SALES") else "Supplier", relabel=lab,
                    liability=liability, can_export=user.can("export"))

    # ---------------------------------------------------------- downloads
    @app.get("/run/{run_id}/report.{fmt}")
    def run_report(request: Request, run_id: int, fmt: str):
        user, denied = guard(request, "export")
        if denied:
            return denied
        if fmt not in ("xlsx", "pdf"):
            return Response(status_code=404)
        from ..services.reports import export_run

        tmp = tempfile.TemporaryDirectory()
        paths = export_run(db, run_id, tmp.name, pdf=(fmt == "pdf"), user=f"{user.username} (web)")
        path = next(p for p in paths if p.suffix == f".{fmt}")
        media = "application/pdf" if fmt == "pdf" else \
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return file_response(path, media, tmp)

    @app.get("/client/{client_id}/compliance.pdf")
    def client_pdf(request: Request, client_id: int, fy: str | None = None):
        user, denied = guard(request, "export")
        if denied:
            return denied
        from ..reports.compliance_report import export_client_pdf

        try:
            c = compliance.client_summary(client_id, fy or fy_of(date.today()))
        except ServiceError:
            return Response(status_code=404)
        tmp = tempfile.TemporaryDirectory()
        path = export_client_pdf(c, Path(tmp.name) / f"Compliance_{c.gstin}_{c.fy}.pdf")
        with db.session() as s:
            audit(s, "EXPORT", "compliance_summary", client_id, {"fy": c.fy, "via": "web"}, user.username, client_id)
        return file_response(path, "application/pdf", tmp)

    @app.get("/dashboard.xlsx")
    def dashboard_xlsx(request: Request, fy: str | None = None):
        user, denied = guard(request, "export")
        if denied:
            return denied
        from ..reports.compliance_report import export_compliance_excel

        fy = fy or fy_of(date.today())
        tmp = tempfile.TemporaryDirectory()
        path = export_compliance_excel(compliance.annual_dashboard(fy), fy, Path(tmp.name) / f"GST_Dashboard_{fy}.xlsx")
        with db.session() as s:
            audit(s, "EXPORT", "annual_dashboard", fy, {"via": "web"}, user.username)
        return file_response(path, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", tmp)

    # ------------------------------------------------------------ uploads
    pending: dict[str, dict] = {}  # token -> {user, client_id, kind, preview, dir, expires}

    def upload_guard(request: Request):
        user, denied = guard(request, "import")
        if denied:
            return None, denied
        if not uploads_enabled():
            return None, HTMLResponse("Uploads from the web view are switched off (Security settings).",
                                      status_code=403)
        return user, None

    def drop(token: str) -> None:
        import shutil

        item = pending.pop(token, None)
        if item and not item.get("kept"):
            shutil.rmtree(item["dir"], ignore_errors=True)

    def expire() -> None:
        for token in [t for t, v in pending.items() if v["expires"] < time.time()]:
            drop(token)

    def clients_list():
        from ..services.clients import ClientService

        return ClientService(db).list()

    @app.get("/upload", response_class=HTMLResponse)
    def upload_form(request: Request, client_id: int | None = None):
        user, denied = upload_guard(request)
        if denied:
            return denied
        return page("upload", request, user, clients=clients_list(), sources=UPLOAD_SOURCES, client_id=client_id,
                    csrf=csrf_of(request), max_mb=MAX_UPLOAD_MB)

    @app.post("/upload", response_class=HTMLResponse)
    async def upload(request: Request):
        user, denied = upload_guard(request)
        if denied:
            return denied
        form = await request.form()
        if not csrf_ok(request, str(form.get("csrf", ""))):
            return HTMLResponse("Invalid form token – reload the page", status_code=400)
        expire()

        def again(msg: str, status: int = 400):
            return page("upload", request, user, status=status, clients=clients_list(), sources=UPLOAD_SOURCES,
                        client_id=None, csrf=csrf_of(request), max_mb=MAX_UPLOAD_MB, error=msg)

        upload_file = form.get("file")
        source = str(form.get("source", ""))
        period = str(form.get("period", "")).strip() or None
        try:
            client_id = int(str(form.get("client_id", "")))
        except ValueError:
            return again("Choose a client")
        if source not in dict(UPLOAD_SOURCES) or upload_file is None or not getattr(upload_file, "filename", ""):
            return again("Choose a file and its type")
        name = _safe_name(upload_file.filename)
        if Path(name).suffix.lower() not in UPLOAD_SUFFIXES:
            return again("Use an Excel, CSV, JSON or ZIP file")
        data = await upload_file.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
        if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
            return again(f"File larger than {MAX_UPLOAD_MB} MB")
        token = secrets.token_urlsafe(18)
        folder = db.data_dir / "uploads" / str(client_id) / token
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_bytes(data)
        from ..services.clients import ClientService

        try:
            client = ClientService(db).get(client_id)
            if client is None:
                raise ServiceError("Client not found")
            if source == "GSTR3B":
                from ..services.gstr3b import Gstr3bService

                pv = Gstr3bService(db).preview(path, period)
                figures = [("Periods", ", ".join(pv.periods) or "–"),
                           ("Table rows", sum(len(t) for t in pv.entries.values()))]
                ctx = dict(layout=pv.layout, period=", ".join(pv.periods), warnings=pv.warnings, issues=[],
                           blocked=None if pv.entries else "No GSTR-3B values found in the file")
            else:
                from ..core.models import Source
                from ..services.imports import ImportService

                pv = ImportService(db).preview(client_id, path, Source(source), period)
                new = len(pv.new_records)
                figures = [("Documents", len(pv.records)), ("New documents", new),
                           ("Already imported", len(pv.records) - new), ("Rows rejected", pv.rejected_rows),
                           ("Duplicates in file", pv.count("duplicate"))]
                blocked = None
                if pv.already_imported_file_id:
                    blocked = f"This file was already imported (import #{pv.already_imported_file_id})."
                elif not new and not pv.outward_summary and not pv.other_itc:
                    blocked = "Nothing new to import."
                ctx = dict(layout=pv.layout_label, period=pv.period, warnings=pv.file_warnings,
                           issues=[i for i in pv.issues if i.severity in ("error", "warning", "duplicate")][:50],
                           blocked=blocked)
        except Exception as exc:  # noqa: BLE001 - shown to the user; the upload is removed
            import shutil

            shutil.rmtree(folder, ignore_errors=True)
            from ..importers.pipeline import MappingRequired

            if isinstance(exc, MappingRequired):
                return again("The headings of this file were not recognised. Map its columns once in the desktop "
                             "app (the mapping is saved as a template), then upload again.", 422)
            if isinstance(exc, (ServiceError, ValueError, FileNotFoundError)) or exc.__class__.__name__ == \
                    "UnsupportedFileError":
                return again(str(exc), 422)
            raise
        pending[token] = {"user": user.username, "client_id": client_id, "kind": source, "preview": pv,
                          "dir": folder, "path": path, "period": period,
                          "expires": time.time() + PENDING_MINUTES * 60}
        return page("upload_preview", request, user, client=client, file_name=name, token=token,
                    csrf=csrf_of(request), figures=figures, **ctx)

    def take(request: Request, token: str, user: Session):
        expire()
        item = pending.get(token)
        if item is None or item["user"] != user.username:
            return None
        return item

    @app.post("/upload/{token}/commit", response_class=HTMLResponse)
    def upload_commit(request: Request, token: str, csrf: str = Form("")):
        user, denied = upload_guard(request)
        if denied:
            return denied
        if not csrf_ok(request, csrf):
            return HTMLResponse("Invalid form token – reload the page", status_code=400)
        item = take(request, token, user)
        if item is None:
            return HTMLResponse("This preview has expired – upload the file again.", status_code=410)
        try:
            if item["kind"] == "GSTR3B":
                from ..services.gstr3b import Gstr3bService

                sf, _ = Gstr3bService(db).import_file(item["client_id"], item["path"], item["period"],
                                                      f"{user.username} (web)")
            else:
                from ..services.imports import ImportService

                sf = ImportService(db).commit(item["client_id"], item["preview"], f"{user.username} (web)")
        except ServiceError as exc:
            drop(token)
            return HTMLResponse(str(exc), status_code=409)
        item["kept"] = True  # the saved file stays as the import's source file
        pending.pop(token, None)
        return page("done", request, user, title="Import saved", client_id=item["client_id"],
                    message=f"Import #{sf.id} saved: {sf.documents_imported} document(s) or values from "
                            f"{sf.file_name}. Reconcile the period in the desktop app.")

    @app.post("/upload/{token}/discard")
    def upload_discard(request: Request, token: str, csrf: str = Form("")):
        user, denied = upload_guard(request)
        if denied:
            return denied
        if not csrf_ok(request, csrf):
            return HTMLResponse("Invalid form token – reload the page", status_code=400)
        if take(request, token, user) is not None:
            drop(token)
        return RedirectResponse("/upload", status_code=303)

    # ------------------------------------------------------------- PWA
    @app.get("/manifest.webmanifest")
    def manifest():
        return JSONResponse({"name": "FIN TAX PRO", "short_name": "FinTaxPro", "start_url": "/", "display": "standalone",
                             "background_color": "#F4F7FA", "theme_color": "#1F3864",
                             "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}]},
                            media_type="application/manifest+json")

    @app.get("/icon.svg")
    def icon():
        return Response(ICON, media_type="image/svg+xml")

    @app.get("/healthz")
    def health():
        return {"ok": True, "version": __version__}

    return app


def serve(db: Database, host: str = "127.0.0.1", port: int = 8765, certfile: str | None = None,
          keyfile: str | None = None, allow_http_lan: bool = False) -> None:
    """Run the web interface. Anything other than this computer needs users and HTTPS
    (or an explicit ``allow_http_lan`` for a trusted office network)."""
    import uvicorn

    local = host in LOCAL_HOSTS
    if not local and not AuthService(db).has_users():
        raise ServiceError("Create at least one user before serving the web interface to other devices")
    if not local and not certfile and not allow_http_lan:
        raise ServiceError("Serving to other devices needs HTTPS (--certfile/--keyfile) or --allow-http-lan")
    app = create_app(db, https=bool(certfile))
    uvicorn.run(app, host=host, port=port, ssl_certfile=certfile, ssl_keyfile=keyfile, log_level="warning",
                server_header=False)
