"""Phase 13: update check, client document reminders, one-page client report, backup copy to a cloud folder."""
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from fintax_gst import __version__
from fintax_gst.services.common import ServiceError
from fintax_gst.services.updates import UpdateInfo, UpdateService, version_tuple

INSTALLER = b"MZ" + bytes(range(256)) * 400  # stands in for the 85 MB installer


class FakeReleasePage:
    """A local stand-in for the GitHub release API and the installer download."""

    def __init__(self, version="99.0.0", payload=INSTALLER, digest=None, size=None):
        page = self
        self.version, self.payload = version, payload
        self.digest = hashlib.sha256(payload).hexdigest() if digest is None else digest
        self.size = len(payload) if size is None else size
        self.requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                page.requests.append((self.path, dict(self.headers)))
                if self.path == "/release":
                    name = f"FinTaxPro-Setup-{page.version}.exe"
                    body = json.dumps({"published_at": "2026-11-01T10:00:00Z", "assets": [
                        {"name": "notes.txt", "size": 1, "browser_download_url": "x"},
                        {"name": name, "size": page.size, "digest": f"sha256:{page.digest}",
                         "browser_download_url": f"{page.base}/download/{name}"}]}).encode()
                elif self.path.startswith("/download/"):
                    body = page.payload
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def service(self):
        return UpdateService(f"{self.base}/release", timeout=5)


@pytest.fixture(autouse=True)
def _no_proxy_for_localhost(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")


@pytest.fixture
def release():
    page = FakeReleasePage()
    yield page
    page.server.shutdown()


def test_update_check_and_verified_download(release, tmp_path):
    svc = release.service()
    info = svc.check()
    assert info.version == "99.0.0" and info.size == len(INSTALLER) and info.sha256 == release.digest
    agent = release.requests[0][1]["User-Agent"]
    assert agent == f"FINTAXPRO/{__version__}"  # program name and version only – nothing about the user
    assert svc.check(current="99.0.0") is None and svc.check(current="100.0") is None
    assert version_tuple("1.0.10") > version_tuple("1.0.9")
    path = svc.download(info, tmp_path)
    assert path.name == "FinTaxPro-Setup-99.0.0.exe" and path.read_bytes() == INSTALLER
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize("digest, size, message", [("0" * 64, None, "fingerprint"), (None, len(INSTALLER) + 5,
                                                                                   "incomplete")])
def test_bad_download_is_deleted(tmp_path, digest, size, message):
    page = FakeReleasePage(digest=digest, size=size)
    try:
        svc = page.service()
        with pytest.raises(ServiceError, match=message):
            svc.download(svc.latest(), tmp_path)
        assert not list(tmp_path.iterdir())  # nothing half-downloaded or unverified is left
    finally:
        page.server.shutdown()


def test_update_check_without_internet(tmp_path):
    with pytest.raises(ServiceError, match="Could not reach the download page"):
        UpdateService("http://127.0.0.1:9/release", timeout=2).check()
    page = FakeReleasePage()
    page.payload = b""
    try:
        svc = page.service()
        info = UpdateInfo("9.9.9", "FinTaxPro-Setup-9.9.9.exe", f"{page.base}/nothing", 10, "")
        with pytest.raises(ServiceError):
            svc.download(info, tmp_path)
    finally:
        page.server.shutdown()


# ------------------------------------------------------------------ client document reminders (13B)
def test_client_reminders(db, sample_files):
    from sqlalchemy import select

    from fintax_gst.core.models import ExceptionStatus, Source
    from fintax_gst.db.models import AuditLog, ClientReminder
    from fintax_gst.samples import CLIENT, gstin
    from fintax_gst.services.clients import ClientService
    from fintax_gst.services.imports import ImportService
    from fintax_gst.services.reconciliation import ReconciliationService
    from fintax_gst.services.reminders import ReminderService

    clients = ClientService(db)
    demo = clients.create(**CLIENT)
    clients.update(demo.id, "admin", mobile="9820012345", email="accounts@ganesh.example", staff="priya")
    other = clients.create(gstin("29", "AACCB5678L"), None, name="Bangalore Electronics LLP")
    ImportService(db).import_file(demo.id, sample_files["books_april"], Source.BOOKS)
    ImportService(db).import_file(demo.id, sample_files["gstr2b_april_json"], Source.GSTR2B)
    recon = ReconciliationService(db)
    run = recon.run(demo.id, "2025-04")
    lines = recon.load(run).result.lines
    missing = next(ln for ln in lines if ln.books is None and ln.gstr2b)  # in GSTR-2B, not in the books
    wrong = next(ln for ln in lines if ln.books and ln.gstr2b and ln.category.value != "Fully Matched")
    recon.update_line(run, missing.line_no, "priya", status=ExceptionStatus.CLIENT_CLARIFICATION.value,
                      remarks="Not in your purchase register – was it received?")
    recon.update_line(run, wrong.line_no, "priya", status=ExceptionStatus.BOOKS_CORRECTION.value)

    svc = ReminderService(db)
    reqs = {r.name: r for r in svc.requests("2025-04")}
    assert reqs[other.name].documents == ["Purchase register for April 2025"]
    r = reqs[CLIENT["name"]]
    assert r.documents == [] and len(r.clarify) == 1 and len(r.correct) == 1
    assert r.clarify[0].invoice_no == missing.gstr2b.invoice_no
    text = svc.message(r, "CA R. Sharma")
    assert text.startswith(f"Dear {CLIENT['contact_person']},") and "was it received?" in text
    assert "Please correct these entries" in text and text.endswith("CA R. Sharma")
    assert svc.whatsapp(r, "Hi").startswith("https://wa.me/919820012345?text=Hi")
    assert svc.mailto(r, "a b").startswith("mailto:accounts%40ganesh.example?subject=GST%20April%202025")
    assert [x.name for x in svc.requests("2025-04", staff="priya")] == [CLIENT["name"]]
    assert "Sales register for April 2025" in svc.requests("2025-04", ask_sales=True)[0].documents

    svc.record(r, "whatsapp", "priya")
    again = {x.name: x for x in svc.requests("2025-04")}[CLIENT["name"]]
    assert again.times_reminded == 1 and again.last_reminded is not None
    with db.session() as s:
        row = s.scalars(select(ClientReminder)).one()
        assert row.channel == "whatsapp" and len(row.items_json) > 10
        assert s.scalars(select(AuditLog).where(AuditLog.action == "REMINDER")).one().user == "priya"
    with pytest.raises(ServiceError):
        svc.record(r, "sms")
    # a client deleted for good takes its reminder log with it
    from fintax_gst.services.auth import SETUP_SESSION
    from fintax_gst.services.security import SecurityService

    SecurityService(db).purge_client(demo.id, CLIENT["gstin"], SETUP_SESSION)
    with db.session() as s:
        assert not s.scalars(select(ClientReminder)).all()


def test_cli_reminders(tmp_path, capsys):
    from fintax_gst.cli import main
    from fintax_gst.samples import CLIENT

    dbp = str(tmp_path / "cli.db")
    assert main(["--db", dbp, "client", "add", "--name", CLIENT["name"], "--gstin", CLIENT["gstin"]]) == 0
    capsys.readouterr()
    assert main(["--db", dbp, "reminders", "--period", "2025-04", "--signature", "CA Office"]) == 0
    out = capsys.readouterr().out
    assert "Purchase register for April 2025" in out and "CA Office" in out


# ------------------------------------------------------------------ one-page client report (13C)
def test_client_report(db, tmp_path):
    from datetime import date

    from pypdf import PdfReader

    from fintax_gst.reports.client_report import build_client_report, build_reports
    from fintax_gst.samples import CLIENT, gstin
    from fintax_gst.services.batch import BatchService, write_example
    from fintax_gst.services.clients import ClientService

    BatchService(db).run(write_example(tmp_path / "batch"), create_clients=True)
    empty = ClientService(db).create(gstin("29", "AACCB5678L"), None, name="Bangalore <Electronics> & Co")
    paths = build_reports(db, "2025-04", tmp_path / "out", firm_name="R. Sharma & Co.", today=date(2025, 5, 15))
    assert sorted(p.name for p in paths) == [f"{CLIENT['gstin']}_2025-04_GST_summary.pdf",
                                             "29AACCB5678L1Z2_2025-04_GST_summary.pdf"]
    full = PdfReader(str(tmp_path / "out" / f"{CLIENT['gstin']}_2025-04_GST_summary.pdf"))
    assert len(full.pages) == 1  # always one page
    text = full.pages[0].extract_text()
    for expected in ("GST summary – April 2025", "ITC as per your purchase register", "ITC claimed in GSTR-3B",
                     "Suppliers to follow up", "Kovai Textiles", "GSTR-1", "Not filed – overdue",
                     "Prepared by R. Sharma & Co. on 15-05-2025", "As reported in GSTR-1"):
        assert expected in text, expected
    blank = PdfReader(str(build_client_report(db, empty.id, "2025-04", tmp_path / "one", today=date(2025, 5, 15))))
    t = blank.pages[0].extract_text()
    assert "Bangalore <Electronics> & Co" in t and "Not reconciled yet" in t and "Purchase register for April" in t
    with pytest.raises(ServiceError):
        build_client_report(db, 999, "2025-04", tmp_path)
    with pytest.raises(ServiceError):
        build_reports(db, "Apr", tmp_path)


def test_cli_client_report(tmp_path, capsys):
    from fintax_gst.cli import main
    from fintax_gst.samples import CLIENT

    dbp = str(tmp_path / "cli.db")
    assert main(["--db", dbp, "client", "add", "--name", CLIENT["name"], "--gstin", CLIENT["gstin"]]) == 0
    assert main(["--db", dbp, "client-report", "--period", "2025-04", "--client", CLIENT["gstin"], "--out",
                 str(tmp_path / "r")]) == 0
    assert "GST_summary.pdf" in capsys.readouterr().out and len(list((tmp_path / "r").iterdir())) == 1


# ------------------------------------------------------------------ backup copy to a cloud folder (13D)
def test_backup_copy_to_cloud_folder(db, tmp_path, sample_files):
    import sqlite3

    from sqlalchemy import select

    from fintax_gst.db.models import AuditLog
    from fintax_gst.samples import CLIENT
    from fintax_gst.services.auth import SETUP_SESSION, PermissionDenied, Session
    from fintax_gst.services.clients import ClientService
    from fintax_gst.services.security import SecurityService

    ClientService(db).create(**CLIENT)
    sec = SecurityService(db)
    cloud = tmp_path / "OneDrive"
    assert sec.cloud_copy() is None
    with pytest.raises(ServiceError, match="not turned on"):
        sec.copy_to_cloud()
    with pytest.raises(ServiceError, match="8 characters"):
        sec.configure_cloud_copy(tmp_path, "short", SETUP_SESSION)
    with pytest.raises(ServiceError, match="not a folder"):
        sec.configure_cloud_copy(cloud, "long enough pw", SETUP_SESSION)
    with pytest.raises(PermissionDenied):
        sec.configure_cloud_copy(tmp_path, "long enough pw", Session("v", "viewer", "v"))
    cloud.mkdir()
    sec.configure_cloud_copy(cloud, "long enough pw", SETUP_SESSION)

    made = sec.auto_backup(force=True)  # every automatic backup is also copied, encrypted
    copies = sorted(cloud.glob("FinTaxPro-backup-*.ftpbk"))
    assert made and len(copies) == 1 and not list(cloud.glob("*.part"))
    raw = copies[0].read_bytes()
    assert raw.startswith(b"FTPBK1") and b"SQLite format" not in raw and CLIENT["name"].encode() not in raw
    with pytest.raises(ServiceError, match="Wrong password"):
        sec.decrypt_backup(copies[0], "wrong password", tmp_path / "x.db")
    plain = sec.decrypt_backup(copies[0], "long enough pw", tmp_path / "restored.db")
    con = sqlite3.connect(plain)
    assert con.execute("select name from clients").fetchone()[0] == CLIENT["name"]
    con.close()
    status = sec.cloud_copy()["status"]
    assert status["ok"] and status["file"] == copies[0].name
    # the key is never written to the audit log
    with db.session() as s:
        entries = [json.loads(a.details_json) for a in s.scalars(select(AuditLog))]
    assert '"key"' not in json.dumps(entries)
    assert {"after": {"dir": str(cloud)}} in entries  # the folder is recorded (Windows paths too)

    # only the newest copies of this computer are kept
    sec.set_setting("backup_keep", 2, SETUP_SESSION)
    import time

    for _ in range(3):
        time.sleep(1.1)  # copies are named by the second
        sec.copy_to_cloud()
    assert len(list(cloud.glob("FinTaxPro-backup-*.ftpbk"))) == 2

    # folder gone (e.g. OneDrive signed out): start-up still works, the problem is shown
    import shutil

    shutil.rmtree(cloud)
    assert sec.auto_backup(force=True) is not None
    status = sec.cloud_copy()["status"]
    assert status["ok"] is False and "not available" in status["message"]
    sec.disable_cloud_copy(SETUP_SESSION)
    assert sec.cloud_copy() is None
