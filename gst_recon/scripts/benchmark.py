"""Measure import, reconciliation, persistence and Excel export on synthetic data.

Usage:  python scripts/benchmark.py 10000 50000 [--mem]
The dataset mixes exact matches, number-format variations, date/amount
differences, missing documents on both sides, duplicates and typos.
"""
from __future__ import annotations

import csv
import random
import sys
import tempfile
import time
import tracemalloc
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fintax_gst.core.gstin import check_digit  # noqa: E402
from fintax_gst.core.models import Source  # noqa: E402
from fintax_gst.db.database import open_database  # noqa: E402
from fintax_gst.services.clients import ClientService  # noqa: E402
from fintax_gst.services.imports import ImportService  # noqa: E402
from fintax_gst.services.reconciliation import ReconciliationService  # noqa: E402
from fintax_gst.services.reports import export_run  # noqa: E402

HEADER = ["Supplier GSTIN", "Supplier Name", "Invoice No", "Invoice Date", "Taxable Value", "IGST", "CGST", "SGST"]


def _gstin(i: int) -> str:
    letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    pan = f"AA{letters[i % 24]}{letters[(i // 24) % 24]}{letters[(i // 576) % 24]}{i % 10000:04d}K"
    base = f"27{pan}1Z"
    return base + check_digit(base)


def make(n: int, folder: Path, seed: int = 7) -> tuple[Path, Path]:
    rng = random.Random(seed)
    suppliers = [_gstin(i) for i in range(max(n // 40, 5))]
    books, g2b = [], []
    for i in range(n):
        g = rng.choice(suppliers)
        no = f"INV/{i:06d}/25-26"
        day = rng.randint(1, 28)
        tx = Decimal(rng.randint(1000, 500000)) / 100 * 10
        tax = (tx * Decimal("0.09")).quantize(Decimal("0.01"))
        row = [g, f"Supplier {g[2:7]}", no, f"{day:02d}-04-2025", str(tx), "0", str(tax), str(tax)]
        r = rng.random()
        if r < 0.80:
            books.append(row), g2b.append(row)
        elif r < 0.85:
            books.append(row), g2b.append([*row[:2], no.replace("/", "-"), *row[3:]])
        elif r < 0.88:
            books.append(row), g2b.append([*row[:3], f"{min(day + 2, 28):02d}-04-2025", *row[4:]])
        elif r < 0.91:
            books.append(row), g2b.append([*row[:6], str(tax + 50), str(tax + 50)])
        elif r < 0.95:
            books.append(row)
        elif r < 0.98:
            g2b.append(row)
        elif r < 0.99:
            books.append(row), books.append(row), g2b.append(row)
        else:
            books.append(row), g2b.append([*row[:2], no[:-3] + no[-1] + no[-2] + no[-3], *row[3:]])
    paths = []
    for name, rows in (("books.csv", books), ("gstr2b.csv", g2b)):
        p = folder / name
        with open(p, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(HEADER)
            w.writerows(rows)
        paths.append(p)
    return paths[0], paths[1]


def bench(n: int, measure_memory: bool = False) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        books, g2b = make(n, tmp)
        db = open_database(tmp / "bench.db")
        client = ClientService(db).create("27AAPFU0939F1ZV", name="Benchmark")
        imp = ImportService(db)
        if measure_memory:  # tracing slows Python down noticeably, so it is opt-in
            tracemalloc.start()
        t = {}
        t0 = time.perf_counter()
        imp.import_file(client.id, books, Source.BOOKS)
        imp.import_file(client.id, g2b, Source.GSTR2B, period="2025-04")
        t["import (preview+validate+save)"] = time.perf_counter() - t0
        t0 = time.perf_counter()
        run_id = ReconciliationService(db).run(client.id, "2025-04")
        t["reconcile (load+match+save)"] = time.perf_counter() - t0
        t0 = time.perf_counter()
        export_run(db, run_id, tmp / "out", pdf=True)
        t["export Excel + PDF"] = time.perf_counter() - t0
        peak = tracemalloc.get_traced_memory()[1] if measure_memory else 0
        if measure_memory:
            tracemalloc.stop()
        lines = len(ReconciliationService(db).load(run_id).result.lines)
        db.dispose()
    print(f"\n{n:,} invoices per side (target) -> {lines:,} reconciliation lines")
    for k, v in t.items():
        print(f"  {k:<32} {v:7.1f} s")
    mem = f"   peak Python memory {peak / 1e6:,.0f} MB" if measure_memory else ""
    print(f"  {'total':<32} {sum(t.values()):7.1f} s{mem}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--mem"]
    for size in (int(a) for a in (args or ["10000"])):
        bench(size, measure_memory="--mem" in sys.argv)
