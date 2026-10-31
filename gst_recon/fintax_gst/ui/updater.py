"""Update check in the desktop app: a notice bar when a newer version is published, and the download."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QWidget

from .. import __version__
from ..services.common import ServiceError
from ..services.updates import UpdateInfo, UpdateService
from .workers import run_task

log = logging.getLogger(__name__)
CHECK_EVERY = timedelta(hours=24)
KEY_ENABLED, KEY_LAST = "update_check", "update_last_check"


def auto_check_enabled(qsettings) -> bool:
    return str(qsettings.value(KEY_ENABLED, "true")).lower() in ("true", "1")


def download_folder() -> Path:
    downloads = Path.home() / "Downloads"
    return downloads if downloads.is_dir() else Path.home()


class _Relay(QObject):
    """Carries the result of the background check to the window's thread."""

    found = Signal(object)  # UpdateInfo or None
    failed = Signal(str)


class UpdateBar(QFrame):
    """Shown under the header when a newer version is available."""

    def __init__(self, parent: QWidget, service_factory=UpdateService):
        super().__init__(parent)
        self.setObjectName("UpdateBar")
        self.setStyleSheet("QFrame#UpdateBar { background: #E3F2FD; border-bottom: 1px solid #90CAF9; }")
        self.factory = service_factory
        self.info: UpdateInfo | None = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 6, 18, 6)
        self.text = QLabel()
        self.install_btn = QPushButton("Download and install")
        self.install_btn.clicked.connect(lambda: self.download_and_install())
        later = QPushButton("Later")
        later.clicked.connect(self.hide)
        lay.addWidget(self.text, 1)
        lay.addWidget(self.install_btn)
        lay.addWidget(later)
        self.relay = _Relay()
        self.relay.found.connect(self._found)
        self.relay.failed.connect(lambda msg: log.info("update check failed: %s", msg))
        self.hide()

    # ----------------------------------------------------------------- check
    def check_in_background(self, qsettings) -> threading.Thread | None:
        """Check at most once a day, without blocking the window. Returns the thread (for tests)."""
        if not auto_check_enabled(qsettings):
            return None
        try:
            last = datetime.fromisoformat(str(qsettings.value(KEY_LAST, "")))
        except ValueError:
            last = None
        if last and datetime.now() - last < CHECK_EVERY:
            return None
        qsettings.setValue(KEY_LAST, datetime.now().isoformat(timespec="seconds"))

        def work():
            try:
                self.relay.found.emit(self.factory().check())
            except ServiceError as exc:
                self.relay.failed.emit(str(exc))

        t = threading.Thread(target=work, name="update-check", daemon=True)
        t.start()
        return t

    def check_now(self, parent: QWidget) -> UpdateInfo | None:
        """Manual check from the Settings page; tells the user the outcome."""
        task = run_task(parent, "Checking for updates", self.factory().check, cancellable=False)
        if not task.ok:
            QMessageBox.information(parent, "Updates", task.message)
            return None
        if task.result_value is None:
            QMessageBox.information(parent, "Updates", f"You have the latest version ({__version__}).")
            return None
        self._found(task.result_value)
        return task.result_value

    def _found(self, info: UpdateInfo | None) -> None:
        if info is None:
            return
        self.info = info
        self.text.setText(f"<b>FIN TAX PRO {info.version}</b> is available (you have {__version__}). "
                          "Your data is kept when you install it.")
        self.show()

    # -------------------------------------------------------------- install
    def download_and_install(self, folder: str | Path | None = None, launch: bool = True) -> Path | None:
        if self.info is None:
            return None
        info = self.info
        task = run_task(self.window(), f"Downloading FIN TAX PRO {info.version}", self.factory().download, info,
                        folder or download_folder())
        if not task.ok:
            QMessageBox.warning(self.window(), "Update", task.message)
            return None
        path: Path = task.result_value
        if not launch:
            return path
        answer = QMessageBox.question(
            self.window(), "Update",
            f"FIN TAX PRO {info.version} has been downloaded and checked:\n{path}\n\nInstall it now? FIN TAX PRO "
            "will close; your clients and data are kept.\n\nIf Windows says 'Windows protected your PC', click "
            "More info, then Run anyway.")
        if answer != QMessageBox.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
            return path
        start_installer(path)
        QApplication.quit()
        return path


def start_installer(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # noqa: S606 – the verified installer the user chose to run
    else:  # the installer is for Windows; elsewhere just show where it is
        subprocess.Popen(["xdg-open", str(path.parent)])  # noqa: S603,S607
