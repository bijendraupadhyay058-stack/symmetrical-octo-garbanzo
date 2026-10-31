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
