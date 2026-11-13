"""'Import from Tally…': pick the company open in TallyPrime, fetch its vouchers for the months
and go through the usual import preview."""
from __future__ import annotations

from PySide6.QtWidgets import QInputDialog, QLineEdit, QMessageBox, QWidget

from ..core.models import Source
from .import_flow import import_interactive
from .state import AppState
from .workers import run_task


def tally_import(parent: QWidget, state: AppState, source: Source, p_from: str, p_to: str | None = None) -> bool:
    from ..services.tally import TallyService

    if state.client is None:
        QMessageBox.information(parent, "Tally", "Select a client first.")
        return False
    svc = TallyService(state.db)
    url, ok = QInputDialog.getText(parent, "Import from Tally", "TallyPrime address (Connectivity → Server):",
                                   QLineEdit.Normal, svc.url())
    if not ok or not url.strip():
        return False
    task = run_task(parent, "Asking Tally for its companies", svc.companies, url.strip(), cancellable=False)
    if not task.ok:
        QMessageBox.warning(parent, "Tally", task.message)
        return False
    companies = task.result_value
    if not companies:
        QMessageBox.information(parent, "Tally", "No company is open in Tally.")
        return False
    company, ok = QInputDialog.getItem(parent, "Import from Tally",
                                       f"Company for {state.client.name} ({p_from} to {p_to or p_from}):",
                                       companies, 0, False)
    if not ok:
        return False
    task = run_task(parent, f"Fetching vouchers from Tally – {company}", svc.fetch, state.client.id, company, p_from,
                    p_to, url.strip(), state.user)
    if not task.ok:
        QMessageBox.warning(parent, "Tally", task.message)
        return False
    return import_interactive(parent, state, task.result_value, source, None) is not None
