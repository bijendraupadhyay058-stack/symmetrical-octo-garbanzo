"""Users and roles, password, encrypted backups, automatic backup settings, audit log, client purge."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from ...services.auth import ROLES
from ...services.common import ServiceError
from ..state import AppState
from ..widgets import LazyPage, RowsModel, Table, card, page_header, primary, section, sortable


def _wrapped(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    return lbl


class SecurityPage(LazyPage):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        self.header = page_header("Security", "")
        lay.addWidget(self.header)
        tabs = QTabWidget()
        tabs.addTab(self._users_tab(), "Users && roles")
        tabs.addTab(self._backup_tab(), "Backups")
        tabs.addTab(self._audit_tab(), "Audit log")
        tabs.addTab(self._data_tab(), "Data deletion")
        lay.addWidget(tabs, 1)
        for sig in (state.dataChanged, state.clientChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()

    # ---------------------------------------------------------------- tabs
    def _users_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.pw_btn = QPushButton("Change my password…")
        self.pw_btn.clicked.connect(self.change_password)
        self.add_btn = primary("Add user…")
        self.add_btn.clicked.connect(self.add_user)
        self.reset_btn = QPushButton("Reset password…")
        self.reset_btn.clicked.connect(self.reset_password)
        self.role_btn = QPushButton("Change role / status…")
        self.role_btn.clicked.connect(self.change_role)
        for b in (self.pw_btn, self.add_btn, self.reset_btn, self.role_btn):
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        self.users_model = RowsModel(["User", "Name", "Role", "Status", "Last login", "Created"])
        self.users = Table()
        self.users.setModel(sortable(self.users_model))
        lay.addWidget(self.users, 1)
        perms = QLabel("<b>Roles</b>: Administrator – everything incl. users, restore, deletion · Partner/Manager – "
                       "everything except users/restore/deletion · Accountant – import, reconcile, review, claim, "
                       "export · Viewer – view and export only.")
        perms.setWordWrap(True)
        perms.setObjectName("Muted")
        lay.addWidget(perms)
        return w

    def _backup_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        frame, fl = card()
        fl.addWidget(section("Encrypted backup"))
        fl.addWidget(_wrapped("AES-encrypted copy of the whole database, protected by a password you choose. "
                              "Keep the password safe – it cannot be recovered."))
        row = QHBoxLayout()
        self.enc_btn = primary("Create encrypted backup…")
        self.enc_btn.clicked.connect(self.encrypted_backup)
        self.restore_btn = QPushButton("Restore encrypted backup…")
        self.restore_btn.setObjectName("Danger")
        self.restore_btn.clicked.connect(self.restore_encrypted)
        row.addWidget(self.enc_btn)
        row.addWidget(self.restore_btn)
        row.addStretch()
        fl.addLayout(row)
        lay.addWidget(frame)
        frame2, f2 = card()
        f2.addWidget(section("Automatic backups"))
        form = QFormLayout()
        self.auto_on = QCheckBox("Back up automatically when the application starts")
        self.interval = QSpinBox()
        self.interval.setRange(1, 24 * 30)
        self.interval.setSuffix(" hours")
        self.keep = QSpinBox()
        self.keep.setRange(1, 365)
        self.retention = QSpinBox()
        self.retention.setRange(1, 3650)
        self.retention.setSuffix(" days")
        form.addRow("", self.auto_on)
        form.addRow("Minimum interval", self.interval)
        form.addRow("Keep at most", self.keep)
        form.addRow("Delete automatic backups older than", self.retention)
        f2.addLayout(form)
        row2 = QHBoxLayout()
        self.save_auto_btn = primary("Save")
        self.save_auto_btn.clicked.connect(self.save_auto)
        self.now_btn = QPushButton("Back up now")
        self.now_btn.clicked.connect(self.backup_now)
        row2.addWidget(self.save_auto_btn)
        row2.addWidget(self.now_btn)
        row2.addStretch()
        f2.addLayout(row2)
        self.backup_lbl = QLabel()
        self.backup_lbl.setWordWrap(True)
        f2.addWidget(self.backup_lbl)
        lay.addWidget(frame2)
        lay.addStretch()
        return w

    def _audit_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.audit_scope = QComboBox()
        self.audit_scope.addItems(["Current client", "All"])
        self.audit_scope.currentIndexChanged.connect(lambda _i: self._fill_audit())
        self.audit_search = QLineEdit()
        self.audit_search.setPlaceholderText("Filter…")
        self.audit_export_btn = QPushButton("Export CSV…")
        self.audit_export_btn.clicked.connect(self.export_audit)
        for x in (self.audit_scope, self.audit_search, self.audit_export_btn):
            row.addWidget(x)
        lay.addLayout(row)
        self.audit_model = RowsModel(["When (UTC)", "User", "Action", "Entity", "ID", "Details"])
        proxy = sortable(self.audit_model)
        self.audit_search.textChanged.connect(proxy.setFilterFixedString)
        t = Table()
        t.setModel(proxy)
        lay.addWidget(t, 1)
        self.audit_table = t
        return w

    def _data_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        frame, fl = card()
        fl.addWidget(section("Permanently delete a client"))
        fl.addWidget(_wrapped("Deletes the client with all imports, reconciliations, reviews, claims, evidence files "
                              "and vendor records. Deleted database pages are overwritten (secure delete) and the "
                              "database is compacted. An encrypted backup is recommended first. The deletion itself "
                              "stays in the audit log."))
        row = QHBoxLayout()
        self.purge_btn = QPushButton("Delete current client permanently…")
        self.purge_btn.setObjectName("Danger")
        self.purge_btn.clicked.connect(self.purge)
        row.addWidget(self.purge_btn)
        row.addStretch()
        fl.addLayout(row)
        lay.addWidget(frame)
        lay.addStretch()
        return w

    # ---------------------------------------------------------------- data
    def reload(self) -> None:
        st = self.state
        s = st.session
        self.header.subtitle.setText(f"Logged in as {s.full_name or s.username} ({ROLES.get(s.role, s.role)}). "
                                     "All data stays on this computer; GST portal credentials are never requested.")
        admin = st.can("manage_users")
        for b in (self.add_btn, self.reset_btn, self.role_btn):
            b.setEnabled(admin)
        self.restore_btn.setEnabled(st.can("restore"))
        self.purge_btn.setEnabled(st.can("delete_data") and st.client is not None)
        for b in (self.save_auto_btn, self.now_btn, self.enc_btn):
            b.setEnabled(st.can("settings"))
        self.pw_btn.setEnabled(s.username != "setup")
        self.users_model.set_rows([[u.username, u.full_name, ROLES.get(u.role, u.role),
                                    "active" if u.active else "disabled",
                                    f"{u.last_login:%d-%m-%Y %H:%M}" if u.last_login else "never",
                                    f"{u.created_at:%d-%m-%Y}"] for u in st.auth.users()])
        self.users.fit()
        sec = st.security
        self.auto_on.setChecked(bool(sec.setting("auto_backup")))
        self.interval.setValue(int(sec.setting("backup_interval_hours")))
        self.keep.setValue(int(sec.setting("backup_keep")))
        self.retention.setValue(int(sec.setting("backup_retention_days")))
        backups = sorted(sec.backup_dir.glob("*.db")) if sec.backup_dir.exists() else []
        self.backup_lbl.setText(f"{len(backups)} backup file(s) in {sec.backup_dir}")
        self._fill_audit()

    def _fill_audit(self) -> None:
        st = self.state
        cid = st.client.id if (self.audit_scope.currentIndex() == 0 and st.client) else None
        rows = st.security.audit_rows(cid, limit=1000)
        self.audit_model.set_rows([[f"{a.at:%d-%m-%Y %H:%M:%S}", a.user, a.action, a.entity, a.entity_id,
                                    a.details_json[:300]] for a in rows])
        self.audit_table.fit(420)

    # ------------------------------------------------------------- helpers
    def ask(self, title: str, label: str, password: bool = False, default: str = "") -> str | None:
        mode = QLineEdit.Password if password else QLineEdit.Normal
        text, ok = QInputDialog.getText(self, title, label, mode, default)
        return text if ok else None

    def choose(self, title: str, label: str, items: list[str]) -> str | None:
        item, ok = QInputDialog.getItem(self, title, label, items, 0, False)
        return item if ok else None

    def _do(self, fn, *args, done: str = "") -> bool:
        try:
            result = fn(*args)
        except ServiceError as exc:
            QMessageBox.warning(self, "Security", str(exc))
            return False
        if done:
            QMessageBox.information(self, "Security", done.format(result=result))
        self.reload()
        return True

    # ------------------------------------------------------------- actions
    def change_password(self) -> None:
        old = self.ask("Change password", "Current password:", True)
        if old is None:
            return
        new = self.ask("Change password", "New password (8+ characters, letters and digits):", True)
        if new is None:
            return
        if self.ask("Change password", "Repeat the new password:", True) != new:
            QMessageBox.warning(self, "Security", "Passwords do not match")
            return
        self._do(self.state.auth.change_password, self.state.session.username, old, new, done="Password changed.")

    def add_user(self) -> None:
        name = self.ask("Add user", "User name:")
        if not name:
            return
        full = self.ask("Add user", "Full name:") or ""
        role = self.choose("Add user", "Role:", [f"{k} – {v}" for k, v in ROLES.items()])
        if not role:
            return
        pw = self.ask("Add user", "Initial password (8+ characters, letters and digits):", True)
        if pw is None:
            return
        self._do(self.state.auth.create_user, name, pw, role.split(" – ")[0], full, self.state.session,
                 done=f"User '{name}' created.")

    def _selected_user(self) -> str | None:
        rows = self.users.selectionModel().selectedRows()
        return self.users.model().index(rows[0].row(), 0).data() if rows else None

    def reset_password(self) -> None:
        user = self._selected_user()
        if not user:
            return
        pw = self.ask("Reset password", f"New password for {user}:", True)
        if pw:
            self._do(self.state.auth.reset_password, user, pw, self.state.session, done="Password reset.")

    def change_role(self) -> None:
        user = self._selected_user()
        if not user:
            return
        role = self.choose("Role", f"Role for {user}:", [f"{k} – {v}" for k, v in ROLES.items()])
        if not role:
            return
        status = self.choose("Status", f"Account of {user}:", ["active", "disabled"])
        if status:
            self._do(self.state.auth.set_role, user, role.split(" – ")[0], self.state.session, status == "active")

    def encrypted_backup(self, target: str | None = None, password: str | None = None) -> Path | None:
        target = target or QFileDialog.getSaveFileName(self, "Encrypted backup", "fintaxpro-backup.ftpbk",
                                                       "FIN TAX PRO backup (*.ftpbk)")[0]
        if not target:
            return None
        password = password or self.ask("Encrypted backup", "Backup password (8+ characters):", True)
        if not password:
            return None
        try:
            return self.state.security.encrypted_backup(target, password, self.state.session)
        except ServiceError as exc:
            QMessageBox.warning(self, "Security", str(exc))
            return None
        finally:
            self.reload()

    def restore_encrypted(self) -> None:
        path = QFileDialog.getOpenFileName(self, "Restore encrypted backup", "", "FIN TAX PRO backup (*.ftpbk)")[0]
        if not path:
            return
        pw = self.ask("Restore", "Backup password:", True)
        if pw is None:
            return
        if QMessageBox.question(self, "Restore", "Replace the current database with this backup? The current "
                                "database is saved first.") != QMessageBox.Yes:
            return
        if self._do(self.state.security.restore_encrypted, path, pw, self.state.session,
                    done="Restored. Previous database saved as {result}."):
            self.state.set_client(None)
            self.state.notify()

    def save_auto(self) -> None:
        sec, s = self.state.security, self.state.session
        try:
            for key, value in (("auto_backup", self.auto_on.isChecked()), ("backup_interval_hours",
                               self.interval.value()), ("backup_keep", self.keep.value()),
                               ("backup_retention_days", self.retention.value())):
                sec.set_setting(key, value, s)
        except ServiceError as exc:
            QMessageBox.warning(self, "Security", str(exc))
        self.reload()

    def backup_now(self) -> None:
        self._do(self.state.security.auto_backup, True, done="Backup written to {result}.")

    def export_audit(self) -> None:
        path = QFileDialog.getSaveFileName(self, "Export audit log", "audit_log.csv", "CSV (*.csv)")[0]
        if path:
            cid = self.state.client.id if (self.audit_scope.currentIndex() == 0 and self.state.client) else None
            self._do(self.state.security.export_audit, path, cid, self.state.session, done="Saved {result}.")

    def purge(self) -> None:
        c = self.state.client
        if c is None:
            return
        typed = self.ask("Delete client permanently", f"This cannot be undone. Type the GSTIN {c.gstin} to "
                                                      "confirm:")
        if typed is None:
            return
        if self._do(self.state.security.purge_client, c.id, typed, self.state.session,
                    done="Client deleted permanently."):
            self.state.set_client(None)
            self.state.notify()
