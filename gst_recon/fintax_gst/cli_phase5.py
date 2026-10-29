"""Phase 5 commands: return due-date calendar and extensions."""
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


def add_commands(sub) -> None:
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
    if args.command == "setting":
        return "settings" if args.action == "set" else "view"
    if args.command == "calendar":
        return "settings" if args.action in ("extend", "delete") else "view"
    return None
