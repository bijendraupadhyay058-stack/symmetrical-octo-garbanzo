"""Phase 13 commands: client document reminders, one-page client report, update check."""
from __future__ import annotations


def cmd_reminders(db, args) -> None:
    from .services.reminders import ReminderService

    svc = ReminderService(db)
    reqs = svc.requests(args.period, args.staff, args.sales)
    if not reqs:
        print("Nothing pending from clients for this month.")
    for r in reqs:
        print(f"=== {r.name} ({r.contact or r.email or r.mobile or 'no contact'}) – reminded {r.times_reminded}x")
        print(svc.message(r, args.signature or ""))
        print()


def cmd_update(db, args) -> None:
    from . import __version__
    from .services.updates import UpdateService

    info = UpdateService().check()
    print(f"FIN TAX PRO {info.version} is available: {info.url}" if info else
          f"You have the latest version ({__version__}).")


def add_commands(sub) -> None:
    r = sub.add_parser("reminders", help="documents and clarifications each client still owes for a month, as "
                                         "messages (nothing is sent)")
    r.add_argument("--period", required=True, help="tax period (YYYY-MM)")
    r.add_argument("--staff", help="only the clients of this staff member")
    r.add_argument("--sales", action="store_true", help="also ask for the sales register")
    r.add_argument("--signature", help="name / firm at the end of each message")
    r.set_defaults(func=cmd_reminders)

    u = sub.add_parser("update-check", help="check whether a newer version is on the download page")
    u.set_defaults(func=cmd_update)


def permission_for(args) -> str | None:
    if args.command in ("reminders", "update-check"):
        return "view"
    return None
