"""FIN TAX PRO desktop application (PySide6)."""
from __future__ import annotations

import argparse
import logging
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QStackedWidget,
    QVBoxLayout, QWidget,
)

from .. import PRODUCT_NAME, TAGLINE, __version__
from ..cli import setup_logging
from ..db.database import Database, default_home, open_database
from ..services.auth import ROLES, SETUP_SESSION, AuthService, Session
from ..services.common import current_user
from ..services.security import SecurityService
from .dialogs.login import LoginDialog
from .pages.admin import ClientsPage, ImportsPage, SettingsPage
from .pages.dashboard import DashboardPage
from .pages.exceptions import ExceptionsPage
from .pages.history import HistoryPage, OpenItemsPage
from .pages.itc import ItcPage
from .pages.notices import NoticesPage
from .pages.phase4 import CompliancePage, LettersPage, OutwardPage, SyncPage
from .pages.returns import ImsPage, ReturnsPage
from .pages.security import SecurityPage
from .pages.suppliers import SuppliersPage
from .pages.workflow import WorkflowPage
from .state import AppState
from .theme import NAVY, STYLESHEET, TEAL

log = logging.getLogger(__name__)

NAV = [
    ("dashboard", "◧  Dashboard"), ("workflow", "▶  Reconcile"), ("exceptions", "⚑  Exceptions"),
    ("itc", "✓  ITC review"), ("returns", "▤  GSTR-3B & annual"), ("ims", "⇄  IMS"),
    ("outward", "⇅  Sales & GSTR-1"), ("compliance", "▦  Compliance"), ("letters", "✉  Letters & papers"),
    ("notices", "⚖  GST notices"),
    ("suppliers", "⌂  Suppliers"), ("open_items", "⏳  Open items"), ("history", "↺  History"),
    ("imports", "⇪  Imports"), ("clients", "☰  Clients"), ("security", "🔒  Security"), ("sync", "☁  Sync & web"),
    ("settings", "⚙  Settings"),
]


def app_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(NAVY))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(0, 0, 64, 64, 14, 14)
    p.setBrush(QColor(TEAL))
    p.drawRect(10, 46, 44, 6)
    p.setPen(QColor("white"))
    f = QFont()
    f.setBold(True)
    f.setPointSize(20)
    p.setFont(f)
    p.drawText(pm.rect().adjusted(0, -8, 0, -8), Qt.AlignCenter, "FT")
    p.end()
    return QIcon(pm)


class MainWindow(QMainWindow):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.setWindowTitle(f"{PRODUCT_NAME} – Smart GST Reconciliation & ITC Management")
        self.setWindowIcon(app_icon())
        self.resize(1440, 900)
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._header())
        body = QHBoxLayout()
        body.setSpacing(0)
        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setFixedWidth(190)
        self.stack = QStackedWidget()
        self.pages: dict[str, QWidget] = {
            "dashboard": DashboardPage(state), "workflow": WorkflowPage(state), "exceptions": ExceptionsPage(state),
            "itc": ItcPage(state), "returns": ReturnsPage(state), "ims": ImsPage(state),
            "outward": OutwardPage(state), "compliance": CompliancePage(state), "letters": LettersPage(state),
            "notices": NoticesPage(state),
            "sync": SyncPage(state),
            "suppliers": SuppliersPage(state), "open_items": OpenItemsPage(state), "history": HistoryPage(state),
            "imports": ImportsPage(state), "clients": ClientsPage(state), "security": SecurityPage(state),
            "settings": SettingsPage(state),
        }
        for key, label in NAV:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, key)
            self.nav.addItem(item)
            self.stack.addWidget(self.pages[key])
            if hasattr(self.pages[key], "navigate"):
                self.pages[key].navigate.connect(self.go)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        body.addWidget(self.nav)
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)
        self.setCentralWidget(central)
        role = ROLES.get(state.session.role, state.session.role)
        self.statusBar().showMessage(f"Database: {state.db.location} · {state.session.full_name or state.user} ({role}) "
                                     "· offline – no data leaves this computer")
        state.clientChanged.connect(self._sync_header)
        state.dataChanged.connect(self._fill_clients)
        state.runChanged.connect(self._sync_header)
        self._fill_clients()
        self.go("dashboard" if state.client else "clients")

    def _header(self) -> QWidget:
        w = QWidget()
        w.setObjectName("Header")
        w.setFixedHeight(64)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(18, 6, 18, 6)
        brand = QVBoxLayout()
        b = QLabel(PRODUCT_NAME)
        b.setObjectName("Brand")
        t = QLabel(TAGLINE)
        t.setObjectName("Tagline")
        brand.addWidget(b)
        brand.addWidget(t)
        lay.addLayout(brand)
        lay.addStretch()
        lbl = QLabel("Client")
        lbl.setObjectName("HeaderLabel")
        self.client_cb = QComboBox()
        self.client_cb.setMinimumWidth(330)
        self.client_cb.currentIndexChanged.connect(self._client_selected)
        fy_lbl = QLabel("Financial year")
        fy_lbl.setObjectName("HeaderLabel")
        self.fy_cb = QComboBox()
        self.fy_cb.currentTextChanged.connect(lambda fy: fy and self.state.set_fy(fy))
        self.run_lbl = QLabel("")
        self.run_lbl.setObjectName("HeaderLabel")
        user_lbl = QLabel(f"👤 {self.state.session.username}")
        user_lbl.setObjectName("HeaderLabel")
        for x in (lbl, self.client_cb, fy_lbl, self.fy_cb, self.run_lbl, user_lbl):
            lay.addWidget(x)
        return w

    def go(self, key: str) -> None:
        for i in range(self.nav.count()):
            if self.nav.item(i).data(Qt.UserRole) == key:
                self.nav.setCurrentRow(i)
                return

    def _fill_clients(self) -> None:
        self.client_cb.blockSignals(True)
        self.client_cb.clear()
        self.client_cb.addItem("— select client —", None)
        for c in self.state.clients.list():
            self.client_cb.addItem(f"{c.name} · {c.gstin}", c.id)
        self.client_cb.blockSignals(False)
        self._sync_header()

    def _client_selected(self, index: int) -> None:
        cid = self.client_cb.itemData(index)
        if cid is None:
            if self.state.client is not None:
                self.state.set_client(None)
            return
        if self.state.client is None or self.state.client.id != cid:
            self.state.set_client(self.state.clients.get(cid))

    def _sync_header(self) -> None:
        st = self.state
        self.client_cb.blockSignals(True)
        idx = self.client_cb.findData(st.client.id) if st.client else 0
        self.client_cb.setCurrentIndex(max(idx, 0))
        self.client_cb.blockSignals(False)
        self.fy_cb.blockSignals(True)
        start = int(st.fy[:4])
        years = [f"{y}-{str(y + 1)[-2:]}" for y in range(start - 4, start + 2)]
        self.fy_cb.clear()
        self.fy_cb.addItems(years)
        self.fy_cb.setCurrentText(st.fy)
        self.fy_cb.blockSignals(False)
        self.run_lbl.setText(f"Run #{st.run_id}" if st.run_id else "No run")


def create_app(argv: list[str] | None = None) -> QApplication:
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName(PRODUCT_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("FinTaxPro")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    app.setWindowIcon(app_icon())
    return app


def build_window(db: Database, user: str | Session | None = None) -> MainWindow:
    state = AppState(db, user or current_user())
    clients = state.clients.list()
    if len(clients) == 1:
        state.set_client(clients[0])
    return MainWindow(state)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fintax-gst-gui")
    parser.add_argument("--db", default=None)
    parser.add_argument("--smoke-test", action="store_true",
                        help="open every page once and exit (used to verify an installation or build)")
    args, qt_args = parser.parse_known_args(argv)
    setup_logging(default_home(), False)
    app = create_app([sys.argv[0], *qt_args])
    db = open_database(args.db)
    if args.smoke_test:  # opens each page once and exits – never interactive, so no login needed
        session = SETUP_SESSION
    else:
        login = LoginDialog(None, AuthService(db))
        if login.exec() != QDialog.Accepted or login.session is None:
            db.dispose()
            return 1
        session = login.session
    try:
        SecurityService(db).auto_backup()
    except OSError as exc:  # never block start-up on a backup problem; it is logged
        log.warning("automatic backup failed: %s", exc)
    win = build_window(db, session)
    win.show()
    if args.smoke_test:
        for key, _label in NAV:
            win.go(key)
            app.processEvents()
        print(f"{PRODUCT_NAME} {__version__}: {len(NAV)} pages OK, database {db.location}")
        db.dispose()
        return 0
    code = app.exec()
    db.dispose()
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
