"""Engine/session creation, versioned migrations and backups."""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import V1_TABLES, SchemaMigration, utcnow

log = logging.getLogger(__name__)


def default_home() -> Path:
    if os.environ.get("FINTAX_HOME"):
        return Path(os.environ["FINTAX_HOME"])
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "FinTaxPro"
    return Path.home() / ".fintaxpro"


def default_db_path() -> Path:
    return Path(os.environ["FINTAX_DB"]) if os.environ.get("FINTAX_DB") else default_home() / "fintaxpro.db"


def _migration_1(conn) -> None:
    from .models import Base

    Base.metadata.create_all(conn, tables=[t.__table__ for t in V1_TABLES])


#: Ordered schema migrations. Never edit an applied migration – append a new one
#: (e.g. ``conn.exec_driver_sql("ALTER TABLE invoices ADD COLUMN ...")``).
MIGRATIONS: list[tuple[int, str, Callable]] = [
    (1, "initial schema: clients, imports, invoices, reconciliation runs, audit log", _migration_1),
]


class Database:
    def __init__(self, path: str | Path | None = None, echo: bool = False):
        self.path = Path(path) if path else default_db_path()
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(f"sqlite:///{self.path}", echo=echo, future=True)
        event.listen(self.engine, "connect", self._on_connect)
        self.Session = sessionmaker(self.engine, expire_on_commit=False, future=True)

    @staticmethod
    def _on_connect(dbapi_conn, _record) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    def current_version(self) -> int:
        if not inspect(self.engine).has_table("schema_migrations"):
            return 0
        with self.Session() as s:
            versions = s.scalars(select(SchemaMigration.version)).all()
        return max(versions, default=0)

    def migrate(self, backup: bool = True) -> list[int]:
        current = self.current_version()
        pending = [m for m in MIGRATIONS if m[0] > current]
        if pending and current > 0 and backup:
            self.backup(suffix=f"pre-migration-v{pending[0][0]}")
        applied = []
        for version, name, fn in pending:
            with self.engine.begin() as conn:
                fn(conn)
                conn.execute(SchemaMigration.__table__.insert().values(version=version, name=name,
                                                                       applied_at=utcnow()))
            log.info("Applied migration %s: %s", version, name)
            applied.append(version)
        return applied

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Transactional scope: commits on success, rolls back on any error (incl. cancellation)."""
        s = self.Session()
        try:
            yield s
            s.commit()
        except BaseException:
            s.rollback()
            raise
        finally:
            s.close()

    def backup(self, target: str | Path | None = None, suffix: str = "manual") -> Path:
        """Consistent online backup using SQLite's backup API."""
        if target is None:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            target = self.path.parent / "backups" / f"fintaxpro-{stamp}-{suffix}.db"
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(self.path)
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        return target

    def restore(self, backup_file: str | Path) -> Path:
        """Replace the database with a backup; the current file is backed up first."""
        backup_file = Path(backup_file)
        check = sqlite3.connect(backup_file)
        try:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Backup file failed SQLite integrity check")
        finally:
            check.close()
        safety = self.backup(suffix="pre-restore")
        self.engine.dispose()
        for extra in ("-wal", "-shm"):
            Path(str(self.path) + extra).unlink(missing_ok=True)
        shutil.copyfile(backup_file, self.path)
        return safety

    def dispose(self) -> None:
        self.engine.dispose()


def open_database(path: str | Path | None = None) -> Database:
    db = Database(path)
    db.migrate()
    return db
