"""Phase 11 commands: interest and late fees."""
from __future__ import annotations

from datetime import date


def _date(text: str | None) -> date | None:
    return date.fromisoformat(text) if text else None


def cmd_interest(db, args) -> None:
    from .core.money import fmt_inr
    from .services.clients import ClientService
    from .services.interest import HEADS, KINDS, InterestService

    client = ClientService(db).resolve(args.client)
    svc = InterestService(db)
    if args.action == "filed":
        if not (args.return_type and args.period):
            raise ValueError("Give --return (GSTR-1, GSTR-3B or GSTR-9), --period and --date (omit --date to remove)")
        svc.set_filing(client.id, args.return_type, args.period, _date(args.date), args.session, args.arn or "",
                       args.nil, args.note or "")
        print(f"{args.return_type} {args.period}: " + (f"filed on {args.date}" if args.date else "removed"))
    elif args.action == "import-filings":
        if not args.file:
            raise ValueError("Give --file with Return type, Period, Date of filing (and optionally ARN, Nil)")
        rows, problems = svc.import_filings(client.id, args.file, args.session, apply=not args.preview)
        for r in rows:
            print(f"  {r[0]:<8} {r[1]:<8} filed {r[2]}  {r[3]}{'  nil' if r[4] else ''}")
        for p in problems:
            print(f"  ! {p}")
        print(f"{len(rows)} filing(s) " + ("previewed – nothing saved" if args.preview else "recorded"))
        if args.preview:
            return
    elif args.action == "settle":
        if not (args.kind and args.period):
            raise ValueError("Give --kind (SHORT_PAYMENT / EXCESS_ITC), --period and --status (SETTLED with --date, "
                             "NOT_PAYABLE with --note); omit --status to remove")
        svc.set_settlement(client.id, args.kind, args.period, args.status, args.session, _date(args.date),
                           args.reference or "", args.note or "")
        print(f"{args.kind.upper()} {args.period}: {args.status or 'removed'}")
    if not args.fy:
        return
    w = svc.working(client.id, args.fy, _date(args.as_of))
    print(f"Interest and late fee – {client.name} ({client.gstin}) FY {args.fy}, as of {w.as_of:%d-%m-%Y}")
    for r in w.late:
        fee = f"late fee {fmt_inr(r.fee_total):>10}" if r.fee_cgst is not None else "late fee  not computed"
        print(f"  {r.return_type:<8} {r.period:<8} due {r.due:%d-%m-%Y} filed {r.filed:%d-%m-%Y} "
              f"{r.days:>4} day(s)  {fee}  interest {fmt_inr(r.interest_total):>10}")
    for e in w.exposures:
        print(f"  {KINDS[e.kind][:30]:<30} {e.period} {e.head.upper():<5} {fmt_inr(e.amount):>12}  "
              f"{e.days:>4} day(s) interest {fmt_inr(e.interest):>10}  {e.status}")
    d = w.drc03()
    print("  DRC-03 (not yet paid): " + "; ".join(
        f"{h.upper()} tax {fmt_inr(d[h]['tax'])} interest {fmt_inr(d[h]['interest'])} fee {fmt_inr(d[h]['fee'])}"
        for h in HEADS if any(d[h].values())) or "  DRC-03 (not yet paid): nil")
    for n in w.notes:
        print(f"  ! {n}")
    if args.out:
        from .reports.interest_report import export_interest

        print(f"Workbook: {export_interest(db, client.id, args.fy, args.out, w.as_of, args.user)}")


def add_commands(sub) -> None:
    i = sub.add_parser("interest", help="interest (section 50) and late fees: working, filing dates, settlements")
    i.add_argument("action", nargs="?", default="show", choices=["show", "filed", "import-filings", "settle"])
    i.add_argument("--client", required=True)
    i.add_argument("--fy", help="financial year of the working, e.g. 2025-26")
    i.add_argument("--as-of", help="date to compute interest to while unpaid (YYYY-MM-DD, default today)")
    i.add_argument("--out", help="folder for the Excel working")
    i.add_argument("--return", dest="return_type", help="filed: GSTR-1, GSTR-3B or GSTR-9")
    i.add_argument("--period", help="filed / settle: YYYY-MM (GSTR-9: the FY)")
    i.add_argument("--date", help="filed: date of filing; settle: date of payment / reversal (YYYY-MM-DD)")
    i.add_argument("--arn")
    i.add_argument("--nil", action="store_true", help="filed: a nil return")
    i.add_argument("--kind", help="settle: SHORT_PAYMENT or EXCESS_ITC")
    i.add_argument("--status", help="settle: SETTLED or NOT_PAYABLE")
    i.add_argument("--reference", help="settle: DRC-03 ARN or the return it was paid / reversed in")
    i.add_argument("--note")
    i.add_argument("--file", help="import-filings: CSV/Excel with Return type, Period, Date of filing")
    i.add_argument("--preview", action="store_true")
    i.set_defaults(func=cmd_interest)


def permission_for(args) -> str | None:
    if args.command == "interest":
        return "review" if args.action in ("filed", "import-filings", "settle") else "view"
    return None
