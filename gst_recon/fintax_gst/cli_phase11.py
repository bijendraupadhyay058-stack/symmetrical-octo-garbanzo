"""Phase 11 commands: interest and late fees, supplier compliance scores, GST notices."""
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

    s = sub.add_parser("supplier-scores", help="supplier compliance scores for a year (risk list for follow-up)")
    s.add_argument("--client", required=True)
    s.add_argument("--fy", required=True)
    s.add_argument("--top", type=int, help="show only the first N (highest risk first)")
    s.add_argument("--why", action="store_true", help="explain each score")
    s.add_argument("--out", help="folder for the Excel list")
    s.set_defaults(func=cmd_supplier_scores)

    n = sub.add_parser("notice", help="GST notices register and draft replies (DRC-01B, DRC-01C, ASMT-10)")
    n.add_argument("action", nargs="?", default="list", choices=["list", "add", "update", "delete", "draft"])
    n.add_argument("--client", required=True)
    n.add_argument("--id", type=int, help="update / delete / draft: notice number")
    n.add_argument("--form", help="DRC-01B, DRC-01C, ASMT-10 or OTHER")
    n.add_argument("--reference", help="notice / DIN / reference number")
    n.add_argument("--date", dest="notice_date", help="date of the notice (YYYY-MM-DD)")
    n.add_argument("--from", dest="period_from", help="first tax period (YYYY-MM)")
    n.add_argument("--to", dest="period_to", help="last tax period (YYYY-MM)")
    n.add_argument("--amount", help="difference stated in the notice")
    n.add_argument("--reply-due", dest="reply_due", help="YYYY-MM-DD")
    n.add_argument("--status", help="OPEN, REPLIED or CLOSED")
    n.add_argument("--officer", help="designation / jurisdiction of the officer")
    n.add_argument("--remarks")
    n.add_argument("--out", help="draft: folder for the Word reply")
    n.add_argument("--as-of", help="draft: date for interest on unpaid amounts (YYYY-MM-DD, default today)")
    n.add_argument("--signatory", help="draft: name of the authorised signatory")
    n.set_defaults(func=cmd_notice)


def permission_for(args) -> str | None:
    if args.command == "interest":
        return "review" if args.action in ("filed", "import-filings", "settle") else "view"
    if args.command == "notice":
        return {"list": "view", "draft": "export"}.get(args.action, "review")
    return None


def cmd_supplier_scores(db, args) -> None:
    from .core.money import fmt_inr
    from .services.clients import ClientService
    from .services.supplier_score import SupplierScoreService

    client = ClientService(db).resolve(args.client)
    svc = SupplierScoreService(db)
    rows, notes = svc.scores(client.id, args.fy)
    print(f"Supplier compliance scores – {client.name} ({client.gstin}) FY {args.fy}")
    for x in rows[:args.top] if args.top else rows:
        print(f"  {x.score:>3} {x.band:<15} {x.gstin} {x.name[:30]:<30} ITC at risk {fmt_inr(x.itc_at_risk):>12}")
        if args.why:
            for r in x.reasons:
                print(f"        {r}")
    for n in notes:
        print(f"  ! {n}")
    if args.out:
        print(f"Workbook: {svc.export(client.id, args.fy, args.out, args.user)}")


def cmd_notice(db, args) -> None:
    from .core.money import fmt_inr
    from .services.clients import ClientService
    from .services.notices import NoticeService

    client = ClientService(db).resolve(args.client)
    svc = NoticeService(db)
    fields = {k: getattr(args, k) for k in ("form", "reference", "notice_date", "period_from", "period_to", "amount",
                                             "reply_due", "status", "officer", "remarks")
              if getattr(args, k) is not None}
    if args.action == "add":
        nid = svc.add(client.id, args.session, **fields)
        print(f"Notice #{nid} recorded")
    elif args.action == "update":
        if not args.id:
            raise ValueError("Give --id of the notice")
        svc.update(args.id, args.session, **fields)
        print(f"Notice #{args.id} updated")
    elif args.action == "delete":
        svc.delete(args.id, args.session)
        print(f"Notice #{args.id} deleted")
    elif args.action == "draft":
        if not (args.id and args.out):
            raise ValueError("Give --id of the notice and --out for the Word draft")
        path, draft = svc.draft(args.id, args.out, date.fromisoformat(args.as_of) if args.as_of else None,
                                args.signatory or "", args.user)
        print(f"Draft reply: {path}")
        print(f"{draft.placeholders} highlighted item(s) to complete or delete before sending (working notes and "
              "placeholders). A DRAFT for review – nothing is filed.")
        return
    for n in svc.list(client.id):
        amount = fmt_inr(n.amount) if n.amount is not None else "-"
        due = f"reply by {n.reply_due:%d-%m-%Y}" if n.reply_due else ""
        print(f"  #{n.id:<4} {n.form:<8} {n.reference[:24]:<24} {n.notice_date:%d-%m-%Y} {n.period_from}..{n.period_to}"
              f"  ₹{amount:>12}  {n.status:<8} {due}")


