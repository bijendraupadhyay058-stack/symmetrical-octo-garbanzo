"""Engine/session creation, versioned migrations and backups."""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

from sqlalchemy import create_engine, delete, event, inspect, select, text
from sqlalchemy.engine import Engine, make_url
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


def is_server_url(target) -> bool:
    """True for a database server URL such as ``postgresql+psycopg://user@host/db``."""
    return isinstance(target, str) and "://" in target and not target.startswith("sqlite")


def copy_rows(src: Engine, dst: Engine, batch: int = 2000, progress: Callable | None = None) -> dict[str, int]:
    """Copy every application table from ``src`` to ``dst`` (same schema version; ``dst``
    tables must be empty). Ids are kept, so references stay valid."""
    with src.connect() as sc, dst.begin() as dc:
        return _copy(sc, dc, batch, progress)


def _copy(sc, dc, batch: int = 2000, progress: Callable | None = None) -> dict[str, int]:
    from .models import Base

    counts = {}
    tables = [t for t in Base.metadata.sorted_tables if t.name != "schema_migrations"]
    for i, t in enumerate(tables):
        n = 0
        result = sc.execute(select(t).order_by(*t.primary_key.columns))
        while rows := result.fetchmany(batch):
            dc.execute(t.insert(), [dict(r._mapping) for r in rows])
            n += len(rows)
        counts[t.name] = n
        if progress:
            progress(int((i + 1) * 100 / len(tables)), f"Copied {t.name}")
    return counts


def _migration_1(conn) -> None:
    from .models import Base

    Base.metadata.create_all(conn, tables=[t.__table__ for t in V1_TABLES])


def _migration_2(conn) -> None:
    from .models import V2_TABLES, Base

    Base.metadata.create_all(conn, tables=[t.__table__ for t in V2_TABLES])


def _migration_3(conn) -> None:
    from sqlalchemy import inspect as sa_inspect

    from .models import V3_TABLES, Base

    existing = {c["name"] for c in sa_inspect(conn).get_columns("invoices")}
    for column, ddl in (("description", "TEXT NOT NULL DEFAULT ''"), ("ims_action", "VARCHAR(2) NOT NULL DEFAULT ''")):
        if column not in existing:  # fresh databases already have them from the current model
            conn.exec_driver_sql(f"ALTER TABLE invoices ADD COLUMN {column} {ddl}")
    Base.metadata.create_all(conn, tables=[t.__table__ for t in V3_TABLES])


def _migration_4(conn) -> None:
    from sqlalchemy import inspect as sa_inspect

    from .models import V4_TABLES, Base

    insp = sa_inspect(conn)
    for table, column, ddl in (("invoices", "supply_type", "VARCHAR(40) NOT NULL DEFAULT ''"),
                               ("gstr3b_entries", "taxable", "VARCHAR(40) NOT NULL DEFAULT '0'")):
        if column not in {c["name"] for c in insp.get_columns(table)}:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    Base.metadata.create_all(conn, tables=[t.__table__ for t in V4_TABLES])


def _migration_5(conn) -> None:
    from .models import V5_TABLES, Base

    Base.metadata.create_all(conn, tables=[t.__table__ for t in V5_TABLES])


def _migration_6(conn) -> None:
    from .models import V6_TABLES, Base

    Base.metadata.create_all(conn, tables=[t.__table__ for t in V6_TABLES])


def _migration_7(conn) -> None:
    from .models import V7_TABLES, Base

    Base.metadata.create_all(conn, tables=[t.__table__ for t in V7_TABLES])


#: Ordered schema migrations. Never edit an applied migration – append a new one
#: (e.g. ``conn.exec_driver_sql("ALTER TABLE invoices ADD COLUMN ...")``).
MIGRATIONS: list[tuple[int, str, Callable]] = [
    (1, "initial schema: clients, imports, invoices, reconciliation runs, audit log", _migration_1),
    (2, "manual match decisions, vendor follow-up register, evidence attachments", _migration_2),
    (3, "users, settings, ITC rules/reviews/claims, GSTR-3B, ISD/imports, IMS columns", _migration_3),
    (4, "outward supplies (sales, GSTR-1), GSTR-3B 3.1, sync authorisations, letters, working papers",
     _migration_4),
    (5, "GST due-date extensions recorded by the user", _migration_5),
    (6, "GSTR-9C figures from the audited financial statements and reasons", _migration_6),
    (7, "GSTR-1 HSN-wise summary of outward supplies", _migration_7),
]


class Database:
    """A SQLite file (the default, fully offline) or a PostgreSQL server.

    ``data_dir`` holds evidence attachments and backups. For SQLite it is the folder of
    the database file; for a server it defaults to the application home folder.
    """

    def __init__(self, path: str | Path | None = None, echo: bool = False, data_dir: str | Path | None = None):
        if path is None:
            path = os.environ.get("FINTAX_DB_URL") or default_db_path()
        self.is_sqlite = not is_server_url(str(path))
        if self.is_sqlite:
            self.path = Path(str(path).removeprefix("sqlite:///"))
            if str(self.path) != ":memory:":
                self.path.parent.mkdir(parents=True, exist_ok=True)
            self.data_dir = Path(data_dir) if data_dir else self.path.parent
            # Sessions are never shared between threads, but the desktop app runs long
            # operations on a worker thread, so pooled connections may change thread.
            self.engine: Engine = create_engine(f"sqlite:///{self.path}", echo=echo, future=True,
                                                connect_args={"check_same_thread": False, "timeout": 30})
            event.listen(self.engine, "connect", self._on_connect)
        else:
            self.url = make_url(str(path))
            self.data_dir = Path(data_dir) if data_dir else default_home()
            self.path = self.data_dir / "server.db"  # never opened; kept for callers that expect a path
            self.engine = create_engine(self.url, echo=echo, future=True, pool_pre_ping=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.Session = sessionmaker(self.engine, expire_on_commit=False, future=True)

    @property
    def location(self) -> str:
        """Where the data lives, for display (passwords are never shown)."""
        return str(self.path) if self.is_sqlite else self.url.render_as_string(hide_password=True)

    @staticmethod
    def _on_connect(dbapi_conn, _record) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA secure_delete=ON")  # deleted client data is overwritten, not left in free pages
        cur.close()

    def current_version(self) -> int:
        if not inspect(self.engine).has_table("schema_migrations"):
            return 0
        with self.Session() as s:
            versions = s.scalars(select(SchemaMigration.version)).all()
        return max(versions, default=0)

    def migrate(self, backup: bool = True, upto: int | None = None) -> list[int]:
        current = self.current_version()
        pending = [m for m in MIGRATIONS if m[0] > current and (upto is None or m[0] <= upto)]
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
        """Consistent backup as a SQLite file: SQLite's online backup API, or for a server
        a snapshot of every table in one repeatable-read transaction."""
        if target is None:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            target = self.data_dir / "backups" / f"fintaxpro-{stamp}-{suffix}.db"
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not self.is_sqlite:
            target.unlink(missing_ok=True)
            snap = Database(target)
            try:
                snap.migrate(backup=False, upto=self.current_version())
                copy_rows(self.engine.execution_options(isolation_level="REPEATABLE READ"), snap.engine)
            finally:
                snap.dispose()
            return target
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
        if not self.is_sqlite:
            self._restore_server(backup_file)
            return safety
        self.engine.dispose()
        for extra in ("-wal", "-shm"):
            Path(str(self.path) + extra).unlink(missing_ok=True)
        shutil.copyfile(backup_file, self.path)
        return safety

    def _restore_server(self, backup_file: Path) -> None:
        """Replace all server tables with the contents of a SQLite backup (one transaction)."""
        from .models import Base

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "restore.db"
            shutil.copyfile(backup_file, work)
            src = Database(work)
            try:
                src.migrate(backup=False, upto=self.current_version())
                tables = [t for t in Base.metadata.sorted_tables if t.name != "schema_migrations"]
                with src.engine.connect() as sc, self.engine.begin() as dc:  # all or nothing
                    for t in reversed(tables):
                        dc.execute(delete(t))
                    _copy(sc, dc)
            finally:
                src.dispose()
        self.reset_sequences()

    def reset_sequences(self) -> None:
        """After rows were inserted with explicit ids, move PostgreSQL id sequences past them."""
        if self.is_sqlite or self.engine.dialect.name != "postgresql":
            return
        from .models import Base

        with self.engine.begin() as conn:
            for t in Base.metadata.sorted_tables:
                if "id" in t.c and t.c.id.autoincrement in (True, "auto") and t.c.id.type.python_type is int:
                    conn.execute(text(f"SELECT setval(pg_get_serial_sequence('{t.name}', 'id'), "
                                      f"COALESCE((SELECT MAX(id) FROM {t.name}), 1), "
                                      f"(SELECT MAX(id) FROM {t.name}) IS NOT NULL)"))

    def dispose(self) -> None:
        self.engine.dispose()


def open_database(path: str | Path | None = None, data_dir: str | Path | None = None) -> Database:
    db = Database(path, data_dir=data_dir)
    db.migrate()
    return db


def copy_database(source: Database, target_url: str | Path, progress: Callable | None = None) -> dict[str, int]:
    """Copy all data into another, empty database (e.g. move a SQLite file to PostgreSQL).
    The target is brought to the same schema version first; nothing is copied if it holds data."""
    from .models import Client

    target = Database(target_url, data_dir=source.data_dir)
    try:
        target.migrate(backup=False, upto=source.current_version())
        if target.current_version() != source.current_version():
            raise ValueError("The target database has a newer schema than the source")
        with target.Session() as s:
            if s.scalar(select(Client.id).limit(1)) is not None:
                raise ValueError("The target database already contains data – use an empty database")
        counts = copy_rows(source.engine, target.engine, progress=progress)
        target.reset_sequences()
        return counts
    finally:
        target.dispose()
