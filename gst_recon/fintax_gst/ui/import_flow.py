"""Interactive import: preview → (re-map columns) → confirm → save, all with progress."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialog, QMessageBox, QWidget

from ..core.models import Source
from ..db.models import SourceFile
from ..importers.pipeline import ImportPreview, MappingRequired
from .dialogs.import_preview import ImportPreviewDialog
from .dialogs.mapping import MappingDialog
from .state import AppState
from .workers import run_task


def _preview(state: AppState, client_id: int, path: Path, source: Source, period: str | None, template):
    try:
        if template is None:
            return state.imports.preview_auto(client_id, path, source, period)
        return state.imports.preview(client_id, path, source, period, template)
    except MappingRequired as exc:
        return exc


def import_interactive(parent: QWidget, state: AppState, path: str | Path, source: Source,
                       period: str | None = None, template: dict | str | None = None) -> SourceFile | None:
    if state.client is None:
        QMessageBox.information(parent, "Import", "Select a client first.")
        return None
    path = Path(path)
    client_id = state.client.id
    while True:
        task = run_task(parent, f"Reading {path.name}", _preview, state, client_id, path, source, period, template,
                        cancellable=False)
        if not task.ok:
            QMessageBox.warning(parent, "Import", task.message)
            return None
        result = task.result_value
        if isinstance(result, MappingRequired):
            mapping = MappingDialog(parent, [c.label for c in result.columns], result.mapping.fields,
                                    f"sheet '{result.sheet}'")
            if mapping.exec() != QDialog.Accepted:
                return None
            template = _remember(state, mapping, source)
            continue
        preview: ImportPreview = result
        dlg = ImportPreviewDialog(parent, preview)
        code = dlg.exec()
        if code == ImportPreviewDialog.REMAP:
            columns = list(dict.fromkeys(c for cols in preview.columns.values() for c in cols))
            current: dict[str, list[str]] = {}
            for m in preview.mappings.values():
                current.update(m.fields)
            mapping = MappingDialog(parent, columns, current, preview.file_name)
            if mapping.exec() == QDialog.Accepted:
                template = _remember(state, mapping, source)
            continue
        if code != QDialog.Accepted:
            return None
        saved = run_task(parent, f"Saving {path.name}", state.imports.commit, client_id, preview, state.user)
        if not saved.ok:
            QMessageBox.warning(parent, "Import", saved.message)
            return None
        state.notify()
        return saved.result_value


def _remember(state: AppState, dlg: MappingDialog, source: Source) -> dict:
    template = dlg.template()
    if dlg.save_check.isChecked() and dlg.template_name.text().strip():
        state.imports.save_template(dlg.template_name.text().strip(), source, template, state.user)
    return template
