"""Unexpected errors in the desktop app are never silent.

* A Python error anywhere in the window (a button, a page refresh) is written with its traceback to
  ``fintaxpro.log`` and shown in a message; the program keeps running and the data is safe (every save is one
  database transaction).
* A hard crash (Qt or another native library) is written by :mod:`faulthandler` to ``crash.log``; at the next
  start the user is told and given the file to send to support.
* Qt's own warnings and errors go to the log as well.
"""
from __future__ import annotations

import faulthandler
import logging
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

log = logging.getLogger("fintax_gst.crash")
CRASH_FILE = "crash.log"
_state = {"file": None, "showing": False, "shown": 0, "home": None}
MAX_DIALOGS = 3  # per session: a repeating error must not bury the window under messages


def previous_crash(home: Path) -> Path | None:
    """If the last session ended in a hard crash, the crash report (renamed so it is reported once)."""
    path = home / CRASH_FILE
    try:
        if path.exists() and path.stat().st_size > 0:
            kept = home / f"crash-{datetime.now():%Y%m%d-%H%M%S}.log"
            path.replace(kept)
            return kept
    except OSError:
        pass
    return None


def install(home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    _state["home"] = home
    try:
        _state["file"] = open(home / CRASH_FILE, "a", encoding="utf-8")  # noqa: SIM115 – open for the whole session
        faulthandler.enable(_state["file"], all_threads=True)
    except OSError as exc:
        log.warning("crash report file not available: %s", exc)
    sys.excepthook = _excepthook
    threading.excepthook = lambda a: log.error("Error in background thread %s: %s\n%s", a.thread.name if a.thread
                                               else "?", a.exc_value,
                                               "".join(traceback.format_exception(a.exc_type, a.exc_value,
                                                                                  a.exc_traceback)))
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler

        levels = {QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
                  QtMsgType.QtFatalMsg: logging.CRITICAL}

        def qt_handler(kind, _context, message):
            if kind in levels and "propagateSizeHints" not in message:
                log.log(levels[kind], "Qt: %s", message)

        qInstallMessageHandler(qt_handler)
    except ImportError:
        pass


def _excepthook(exc_type, exc, tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    log.error("Unexpected error: %s\n%s", exc, "".join(traceback.format_exception(exc_type, exc, tb)))
    show_error(exc)


def show_error(exc: BaseException) -> None:
    """Tell the user (at most a few times per session; never while a message is already open)."""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        return
    if QApplication.instance() is None or _state["showing"] or _state["shown"] >= MAX_DIALOGS:
        return
    _state["showing"] = True
    _state["shown"] += 1
    try:
        where = (_state["home"] / "fintaxpro.log") if _state["home"] else "the program's log file"
        QMessageBox.critical(
            QApplication.activeWindow(), "FIN TAX PRO – something went wrong",
            f"An unexpected error occurred:\n\n{type(exc).__name__}: {exc}\n\nYour data is safe – nothing half-saved "
            "is kept. The last action may not have finished; please try it again.\n\nDetails were written to:\n"
            f"{where}\nIf this keeps happening, please send that file to your support contact.")
    finally:
        _state["showing"] = False
