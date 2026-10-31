"""Phase 15 commands: GSTR-1 JSON, GSTR-3B draft, invoices entered by hand."""
from __future__ import annotations


def cmd_gstr1_json(db, args) -> None:
    from .services.clients import ClientService
    from .services.gstr1_prep import Gstr1PrepService

    client = ClientService(db).resolve(args.client)
    svc = Gstr1PrepService(db)
    draft = svc.draft(client.id, args.period)
    for section, n in draft.counts.items():
        print(f"  {section:<6} {n:>5} document(s)")
    for i in draft.issues:
        print(f"  {'LEFT OUT' if i.severity == 'error' else 'check':<8} {i.doc.number if i.doc else '':<18} {i.message}")
    print(f"Saved {svc.save(client.id, draft, args.out, args.user)}")


def add_commands(sub) -> None:
    g = sub.add_parser("gstr1-json", help="GSTR-1 JSON of a month from the sales register (portal / Offline Tool)")
    g.add_argument("--client", required=True)
    g.add_argument("--period", required=True, help="tax period (YYYY-MM)")
    g.add_argument("--out", required=True, help="the .json file to write")
    g.set_defaults(func=cmd_gstr1_json)


def permission_for(args) -> str | None:
    if args.command == "gstr1-json":
        return "export"
    return None
