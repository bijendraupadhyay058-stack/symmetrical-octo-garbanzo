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


def cmd_gstr3b_draft(db, args) -> None:
    from .compliance.gstr3b_draft import HEADS
    from .services.clients import ClientService
    from .services.gstr3b_draft import Gstr3bDraftService

    client = ClientService(db).resolve(args.client)
    d = Gstr3bDraftService(db).draft(client.id, args.period)
    so = d.setoff
    for h in HEADS:
        print(f"  {h.upper():<5} payable {so.liability[h] + so.rcm[h]:>14}  ITC available {so.credit[h]:>14}  "
              f"cash {so.cash[h]:>12}  carried forward {so.carried[h]:>12}")
    print(f"Cash to pay: {so.total_cash}")
    for n in d.notes:
        print(f"  note: {n}")
    if args.pdf:
        from .reports.gstr3b_draft_pdf import build_pdf

        print(f"Saved {build_pdf(d, args.pdf)}")


def add_commands(sub) -> None:
    g = sub.add_parser("gstr1-json", help="GSTR-1 JSON of a month from the sales register (portal / Offline Tool)")
    g.add_argument("--client", required=True)
    g.add_argument("--period", required=True, help="tax period (YYYY-MM)")
    g.add_argument("--out", required=True, help="the .json file to write")
    g.set_defaults(func=cmd_gstr1_json)

    t = sub.add_parser("gstr3b-draft", help="GSTR-3B figures of a month, ITC set-off and cash to pay")
    t.add_argument("--client", required=True)
    t.add_argument("--period", required=True, help="tax period (YYYY-MM)")
    t.add_argument("--pdf", help="also save the one-page draft to this .pdf file")
    t.set_defaults(func=cmd_gstr3b_draft)


def permission_for(args) -> str | None:
    if args.command in ("gstr1-json", "gstr3b-draft"):
        return "export"
    return None
