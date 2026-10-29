"""FastAPI application: read-only dashboards and report downloads for phones and browsers.

Security
--------
* Every page needs a FIN TAX PRO login (same users, roles and lockout as the desktop).
  When no users exist the server only accepts connections from this computer.
* The session cookie is HMAC-signed, HttpOnly, SameSite=Strict, expires after
  ``SESSION_MINUTES`` and is marked Secure when served over HTTPS.
* Pages are read-only; nothing can be imported, changed or deleted from the web.
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

    def page(name: str, request: Request, user: Session | None, status: int = 200, **ctx) -> HTMLResponse:
        html = env.get_template(name).render(user=user, role=ROLES.get(user.role, user.role) if user else "", **ctx)
        return HTMLResponse(html, status_code=status)

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
        return page("dashboard", request, user, fy=fy, fys=fys, clients=clients, counts=counts,
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
