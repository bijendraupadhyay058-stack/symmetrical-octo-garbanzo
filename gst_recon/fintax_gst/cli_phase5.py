"""Phase 5–6 commands: due-date calendar and extensions, settings, GSTR-9 working."""
from __future__ import annotations

from datetime import date


def cmd_calendar(db, args) -> None:
    from .services.calendar import CalendarService

    svc = CalendarService(db)
    if args.action == "extend":
        o = svc.add_override(args.return_type, args.period, date.fromisoformat(args.due), args.reference or "",
                             args.session, (args.states or "").split(","))
        print(f"Extension #{o.id}: {o.return_type} {o.period} due {o.due_date:%d-%m-%Y} ({o.reference})"
              + (f" for states {o.state_codes}" if o.state_codes else " for all states"))
    elif args.action == "extensions":
        for o in svc.override_rows():
            print(f"#{o.id:<4} {o.return_type:<8} {o.period:<8} {o.due_date:%d-%m-%Y}  {o.reference:<40} "
                  f"{o.state_codes or 'all states'}")
    elif args.action == "delete":
        svc.delete_override(args.id, args.session)
        print(f"Extension #{args.id} deleted")
    else:
        as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
        rows = svc.upcoming(as_of, args.days)
        for u in rows:
            flag = "OVERDUE" if u.overdue else ""
            ext = f" ({u.item.basis})" if u.item.extended else ""
            print(f"{u.item.due:%d-%m-%Y}  {u.item.return_type:<8} {u.item.period:<8} {u.client[:34]:<34} "
                  f"{u.gstin}  {u.status:<13} {flag}{ext}")
        if not rows:
            print("Nothing due in the window.")


def cmd_setting(db, args) -> None:
    import json

    from .services.security import DEFAULTS, SecurityService

    sec = SecurityService(db)
    if args.action == "set":
        if args.key not in DEFAULTS:
            raise ValueError(f"Unknown setting '{args.key}' – one of: {', '.join(DEFAULTS)}")
        try:
            value = json.loads(args.value)
        except (TypeError, ValueError):
            raise ValueError("Value must be JSON, e.g. true, 24 or \"text\"") from None
        sec.set_setting(args.key, value, args.session)
    for key in DEFAULTS:
        print(f"{key:<24} {json.dumps(sec.setting(key))}")


def cmd_gstr9(db, args) -> None:
    from .core.money import fmt_inr
    from .services.clients import ClientService
    from .services.gstr9 import Gstr9Service

    client = ClientService(db).resolve(args.client)
    w = Gstr9Service(db).working(client.id, args.fy)
    print(f"GSTR-9 working – {client.name} ({client.gstin}) FY {args.fy}")
    print(f"  {'Table':<7}{'Returns taxable':>17}{'Returns tax':>15}{'Books taxable':>17}{'Books tax':>15}")
    for r in w.table4 + w.table5 + w.table6 + w.table7:
        g, b = r.gstr1, r.books
        taxable = fmt_inr(g.taxable) if g is not None and (r in w.table4 or r in w.table5) else ""
        print(f"  {r.code:<7}{taxable:>17}{fmt_inr(g.total) if g else '':>15}"
              f"{fmt_inr(b.taxable) if b else '':>17}{fmt_inr(b.total) if b else '':>15}")
    for x in w.table9:
        f = lambda v: fmt_inr(v) if v is not None else "-"  # noqa: E731
        print(f"  Table 9 {x.head:<5} payable {f(x.payable):>14}  declared in 3B {f(x.declared):>14}  "
              f"paid {f(x.paid):>14}")
    for a in w.amendments:
        change = fmt_inr(a["delta"].taxable) if a["delta"] else "-"
        print(f"  Amendment {a['period']} {a['section']:<6} {a['document']:<22} change {change:>12}  {a['status']}")
    for n in w.notes:
        print(f"  ! {n}")
    if args.out:
        from .reports.annual_report import export_annual

        print(f"Workbook: {export_annual(db, client.id, args.fy, args.out, user=args.user)}")


def cmd_gstr9c(db, args) -> None:
    from .core.money import fmt_inr
    from .services.clients import ClientService
    from .services.gstr9c import Gstr9cService

    client = ClientService(db).resolve(args.client)
    svc = Gstr9cService(db)
    if args.action == "set":
        if not args.item:
            raise ValueError("Give --item (e.g. 5A) with --amount and/or --note")
        svc.set_input(client.id, args.fy, args.item, args.amount, args.note or "", args.session)
        print(f"{args.item.upper()} recorded for FY {args.fy}")
    st = svc.statement(client.id, args.fy)
    print(f"GSTR-9C reconciliation – {client.name} ({client.gstin}) FY {args.fy}")
    for x in st.table5 + st.table7 + st.table12:
        print(f"  {x.code:<4} {fmt_inr(x.amount):>16}  {x.label[:60]:<60} {x.source}")
    tot, paid, un = st.table9_total, st.table9_paid, st.table9_unreconciled
    for h in ("igst", "cgst", "sgst", "cess"):
        f = lambda v: fmt_inr(v) if v is not None else "-"  # noqa: E731
        print(f"  9 {h.upper():<5} books {f(tot[h]):>14}  paid per GSTR-9 {f(paid.get(h)):>14}  "
              f"un-reconciled {f(un.get(h)):>14}")
    for k, reason in st.reasons.items():
        if reason:
            print(f"  {k}: {reason}")
    for n in st.notes:
        print(f"  ! {n}")
    if args.out:
        from .reports.annual_report import export_annual

        print(f"Workbook: {export_annual(db, client.id, args.fy, args.out, user=args.user)}")


def add_commands(sub) -> None:
    c9 = sub.add_parser("gstr9c", help="GSTR-9C reconciliation statement (show, or set an audited figure/reason)")
    c9.add_argument("action", nargs="?", default="show", choices=["show", "set"])
    c9.add_argument("--client", required=True)
    c9.add_argument("--fy", required=True)
    c9.add_argument("--item", help="set: 5A–5O, 7B–7D, 12A–12C, 9INT, 9FEE, 9PEN, 9OTH, or reasons R6, R8, R10, R13")
    c9.add_argument("--amount", help="set: amount (omit to clear and use the default)")
    c9.add_argument("--note", help="set: note or reason")
    c9.add_argument("--out", help="folder for the annual workbook (GSTR-9, GSTR-9C)")
    c9.set_defaults(func=cmd_gstr9c)

    g9 = sub.add_parser("gstr9", help="GSTR-9 working (Tables 4–9) from GSTR-1, GSTR-3B and the sales register")
    g9.add_argument("--client", required=True)
    g9.add_argument("--fy", required=True)
    g9.add_argument("--out", help="folder for the annual workbook (Table 8 and Tables 4–9)")
    g9.set_defaults(func=cmd_gstr9, perm="view")

    st = sub.add_parser("setting", help="application settings, e.g. setting set web_uploads true")
    st.add_argument("action", nargs="?", default="list", choices=["list", "set"])
    st.add_argument("key", nargs="?")
    st.add_argument("value", nargs="?")
    st.set_defaults(func=cmd_setting)

    c = sub.add_parser("calendar", help="returns due (monthly / QRMP) and recorded due-date extensions")
    c.add_argument("action", nargs="?", default="upcoming", choices=["upcoming", "extend", "extensions", "delete"])
    c.add_argument("--days", type=int, default=30, help="upcoming: days ahead (overdue items of 60 days included)")
    c.add_argument("--as-of", help="upcoming: reference date YYYY-MM-DD (default today)")
    c.add_argument("--return", dest="return_type", help="extend: GSTR-1, IFF, GSTR-3B, PMT-06, GSTR-9 or GSTR-9C")
    c.add_argument("--period", help="extend: YYYY-MM (quarter-end month for QRMP; FY such as 2025-26 for GSTR-9)")
    c.add_argument("--due", help="extend: new due date YYYY-MM-DD")
    c.add_argument("--reference", help="extend: notification / circular number")
    c.add_argument("--states", help="extend: state codes the extension applies to, e.g. 27,29 (default all)")
    c.add_argument("--id", type=int, help="delete: extension id")
    c.set_defaults(func=cmd_calendar)


def permission_for(args) -> str | None:
    if args.command == "gstr9c":
        return "review" if args.action == "set" else "view"
    if args.command == "setting":
        return "settings" if args.action == "set" else "view"
    if args.command == "calendar":
        return "settings" if args.action in ("extend", "delete") else "view"
    return None
