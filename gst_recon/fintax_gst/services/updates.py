"""Check for a newer FIN TAX PRO installer and download it.

The check reads the public release page of the project on GitHub (``RELEASE_API``) and compares the
version in the installer's file name with the running version. Nothing about the user, the computer or
the clients is sent: the request carries only the program name and version (User-Agent).

A download is written to ``<name>.part`` and renamed only after its size and SHA-256 fingerprint match
what the release page publishes, so a broken or altered download is never offered for installation.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .. import PRODUCT_NAME, __version__
from .common import ServiceError

RELEASE_API = ("https://api.github.com/repos/bijendraupadhyay058-stack/symmetrical-octo-garbanzo/releases/tags/"
               "fintaxpro-latest")
_ASSET = re.compile(r"^FinTaxPro-Setup-(\d+(?:\.\d+){1,3})\.exe$")
_CHUNK = 256 * 1024


def version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(x) for x in text.split("."))


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    file_name: str
    url: str
    size: int
    sha256: str  # empty when the release page publishes no fingerprint
    published: str = ""


class UpdateService:
    def __init__(self, api: str = RELEASE_API, timeout: float = 15):
        self.api, self.timeout = api, timeout

    def _open(self, url: str):
        req = urllib.request.Request(url, headers={"User-Agent": f"{PRODUCT_NAME.replace(' ', '')}/{__version__}",
                                                   "Accept": "application/vnd.github+json"})
        return urllib.request.urlopen(req, timeout=self.timeout)  # noqa: S310 – fixed https address

    def latest(self) -> UpdateInfo:
        """The installer currently published on the download page."""
        try:
            with self._open(self.api) as r:
                data = json.loads(r.read().decode("utf-8"))
        except (OSError, ValueError) as exc:
            raise ServiceError(f"Could not reach the download page ({exc}). Check the internet connection, "
                               "or try again later.") from None
        for a in data.get("assets", []):
            m = _ASSET.match(a.get("name", ""))
            if m:
                digest = a.get("digest") or ""
                return UpdateInfo(m.group(1), a["name"], a["browser_download_url"], int(a.get("size") or 0),
                                  digest.removeprefix("sha256:") if digest.startswith("sha256:") else "",
                                  data.get("published_at", ""))
        raise ServiceError("The download page has no installer at the moment – try again later.")

    def check(self, current: str = __version__) -> UpdateInfo | None:
        """The newer version available, or None when this one is up to date."""
        info = self.latest()
        return info if version_tuple(info.version) > version_tuple(current) else None

    def download(self, info: UpdateInfo, folder: str | Path, progress=None, cancel=None) -> Path:
        """Download and verify the installer; returns its path."""
        progress = progress or (lambda pct, msg: None)
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / info.file_name
        part = target.with_name(target.name + ".part")
        digest, done = hashlib.sha256(), 0
        try:
            with self._open(info.url) as r, part.open("wb") as fh:
                while chunk := r.read(_CHUNK):
                    if cancel:
                        cancel.check()
                    fh.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if info.size:
                        progress(int(100 * done / info.size), f"Downloading {info.file_name} – "
                                                              f"{done / 1e6:.0f} of {info.size / 1e6:.0f} MB")
        except OSError as exc:
            part.unlink(missing_ok=True)
            raise ServiceError(f"The download was interrupted ({exc}). Please try again.") from None
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        if info.size and done != info.size:
            part.unlink(missing_ok=True)
            raise ServiceError(f"The download is incomplete ({done} of {info.size} bytes). Please try again.")
        if info.sha256 and digest.hexdigest() != info.sha256.lower():
            part.unlink(missing_ok=True)
            raise ServiceError("The downloaded installer does not match the fingerprint on the download page, so "
                               "it was deleted. Please try again; if it happens again, download it from the page "
                               "yourself.")
        part.replace(target)
        progress(100, "Download complete")
        return target
