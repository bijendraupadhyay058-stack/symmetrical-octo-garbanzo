"""Phase 10 commands: TDS / TCS credits received."""
from __future__ import annotations


def cmd_tds_tcs(db, args) -> None:
    from .core.money import fmt_inr
    from .services.clients import ClientService
    from .services.tds_tcs import TdsTcsService

    client = ClientService(db).resolve(args.client)
    svc = TdsTcsService(db)
    if args.action == "import":
        if not args.file:
            raise ValueError("Give --file with the 'TDS and TCS credit received' download (Excel/CSV)")
        pv = svc.preview(client.id, args.file) if args.preview else svc.import_file(client.id, args.file, args.user)
        for c in pv.new:
            print(f"  new      {c.kind} {c.period} {c.party_gstin} {c.party_name[:30]:<30} value {fmt_inr(c.value):>14}"
                  f"  tax {fmt_inr(c.tax):>12}  {c.action}")
        for c, before in pv.changed:
            print(f"  changed  {c.kind} {c.period} {c.party_gstin} action {before} -> {c.action}")
        for p in pv.problems:
            print(f"  ! {p}")
        print(f"{len(pv.new)} new credit(s), {len(pv.changed)} changed action(s), {pv.unchanged} already imported"
              + (" – preview only, nothing saved" if args.preview else ""))
        if args.preview:
            return
    st = svc.statement(client.id, args.fy)
    print(f"TDS / TCS credit received – {client.name} ({client.gstin}) FY {args.fy}")
    for p in st.parties:
        sales = f"sales {fmt_inr(p.sales_taxable):>14}  " if p.sales_taxable is not None else " " * 22
        print(f"  {p.kind} {p.gstin} {p.name[:28]:<28} {sales}value {fmt_inr(p.value):>14}  tax {fmt_inr(p.tax):>12}"
              f"  accepted {fmt_inr(p.accepted):>10}  pending {fmt_inr(p.pending):>10}")
    for kind in ("TDS", "TCS"):
        print(f"  {kind} credit: accepted {fmt_inr(st.total(kind, 'ACCEPTED'))}, pending "
              f"{fmt_inr(st.total(kind, 'PENDING'))}, rejected {fmt_inr(st.total(kind, 'REJECTED'))}")
    for f in st.findings:
        print(f"  [{f.severity.upper()}] {f.kind} {f.period or 'year'}: {f.text}")


def add_commands(sub) -> None:
    t = sub.add_parser("tds-tcs", help="TDS (GSTR-7) / TCS (GSTR-8) credit received: import and statement")
    t.add_argument("action", nargs="?", default="show", choices=["show", "import"])
    t.add_argument("--client", required=True)
    t.add_argument("--fy", required=True)
    t.add_argument("--file", help="import: the portal's 'TDS and TCS credit received' download (Excel/CSV)")
    t.add_argument("--preview", action="store_true", help="import: show what would be saved; save nothing")
    t.set_defaults(func=cmd_tds_tcs)

    a = sub.add_parser("activity", help="per-user activity from the audit log (partners and administrators)")
    a.add_argument("--days", type=int, default=30)
    a.add_argument("--user", dest="user_filter", help="one user: also list their latest actions")
    a.add_argument("--recent", type=int, default=20, help="with --user: how many latest actions to list")
    a.set_defaults(func=cmd_activity)


def permission_for(args) -> str | None:
    if args.command == "tds-tcs":
        return "import" if args.action == "import" else "view"
    if args.command == "activity":
        return "settings"
    return None


def cmd_activity(db, args) -> None:
    from datetime import timedelta

    from .db.models import utcnow
    from .services.security import SecurityService

    since = utcnow() - timedelta(days=args.days)
    rows = SecurityService(db).activity(args.session, since, args.user_filter)
    print(f"Activity since {since:%d-%m-%Y} (UTC), from the audit log")
    for u in rows:
        top = ", ".join(f"{a} {n}" for a, n in u.actions.most_common(6))
        print(f"  {u.user:<16} {u.total:>6} action(s)  review edits {u.edits:>5}  clients {len(u.clients):>3}  "
              f"last {u.last:%d-%m-%Y %H:%M}  ({top})")
        if args.user_filter:
            for a in u.recent[:args.recent]:
                print(f"      {a.at:%d-%m-%Y %H:%M}  {a.action:<20} {a.entity:<14} {a.entity_id}")
    if not rows:
        print("  no activity")
