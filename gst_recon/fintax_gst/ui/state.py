"""Application state shared by all pages: database, services, current client/FY/run."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QObject, QSettings, Signal

from ..core.models import ReconSettings, fy_of
from ..db.database import Database
from ..db.models import Client
from ..services.clients import ClientService
from ..services.followup import AttachmentService, VendorService
from ..services.imports import ImportService
from ..services.reconciliation import ReconciliationService
from ..services.auth import SETUP_SESSION, AuthService, Session
from ..services.gstr3b import Gstr3bService
from ..services.itc import ItcService
from ..services.security import SecurityService
from ..services.tracking import TrackingService


class AppState(QObject):
    clientChanged = Signal()
    runChanged = Signal()
    dataChanged = Signal()  # imports, runs or lines changed

    def __init__(self, db: Database, user: str | Session, settings: QSettings | None = None):
        super().__init__()
        self.db = db
        self.session: Session = user if isinstance(user, Session) else Session(user, SETUP_SESSION.role, user)
        self.user = self.session.username
        self.qsettings = settings or QSettings("FinTaxPro", "GSTReconciliation")
        self.clients = ClientService(db)
        self.imports = ImportService(db)
        self.recon = ReconciliationService(db)
        self.tracking = TrackingService(db)
        self.vendors = VendorService(db)
        self.attachments = AttachmentService(db)
        self.auth = AuthService(db)
        self.itc = ItcService(db)
        self.gstr3b = Gstr3bService(db)
        self.security = SecurityService(db)
        self.client: Client | None = None
        self.fy: str = fy_of(date.today())
        self.run_id: int | None = None
        self._ctx_cache = None  # (run_id, RunContext) – shared by all pages until data changes

    # ------------------------------------------------------------- selection
    def set_client(self, client: Client | None) -> None:
        self.client = client
        if client is not None and client.financial_year:
            self.fy = client.financial_year
        latest = self.tracking.latest_run(client.id, self.fy) if client else None
        self.run_id = latest.id if latest else None
        self.clientChanged.emit()
        self.runChanged.emit()

    def set_fy(self, fy: str) -> None:
        if fy == self.fy:
            return
        self.fy = fy
        latest = self.tracking.latest_run(self.client.id, fy) if self.client else None
        self.run_id = latest.id if latest else None
        self.clientChanged.emit()
        self.runChanged.emit()

    def set_run(self, run_id: int | None, data_changed: bool = False) -> None:
        """Show another run. ``data_changed`` (a run was just made) also tells pages that data changed – in one
        step, so the new run is loaded once and not again by a second refresh."""
        self.run_id = run_id
        if data_changed:
            self._ctx_cache = None
            self.dataChanged.emit()
        self.runChanged.emit()

    def notify(self, keep_cache: bool = False) -> None:
        """Tell pages that data changed. ``keep_cache`` is used when the change was
        applied to the cached run objects as well (e.g. a review save)."""
        if not keep_cache:
            self._ctx_cache = None
        self.dataChanged.emit()

    def run_context(self):
        """The current run loaded once and shared by every page until data changes."""
        if self.run_id is None:
            return None
        if self._ctx_cache is None or self._ctx_cache[0] != self.run_id:
            self._ctx_cache = (self.run_id, self.recon.load(self.run_id))
        return self._ctx_cache[1]

    # ---------------------------------------------------------- permissions
    def can(self, permission: str) -> bool:
        return self.session.can(permission)

    # ------------------------------------------------------- user settings
    def recon_settings(self) -> ReconSettings:
        data = self.qsettings.value("recon_settings")
        if isinstance(data, dict):
            try:
                return ReconSettings.from_dict(data)
            except (TypeError, ValueError):
                pass
        return ReconSettings()

    def save_recon_settings(self, settings: ReconSettings) -> None:
        self.qsettings.setValue("recon_settings", settings.to_dict())
