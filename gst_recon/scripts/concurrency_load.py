"""Concurrent review edits against one database – checks that no edit is lost.

Usage:
    python scripts/concurrency_load.py --db postgresql+psycopg://user@host/db --workers 8 --edits 50
    python scripts/concurrency_load.py --db fintax.db --workers 4 --edits 20

The database must be empty (a demo client and run are created) – never point it at a
live database. Each worker repeatedly opens a line of the run (reads its version),
changes the remarks and saves with that version, as two people working on the same
exceptions would. A worker spends at most ``--attempts`` tries on each edit. Workers
pick from a small set of lines (``--hot``), so they collide often.

At the end the script checks:

* every successful save is in the audit log, once;
* each line's version = 1 + the saves that succeeded on it;
* each line's remarks are the text of the last save that succeeded on it.

It prints the throughput, the conflicts detected and the save latency. The exit code is 1
if any check fails.
"""
from __future__ import annotations

import argparse
import random
import statistics
import sys
import tempfile
import threading
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402

from fintax_gst.core.models import Source  # noqa: E402
from fintax_gst.db.database import open_database  # noqa: E402
from fintax_gst.db.models import AuditLog, ReconLineRow  # noqa: E402
from fintax_gst.samples import CLIENT, write_all  # noqa: E402
from fintax_gst.services.clients import ClientService  # noqa: E402
from fintax_gst.services.common import ConflictError  # noqa: E402
from fintax_gst.services.imports import ImportService  # noqa: E402
from fintax_gst.services.reconciliation import ReconciliationService  # noqa: E402


def setup(db) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        files = write_all(Path(tmp))
        c = ClientService(db).create(**CLIENT)
        svc = ImportService(db)
        svc.import_file(c.id, files["books_april"], Source.BOOKS)
        svc.import_file(c.id, files["gstr2b_april_json"], Source.GSTR2B)
        return ReconciliationService(db).run(c.id, "2025-04", user="setup")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", required=True, help="empty database: file path or URL")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--edits", type=int, default=50, help="successful saves wanted per worker")
    ap.add_argument("--hot", type=int, default=3, help="number of lines the workers share")
    ap.add_argument("--attempts", type=int, default=20, help="tries per edit before a worker gives up on it")
    args = ap.parse_args(argv)

    db = open_database(args.db)
    with db.session() as s:
        if s.scalar(select(func.count()).select_from(ReconLineRow)):
            print("The database already holds reconciliation lines – use an empty database.")
            return 2
    run_id = setup(db)
    with db.session() as s:
        lines = list(s.scalars(select(ReconLineRow.line_no).where(ReconLineRow.run_id == run_id)
                               .order_by(ReconLineRow.line_no).limit(args.hot)))
    svc = ReconciliationService(db)
    lock = threading.Lock()
    wins: Counter = Counter()
    last_text: dict[int, tuple[int, str]] = {}  # line -> (version, remarks) of the latest successful save
    conflicts, gave_up, latencies, errors = [0], [0], [], []

    def worker(n: int) -> None:
        rnd = random.Random(n)
        user = f"user{n}"
        for i in range(args.edits):
            line = rnd.choice(lines)
            for _attempt in range(args.attempts):
                with db.session() as s:
                    version = s.scalar(select(ReconLineRow.version).where(ReconLineRow.run_id == run_id,
                                                                          ReconLineRow.line_no == line))
                text = f"{user} edit {i}"
                t0 = time.perf_counter()
                try:
                    new = svc.update_line(run_id, line, user, remarks=text, expected_version=version)
                except ConflictError:
                    with lock:
                        conflicts[0] += 1
                    continue
                except Exception as exc:  # anything else is a failure of the test
                    with lock:
                        errors.append(f"{user}: {type(exc).__name__}: {exc}")
                    return
                with lock:
                    latencies.append(time.perf_counter() - t0)
                    wins[line] += 1
                    if new > last_text.get(line, (0, ""))[0]:
                        last_text[line] = (new, text)
                break
            else:
                with lock:
                    gave_up[0] += 1

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(args.workers)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - t0

    ok = not errors
    with db.session() as s:
        audited = s.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "UPDATE", AuditLog.entity == "recon_line"))
        rows = {r.line_no: r for r in s.scalars(select(ReconLineRow).where(ReconLineRow.run_id == run_id,
                                                                            ReconLineRow.line_no.in_(lines)))}
    saved = sum(wins.values())
    print(f"Database: {db.location}")
    print(f"{args.workers} workers, {len(lines)} shared lines: {saved} saves in {elapsed:.1f} s "
          f"({saved / elapsed:.0f}/s), {conflicts[0]} conflicts detected, {gave_up[0]} edits given up")
    if latencies:
        q = sorted(latencies)
        print(f"save latency: median {statistics.median(q) * 1000:.0f} ms, "
              f"95th percentile {q[int(len(q) * 0.95) - 1] * 1000:.0f} ms")
    if audited != saved:
        ok = False
        print(f"FAIL: {saved} saves but {audited} audit entries")
    for line in lines:
        r = rows[line]
        if r.version != 1 + wins[line]:
            ok = False
            print(f"FAIL: line {line} version {r.version}, expected {1 + wins[line]}")
        if wins[line] and r.remarks != last_text[line][1]:
            ok = False
            print(f"FAIL: line {line} remarks '{r.remarks}', last successful save '{last_text[line][1]}'")
    for e in errors[:10]:
        print(f"FAIL: {e}")
    print("OK – no lost or duplicated edits" if ok else "FAILED")
    db.dispose()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
