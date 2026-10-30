"""Command-line interface (Phase 1). The PySide6 desktop UI uses the same services."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import logging
import sys
import time
from datetime import date
from decimal import Decimal
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import PRODUCT_FULL_NAME, TAGLINE, __version__
from .core.models import ReconSettings, Source
from .core.money import fmt_inr
from .db.database import Database, default_home, open_database
from .engine.matcher import OperationCancelled
from .engine.summary import DASHBOARD_LABELS, category_summary, dashboard
from .importers.pipeline import ImportPreview, MappingRequired
from .importers.readers import UnsupportedFileError
from .services.clients import ClientService
from .cli_phase3 import add_commands as add_phase3_commands
from .cli_phase3 import permission_for as _permission_phase3
from .cli_phase4 import add_commands as add_phase4_commands
from .cli_phase4 import permission_for as _permission_phase4
from .cli_phase5 import add_commands as add_phase5_commands
from .cli_phase5 import permission_for as _permission_phase5
from .services.auth import Session
from .services.common import ServiceError, current_user
from .services.imports import ImportService
from .services.reconciliation import ReconciliationService, fy_periods
from .services.reports import export_run

log = logging.getLogger("fintax_gst")


def setup_logging(home: Path, verbose: bool) -> None:
    home.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(home / "fintaxpro.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)


def _bar(pct: int, msg: str) -> None:
    filled = pct * 30 // 100
    sys.stderr.write(f"\r[{'#' * filled}{'.' * (30 - filled)}] {pct:3d}% {msg[:50]:<50}")
    if pct >= 100:
        sys.stderr.write("\n")
    sys.stderr.flush()


def _money(v: Decimal) -> str:
    return f"₹ {fmt_inr(v)}"


def print_preview(p: ImportPreview, limit: int = 15) -> None:
    s = p.summary()
    print(f"\nFile      : {p.file_name}\nLayout    : {p.layout_label}\nSource    : {p.source.value}"
          f"\nPeriod    : {p.period or '(from voucher dates)'}")
    for sheet, m in p.mappings.items():
        print(f"Mapping [{sheet}]:")
        for field, cols in m.fields.items():
            print(f"    {field:<22} <- {', '.join(cols)}")
        for note in m.notes:
            print(f"    note: {note}")
    print(f"Rows read : {s['rows_read']}   valid documents: {s['valid_documents']}   "
          f"new: {s['new_documents']}   already imported: {s['already_imported_documents']}")
    print(f"Rejected  : {s['rejected_rows']}   duplicate rows in file: {s['duplicate_rows_in_file']}   "
          f"ignored (total rows): {s['ignored_rows']}   with warnings: {s['rows_with_warnings']}")
    print(f"Taxable   : {_money(s['taxable_total'])}   ITC: {_money(s['itc_total'])}")
    for w in p.file_warnings:
        print(f"  ! {w}")
    shown = [i for i in p.issues if i.severity != "info"][:limit]
    for i in shown:
        print(f"  [{i.severity.upper():9}] row {i.row}: {i.message}")
    rest = len([i for i in p.issues if i.severity != "info"]) - len(shown)
    if rest > 0:
        print(f"  ... {rest} more issue(s) – all are saved with the import and listed in the report")
    if p.already_imported_file_id:
        print(f"  ! This exact file was already imported (import #{p.already_imported_file_id}).")


def print_dashboard(lines, comparison: str = "BOOKS_VS_GSTR2B") -> None:
    from .core.models import relabel

    lab = lambda t: relabel(t, comparison)  # noqa: E731
    d = dashboard(lines)
    print("\n  FIN TAX PRO – Reconciliation dashboard")
    print("  " + "-" * 62)
    for key, label, kind in DASHBOARD_LABELS:
        v = d[key]
        print(f"  {lab(label):<44} {(_money(v) if kind == 'money' else str(v)):>18}")
    print(f"  {'Matching percentage':<44} {str(d['match_percentage']) + '%':>18}")
    print("\n  " + lab("Category                                         Lines      ITC difference"))
    for r in category_summary(lines):
        if r.lines:
            print(f"  {lab(r.category.value):<46} {r.lines:>6} {_money(r.itc_difference):>20}")


# --------------------------------------------------------------- commands
def cmd_init(db: Database, args) -> None:
    print(f"Database ready at {db.location} (schema v{db.current_version()})")


def cmd_client(db: Database, args) -> None:
    svc = ClientService(db)
    if args.action == "add":
        c = svc.create(args.gstin, user=args.user, name=args.name, trade_name=args.trade_name or args.name,
                       financial_year=args.fy or "", registration_type=args.registration_type,
                       return_frequency=args.frequency, address=args.address or "",
                       contact_person=args.contact or "", email=args.email or "", mobile=args.mobile or "")
        print(f"Client #{c.id} created: {c.name} {c.gstin} ({c.state}), PAN {c.pan}")
    else:
        clients = svc.list(pan=args.pan)
        if not clients:
            print("No clients yet. Add one with: fintax-gst client add --gstin ... --name ...")
        for c in clients:
            print(f"#{c.id:<4} {c.gstin}  {c.name:<40} PAN {c.pan}  FY {c.financial_year or '-'}  {c.return_frequency}")


def _load_template(svc: ImportService, args) -> dict | str | None:
    if args.mapping:
        return json.loads(Path(args.mapping).read_text(encoding="utf-8"))
    return args.template


def cmd_import(db: Database, args) -> None:
    client = ClientService(db).resolve(args.client)
    svc = ImportService(db)
    try:
        template = _load_template(svc, args)
        if template is None:
            preview = svc.preview_auto(client.id, args.file, Source(args.source.upper()), args.period, args.sheet)
        else:
            preview = svc.preview(client.id, args.file, Source(args.source.upper()), args.period, template,
                                  args.sheet)
    except MappingRequired as exc:
        print(f"\nColumn mapping needed – {exc}")
        print("Detected so far:")
        for f, cols in exc.mapping.fields.items():
            print(f"    {f:<22} <- {', '.join(cols)}")
        print("\nCreate a JSON file such as:\n  {\"fields\": {\"supplier_gstin\": [\"Party GSTIN\"], "
              "\"invoice_no\": [\"Bill Ref\"], \"invoice_date\": [\"Bill Dt\"], \"taxable_value\": [\"Basic\"], "
              "\"cgst\": [\"CGST\"], \"sgst\": [\"SGST\"], \"igst\": [\"IGST\"]}}\n"
              "and run the import again with --mapping that.json (add --save-template NAME to reuse it).")
        raise SystemExit(2) from None
    print_preview(preview)
    if args.save_template:
        merged = {}
        for m in preview.mappings.values():
            merged.update(m.fields)
        svc.save_template(args.save_template, preview.source, {"fields": merged}, args.user)
        print(f"Mapping saved as template '{args.save_template}'")
    if args.preview:
        print("\nPreview only – nothing saved.")
        return
    sf = svc.commit(client.id, preview, args.user, progress=_bar)
    print(f"Imported as #{sf.id}: {sf.documents_imported} documents saved, {sf.rows_rejected} rows rejected, "
          f"{sf.documents_skipped_existing} already-imported documents skipped.")


def cmd_imports(db: Database, args) -> None:
    client = ClientService(db).resolve(args.client)
    svc = ImportService(db)
    if args.remove:
        n = svc.remove_import(client.id, args.remove, args.user)
        print(f"Import #{args.remove} removed ({n} documents).")
        return
    for f in svc.list_files(client.id):
        print(f"#{f.id:<4} {f.source_type:<7} {f.period or '-':<8} {f.file_name:<45} docs {f.documents_imported:<6}"
              f" rejected {f.rows_rejected:<4} skipped {f.documents_skipped_existing:<4} {f.imported_at:%d-%m-%Y %H:%M}")


def _settings(args) -> ReconSettings:
    s = ReconSettings()
    if args.amount_tolerance is not None:
        s.amount_tolerance = Decimal(args.amount_tolerance)
    if args.date_tolerance is not None:
        s.date_tolerance_days = args.date_tolerance
    if args.fuzzy_threshold is not None:
        s.fuzzy_threshold = args.fuzzy_threshold
    if args.no_fuzzy:
        s.enable_fuzzy = False
    return s


def cmd_reconcile(db: Database, args) -> None:
    client = ClientService(db).resolve(args.client)
    if args.fy:
        p_from, p_to = fy_periods(args.fy)
    else:
        p_from, p_to = args.period_from, args.period_to or args.period_from
    if not p_from:
        raise ServiceError("Give --from YYYY-MM (and optionally --to) or --fy 2025-26")
    t0 = time.perf_counter()
    run_id = ReconciliationService(db).run(client.id, p_from, p_to, _settings(args),
                                           compare_with=Source(args.compare.upper()), user=args.user, progress=_bar)
    elapsed = time.perf_counter() - t0
    ctx = ReconciliationService(db).load(run_id)
    print(f"Reconciliation run #{run_id} for {client.name} ({client.gstin}) {p_from}..{p_to} "
          f"completed in {elapsed:.1f}s")
    print_dashboard(ctx.result.lines, ctx.run.comparison)
    if args.export:
        for p in export_run(db, run_id, args.export, pdf=not args.no_pdf, user=args.user):
            print(f"Report: {p}")


def cmd_runs(db: Database, args) -> None:
    client = ClientService(db).resolve(args.client)
    for r in ReconciliationService(db).list_runs(client.id):
        d = json.loads(r.summary_json)
        print(f"#{r.id:<4} {r.period_from}..{r.period_to} {r.comparison:<16} lines {d.get('total_lines', 0):<6} "
              f"pending {d.get('pending_cases', 0):<5} {r.started_at:%d-%m-%Y %H:%M} by {r.created_by}")


def cmd_show(db: Database, args) -> None:
    ctx = ReconciliationService(db).load(args.run)
    lines = ctx.result.lines
    if args.category:
        lines = [ln for ln in lines if args.category.lower() in ln.category.value.lower()]
    if args.pending:
        lines = [ln for ln in lines if ln.status.value not in ("No Action Required", "Resolved", "Closed After Review")]
    for ln in lines:
        b, g = ln.books, ln.gstr2b
        print(f"{ln.line_no:>5} {ln.category.value:<42} {ln.supplier_gstin} "
              f"{(b.invoice_no if b else '-'):<16} {(g.invoice_no if g else '-'):<16} "
              f"ITC diff {fmt_inr(ln.diff('itc')):>12}  [{ln.status.value}]")
        if args.reasons:
            for r in ln.reasons:
                print(f"        - {r}")


def cmd_update_line(db: Database, args) -> None:
    action_date = date.fromisoformat(args.action_date) if args.action_date else None
    ReconciliationService(db).update_line(args.run, args.line, args.user, status=args.status, remarks=args.remarks,
                                          assigned_to=args.assign, action_date=action_date)
    print(f"Line {args.line} of run #{args.run} updated (audit trail recorded).")


def cmd_match(db: Database, args) -> None:
    rs = ReconciliationService(db)
    if args.action == "confirm":
        rs.confirm_match(args.run, args.line, args.user, args.remarks or "")
        print(f"Line {args.line} confirmed as a manual match.")
    elif args.action == "pair":
        if args.with_line is None:
            raise ServiceError("Give --with LINE for a manual pair")
        kept = rs.manual_match(args.run, args.line, args.with_line, args.user, args.remarks or "")
        print(f"Lines {args.line} and {args.with_line} matched as line {kept}.")
    elif args.action == "unmatch":
        new = rs.unmatch(args.run, args.line, args.user, args.remarks or "")
        print(f"Line {args.line} split; the GSTR-2B document is now line {new}. The pair will not be re-matched.")
    else:
        rs.mark_pending_clarification(args.run, args.line, args.user, args.remarks or "")
        print(f"Line {args.line} marked Pending Client or Supplier Clarification.")


def cmd_vendor(db: Database, args) -> None:
    from .services.followup import VendorService

    client = ClientService(db).resolve(args.client)
    vs = VendorService(db)
    if args.gstin:
        fields = {k: v for k, v in {"name": args.name, "contact_person": args.contact, "email": args.email,
                                    "phone": args.phone, "followup_status": args.status,
                                    "next_followup": args.next, "remarks": args.remarks}.items() if v is not None}
        v = vs.upsert(client.id, args.gstin, args.user, **fields)
        print(f"Vendor {v.gstin} saved ({v.followup_status or 'no status'}).")
        return
    for v in vs.all(client.id).values():
        nxt = f"{v.next_followup:%d-%m-%Y}" if v.next_followup else "-"
        print(f"{v.gstin}  {v.name:<34} {v.followup_status:<28} next {nxt:<10} {v.email} {v.remarks}")


def cmd_attach(db: Database, args) -> None:
    from .services.followup import AttachmentService

    att = AttachmentService(db).add(args.run, args.line, args.file, args.user, args.description or "")
    print(f"Attached {att.file_name} (sha256 {att.sha256[:12]}…) to line {args.line} of run #{args.run}.")


def cmd_open_items(db: Database, args) -> None:
    from .services.tracking import TrackingService

    client = ClientService(db).resolve(args.client)
    items = TrackingService(db).open_items(client.id)
    for i in items:
        print(f"{i.source:<7} {i.supplier_gstin} {i.invoice_no:<18} {i.invoice_date:%d-%m-%Y} {i.period} "
              f"ITC {fmt_inr(i.itc):>12}  {i.last_category:<42} {i.status}")
    print(f"{len(items)} open document(s)")


def cmd_export(db: Database, args) -> None:
    for p in export_run(db, args.run, args.out, pdf=not args.no_pdf, user=args.user):
        print(f"Report: {p}")


def cmd_backup(db: Database, args) -> None:
    print(f"Backup written to {db.backup(args.to)}")


def cmd_restore(db: Database, args) -> None:
    safety = db.restore(args.file)
    print(f"Database restored from {args.file}. Previous database saved as {safety}")


def cmd_db_copy(db: Database, args) -> None:
    from .db.database import copy_database

    target = args.to or os.environ.get("FINTAX_TARGET_DB_URL")
    if not target:
        raise ServiceError("Give --to with the target database (file path or URL), or set FINTAX_TARGET_DB_URL")
    counts = copy_database(db, target, progress=_bar)
    print(f"\nCopied {sum(counts.values())} rows from {db.location} to the target database:")
    for name, n in counts.items():
        if n:
            print(f"  {name:<22} {n:>8}")
    print("Evidence files stay in the data folder; point the new installation to the same folder "
          "(FINTAX_HOME) or copy it.")


def cmd_sample_data(_db, args) -> None:
    from .samples import write_all

    for name, p in write_all(args.out).items():
        print(f"{name:<20} {p}")


def cmd_demo(_db, args) -> None:
    """End-to-end demonstration on a fresh database inside --out."""
    from .samples import CLIENT, write_all

    out = Path(args.out)
    db_path = out / "demo.db"
    for suffix in ("", "-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)
    db = open_database(db_path)
    files = write_all(out / "sample_data")
    client = ClientService(db).create(user="demo", **CLIENT)
    print(f"Client #{client.id}: {client.name} {client.gstin}")
    svc = ImportService(db)
    for key, source in (("books_march", Source.BOOKS), ("books_april", Source.BOOKS),
                        ("gstr2b_april_json", Source.GSTR2B), ("ims_april_json", Source.IMS)):
        preview = svc.preview(client.id, files[key], source)
        print_preview(preview, limit=6)
        svc.commit(client.id, preview, "demo")
    from .services.gstr3b import Gstr3bService

    Gstr3bService(db).import_file(client.id, files["gstr3b_april_json"], user="demo")
    print("GSTR-3B April 2025 imported")
    run_id = ReconciliationService(db).run(client.id, "2025-04", user="demo", progress=_bar)
    ctx = ReconciliationService(db).load(run_id)
    print_dashboard(ctx.result.lines)
    for p in export_run(db, run_id, out / "reports", user="demo", as_of=date(2025, 5, 15)):
        print(f"Report: {p}")
    from .reports.annual_report import export_annual

    # Phase 4: outward supplies, compliance dashboard, supplier letters, working papers
    for key, source in (("sales_april", Source.SALES), ("gstr1_april_json", Source.GSTR1),
                        ("gstr1_may_json", Source.GSTR1), ("gstr1_next_json", Source.GSTR1)):
        svc.commit(client.id, svc.preview(client.id, files[key], source), "demo")
    out_run = ReconciliationService(db).run(client.id, "2025-04", compare_with=Source.GSTR1, user="demo")
    print("\nSales register vs GSTR-1:")
    print_dashboard(ReconciliationService(db).load(out_run).result.lines, "SALES_VS_GSTR1")
    for p in export_run(db, out_run, out / "reports", user="demo"):
        print(f"Report: {p}")
    from .reports.compliance_report import export_client_pdf, export_compliance_excel
    from .services.auth import SETUP_SESSION
    from .services.compliance import ComplianceService
    from .services.letters import LetterService
    from .services.papers import WorkingPaperService

    summaries = ComplianceService(db).annual_dashboard("2025-26", today=date(2025, 5, 25))
    print(f"Report: {export_compliance_excel(summaries, '2025-26', out / 'reports' / 'GST_Dashboard_2025-26.xlsx')}")
    print(f"Report: {export_client_pdf(summaries[0], out / 'reports' / f'Compliance_{client.gstin}_2025-26.pdf')}")
    letters = LetterService(db).generate(run_id, out / "reports", letter_date=date(2025, 5, 16), user="demo")
    print(f"Supplier letters: {len(letters)} written to {out / 'reports'}")
    wp = WorkingPaperService(db).prepare(run_id, out / "working_papers", SETUP_SESSION)
    print(f"Working papers: {wp.package_path}")
    from .services.gstr9c import Gstr9cService

    Gstr9cService(db).import_expenses(client.id, "2025-26", files["expense_ledger"], SETUP_SESSION)
    print("Expense ledger imported into GSTR-9C Table 14")
    print(f"Report: {export_annual(db, client.id, '2025-26', out / 'reports', user='demo')}")
    db.dispose()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fintax-gst", description=f"{PRODUCT_FULL_NAME}\n{TAGLINE}",
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=None,
                   help="database file, or a server URL such as postgresql+psycopg://user@host/fintax "
                        "(default: FINTAX_DB_URL, FINTAX_DB or the file in the data folder)")
    p.add_argument("--login", default=os.environ.get("FINTAX_USER"),
                   help="user name to log in with once users exist (password: FINTAX_PASSWORD or prompt)")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create or upgrade the database").set_defaults(func=cmd_init)

    c = sub.add_parser("client", help="manage clients")
    c.add_argument("action", choices=["add", "list"])
    c.add_argument("--gstin")
    c.add_argument("--name")
    c.add_argument("--trade-name")
    c.add_argument("--fy", help="financial year, e.g. 2025-26")
    c.add_argument("--registration-type", default="Regular")
    c.add_argument("--frequency", default="Monthly", choices=["Monthly", "Quarterly"])
    c.add_argument("--address")
    c.add_argument("--contact")
    c.add_argument("--email")
    c.add_argument("--mobile")
    c.add_argument("--pan", help="list: only GSTINs of this PAN")
    c.set_defaults(func=cmd_client)

    i = sub.add_parser("import", help="preview and import a purchase/sales register, GSTR-2B/2A, GSTR-1 or IMS file")
    i.add_argument("--client", required=True, help="client id or GSTIN")
    i.add_argument("--source", required=True, choices=["books", "gstr2b", "gstr2a", "ims", "sales", "gstr1", "gstr8a"],
                   help="gstr8a = GSTR-9 Table 8A document details (annual)")
    i.add_argument("--file", required=True)
    i.add_argument("--period", help="YYYY-MM (GSTR-2B period if not detected; books booking month override)")
    i.add_argument("--template", help="saved mapping template name")
    i.add_argument("--mapping", help="JSON file with a manual column mapping")
    i.add_argument("--save-template", help="save the mapping used under this name")
    i.add_argument("--sheet", help="import only this worksheet")
    i.add_argument("--preview", action="store_true", help="show the preview only; save nothing")
    i.set_defaults(func=cmd_import)

    il = sub.add_parser("imports", help="list (or remove unused) imports of a client")
    il.add_argument("--client", required=True)
    il.add_argument("--remove", type=int, help="import id to remove (only if not used in a reconciliation)")
    il.set_defaults(func=cmd_imports)

    r = sub.add_parser("reconcile", help="run a reconciliation")
    r.add_argument("--client", required=True)
    r.add_argument("--from", dest="period_from")
    r.add_argument("--to", dest="period_to")
    r.add_argument("--fy", help="whole financial year, e.g. 2025-26")
    r.add_argument("--compare", default="gstr2b", choices=["gstr2b", "gstr2a", "gstr1", "gstr8a"],
                   help="gstr1 = sales register vs GSTR-1 (outward); gstr8a = books vs Table 8A (use --fy)")
    r.add_argument("--amount-tolerance", help="rupees per tax component (default 1.00)")
    r.add_argument("--date-tolerance", type=int, help="days (default 7)")
    r.add_argument("--fuzzy-threshold", type=int, help="0-100 (default 85)")
    r.add_argument("--no-fuzzy", action="store_true")
    r.add_argument("--export", help="directory for the Excel/PDF report")
    r.add_argument("--no-pdf", action="store_true")
    r.set_defaults(func=cmd_reconcile)

    rl = sub.add_parser("runs", help="list reconciliation runs")
    rl.add_argument("--client", required=True)
    rl.set_defaults(func=cmd_runs)

    sh = sub.add_parser("show", help="list lines of a run")
    sh.add_argument("--run", type=int, required=True)
    sh.add_argument("--category", help="filter by category text")
    sh.add_argument("--pending", action="store_true")
    sh.add_argument("--reasons", action="store_true")
    sh.set_defaults(func=cmd_show)

    u = sub.add_parser("update-line", help="update status/remarks of an exception (audited)")
    u.add_argument("--run", type=int, required=True)
    u.add_argument("--line", type=int, required=True)
    u.add_argument("--status")
    u.add_argument("--remarks")
    u.add_argument("--assign")
    u.add_argument("--action-date", help="YYYY-MM-DD")
    u.set_defaults(func=cmd_update_line)

    m = sub.add_parser("match", help="manual decisions: confirm | pair | unmatch | clarify (audited)")
    m.add_argument("action", choices=["confirm", "pair", "unmatch", "clarify"])
    m.add_argument("--run", type=int, required=True)
    m.add_argument("--line", type=int, required=True)
    m.add_argument("--with", dest="with_line", type=int, help="pair: the other line")
    m.add_argument("--remarks")
    m.set_defaults(func=cmd_match)

    v = sub.add_parser("vendor", help="vendor follow-up register (list, or update with --gstin)")
    v.add_argument("--client", required=True)
    v.add_argument("--gstin")
    v.add_argument("--name")
    v.add_argument("--contact")
    v.add_argument("--email")
    v.add_argument("--phone")
    v.add_argument("--status", help="Not contacted | Mail sent | Reminder sent | Supplier confirmed correction | "
                                    "Supplier disputes | Closed")
    v.add_argument("--next", help="next follow-up date YYYY-MM-DD")
    v.add_argument("--remarks")
    v.set_defaults(func=cmd_vendor)

    at = sub.add_parser("attach", help="attach supporting evidence to a line")
    at.add_argument("--run", type=int, required=True)
    at.add_argument("--line", type=int, required=True)
    at.add_argument("--file", required=True)
    at.add_argument("--description")
    at.set_defaults(func=cmd_attach)

    oi = sub.add_parser("open-items", help="unresolved documents across all periods")
    oi.add_argument("--client", required=True)
    oi.set_defaults(func=cmd_open_items)

    e = sub.add_parser("export", help="export Excel (and PDF) report of a run")
    e.add_argument("--run", type=int, required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--no-pdf", action="store_true")
    e.set_defaults(func=cmd_export)

    b = sub.add_parser("backup", help="back up the database")
    b.add_argument("--to")
    b.set_defaults(func=cmd_backup)
    rs = sub.add_parser("restore", help="restore the database from a backup")
    rs.add_argument("file")
    rs.set_defaults(func=cmd_restore)

    add_phase3_commands(sub)
    add_phase4_commands(sub)
    add_phase5_commands(sub)

    dc = sub.add_parser("db-copy", help="copy all data into another empty database, e.g. SQLite → PostgreSQL")
    dc.add_argument("--to", help="target: file path or URL (or FINTAX_TARGET_DB_URL); password via PGPASSWORD")
    dc.set_defaults(func=cmd_db_copy, perm="restore")

    sd = sub.add_parser("sample-data", help="write demo input files")
    sd.add_argument("--out", required=True)
    sd.set_defaults(func=cmd_sample_data, no_db=True)
    d = sub.add_parser("demo", help="run the complete demo (fresh database in --out)")
    d.add_argument("--out", required=True)
    d.set_defaults(func=cmd_demo, no_db=True)
    return p


def permission_for(args) -> str | None:
    if getattr(args, "no_db", False):
        return None
    return _permission_phase5(args) or _permission_phase4(args) or _permission_phase3(args)


def authenticate(db: Database, args) -> Session:
    """Log in (when users exist) and check the command's permission."""
    from .services.auth import SETUP_SESSION, AuthService, require

    auth = AuthService(db)
    needed = permission_for(args)
    if not auth.has_users():
        if not (args.command == "user" and args.action == "add"):
            print("! No users configured – running in setup mode. Create an administrator with "
                  "`fintax-gst user add --username admin --role admin`.", file=sys.stderr)
        return SETUP_SESSION
    if not args.login:
        raise ServiceError("Log in with --login USER (or set FINTAX_USER); the password is read from "
                           "FINTAX_PASSWORD or prompted")
    password = os.environ.get("FINTAX_PASSWORD") or getpass.getpass(f"Password for {args.login}: ")
    session = auth.login(args.login, password)
    if needed:
        require(session, needed)
    return session


def _utf8_output() -> None:
    """Amounts are printed with ₹. On Windows, redirected output (pipes, log files, CI) uses the
    ANSI code page, which has no ₹ – switch such streams to UTF-8 instead of failing."""
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        if encoding != "utf8" and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):  # pragma: no cover - stream already in use in a way that forbids it
                pass


def main(argv: list[str] | None = None) -> int:
    _utf8_output()
    args = build_parser().parse_args(argv)
    setup_logging(default_home(), args.verbose)
    try:
        db = None if getattr(args, "no_db", False) else open_database(args.db)
        if db is not None:
            args.session = authenticate(db, args)
            args.user = args.session.username if args.session.username != "setup" else current_user()
        args.func(db, args)
        return 0
    except (ServiceError, UnsupportedFileError, ValueError, FileNotFoundError) as exc:
        log.warning("command failed: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except OperationCancelled:
        print("\nCancelled – nothing was saved.", file=sys.stderr)
        return 130
    except KeyboardInterrupt:
        print("\nInterrupted – the current transaction was rolled back.", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
