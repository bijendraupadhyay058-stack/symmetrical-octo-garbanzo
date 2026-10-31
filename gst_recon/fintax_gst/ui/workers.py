"""Background execution with progress and safe cancellation.

Long operations (import, reconciliation, export) run on a QThread so the UI stays
responsive. Services write inside one transaction and check the CancelToken
between batches, so Cancel never leaves partial data behind.
"""
from __future__ import annotations

import inspect
import logging
import traceback
from typing import Callable

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from ..engine.matcher import CancelToken, OperationCancelled
from ..services.common import ServiceError

log = logging.getLogger(__name__)


class _Worker(QObject):
    progress = Signal(int, str)
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, fn: Callable, args, kwargs, token: CancelToken):
        super().__init__()
        self.fn, self.args, self.kwargs, self.token = fn, args, kwargs, token

    @Slot()
    def run(self) -> None:
        kwargs = dict(self.kwargs)
        params = inspect.signature(self.fn).parameters
        if "progress" in params:
            kwargs["progress"] = lambda pct, msg: self.progress.emit(int(pct), str(msg))
        if "cancel" in params:
            kwargs["cancel"] = self.token
        try:
            result = self.fn(*self.args, **kwargs)
        except OperationCancelled:
            self.cancelled.emit()
        except (ServiceError, ValueError, FileNotFoundError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - reported to the user, logged with traceback
            log.error("Background task failed: %s\n%s", exc, traceback.format_exc())
            self.failed.emit(f"Unexpected error: {exc}")
        else:
            self.succeeded.emit(result)


class TaskDialog(QDialog):
    """Modal progress dialog with Cancel. ``done_signal`` fires with (ok, result_or_message)."""

    finished_task = Signal(bool, object)

    def __init__(self, parent: QWidget | None, title: str, fn: Callable, *args, cancellable: bool = True, **kwargs):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(460)
        self.token = CancelToken()
        self.result_value = None
        self.ok = False
        self.message = ""
        lay = QVBoxLayout(self)
        self.label = QLabel("Starting…")
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        lay.addWidget(QLabel(f"<b>{title}</b>"))
        lay.addWidget(self.label)
        lay.addWidget(self.bar)
        row = QHBoxLayout()
        row.addStretch()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setVisible(cancellable)
        self.cancel_btn.clicked.connect(self._cancel)
        row.addWidget(self.cancel_btn)
        lay.addLayout(row)

        self.thread = QThread(self)
        self.worker = _Worker(fn, args, kwargs, self.token)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._progress, Qt.QueuedConnection)
        self.worker.succeeded.connect(self._ok, Qt.QueuedConnection)
        self.worker.failed.connect(self._failed, Qt.QueuedConnection)
        self.worker.cancelled.connect(self._cancelled, Qt.QueuedConnection)

    def start(self) -> None:
        self.thread.start()

    def _progress(self, pct: int, msg: str) -> None:
        self.bar.setValue(max(0, min(100, pct)))
        self.label.setText(msg)

    def _cancel(self) -> None:
        self.token.cancel()
        self.cancel_btn.setEnabled(False)
        self.label.setText("Cancelling safely – nothing will be saved…")

    def _finish(self, ok: bool, value) -> None:
        self.ok = ok
        self.thread.quit()
        self.thread.wait()
        self.finished_task.emit(ok, value)
        self.accept() if ok else self.reject()

    def _ok(self, result) -> None:
        self.result_value = result
        self._finish(True, result)

    def _failed(self, message: str) -> None:
        self.message = message
        self._finish(False, message)

    def _cancelled(self) -> None:
        self.message = "Cancelled – nothing was saved."
        self._finish(False, self.message)

    def reject(self) -> None:  # Esc / window close request cancellation instead of abandoning the thread
        if self.thread.isRunning():
            self._cancel()
            return
        super().reject()


def run_task(parent: QWidget | None, title: str, fn: Callable, *args, cancellable: bool = True,
             **kwargs) -> TaskDialog:
    """Run ``fn`` in the background behind a progress dialog and block (with a live
    event loop) until it finishes. Inspect ``.ok``, ``.result_value`` and ``.message``."""
    dlg = TaskDialog(parent, title, fn, *args, cancellable=cancellable, **kwargs)
    dlg.start()
    dlg.exec()  # worker signals are queued to this event loop, so completion cannot be missed
    return dlg
