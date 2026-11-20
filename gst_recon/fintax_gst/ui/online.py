"""Internet connection status, checked in the background (the program works fully offline; only the portal
links and the update check need the internet)."""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QTimer, Signal


class OnlineMonitor(QObject):
    changed = Signal(bool)

    def __init__(self, interval_ms: int = 60_000, parent=None):
        super().__init__(parent)
        self.online: bool | None = None  # None until the first check finishes
        self._busy = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check)
        self._timer.start(interval_ms)
        self._result.connect(self._set)

    _result = Signal(bool)

    def check(self) -> None:
        if self._busy:
            return
        self._busy = True

        def work():
            from ..services.portal import is_online

            ok = is_online()
            try:
                self._result.emit(ok)
            except RuntimeError:  # the window was closed meanwhile
                pass

        threading.Thread(target=work, daemon=True).start()

    def _set(self, ok: bool) -> None:
        self._busy = False
        before, self.online = self.online, ok
        if before != ok:
            self.changed.emit(ok)
