"""Phase 12 commands: direct Tally import, batch processing, firm work dashboard."""
from __future__ import annotations


def cmd_tally(db, args) -> None:
    from .services.tally import TallyService

    svc = TallyService(db)
    if args.action == "companies":
        names = svc.companies(args.url)
        print("\n".join(f"  {n}" for n in names) if names else "  No company open in Tally")
        return
    if not (args.client and args.company and args.period_from):
        raise ValueError("Give --client, --company (as named in Tally), --from and optionally --to")
    from .services.clients import ClientService

    client = ClientService(db).resolve(args.client)
    path = svc.fetch(client.id, args.company, args.period_from, args.period_to, args.url, args.user)
    print(f"Fetched from Tally: {path}")
    from .cli import cmd_import

    for name, value in (("file", str(path)), ("period", None), ("template", None), ("mapping", None),
                        ("save_template", None), ("sheet", None)):
        setattr(args, name, value)
    cmd_import(db, args)


def cmd_batch(db, args) -> None:
    from .services.batch import BatchService, write_example

    if args.example:
        print(f"Example batch folder created: {write_example(args.folder)}")
        return
    res = BatchService(db).run(args.folder, user=args.user, pdf=args.pdf, rerun=args.rerun, dry_run=args.check,
                               create_clients=args.add_clients)
    for r in res.rows:
        print(f"  {r.action:<10} {r.client[:40]:<40} {r.period:<8} {r.item[:36]:<36} {r.detail}")
    print(("Check only – nothing changed." if args.check else res.text().capitalize() + ".") +
          (f" Summary: {res.summary_path}" if res.summary_path else ""))


def cmd_firm(db, args) -> None:
    from .services.firm import FirmService, export_xlsx

    work = FirmService(db).work(args.period, staff=args.staff)
    for c in work.clients:
        print(f"  {c.stage:<24} {c.name[:34]:<34} {c.staff[:12]:<12} {c.next_step}")
    if work.deadlines:
        print("Deadlines:")
        for d in work.deadlines:
            print(f"  {d.on:%d-%m-%Y} {d.state:<9} {d.client[:34]:<34} {d.item}")
    print("Staff: " + "; ".join(f"{s.person} – {s.clients} client(s), {s.pending_lines} open line(s)"
                                for s in work.staff))
    if args.excel:
        print(f"Saved {export_xlsx(work, args.excel)}")


def add_commands(sub) -> None:
    t = sub.add_parser("tally", help="import purchase / sales vouchers straight from TallyPrime (XML interface)")
    t.add_argument("action", choices=["companies", "import"])
    t.add_argument("--url", help="Tally address (default: setting tally_url, http://localhost:9000)")
    t.add_argument("--client", help="import: client id or GSTIN")
    t.add_argument("--company", help="import: company name as open in Tally")
    t.add_argument("--from", dest="period_from", help="import: first month (YYYY-MM)")
    t.add_argument("--to", dest="period_to", help="import: last month (YYYY-MM, default --from)")
    t.add_argument("--source", default="books", choices=["books", "sales"], help="purchase (books) or sales register")
    t.add_argument("--preview", action="store_true", help="show the preview only; save nothing (the fetched file "
                                                          "is kept)")
    t.set_defaults(func=cmd_tally)

    b = sub.add_parser("batch", help="import, reconcile and report a folder of clients (client folder with GSTIN "
                                     "\\ month folder \\ files)")
    b.add_argument("folder", help="the batch folder")
    b.add_argument("--check", action="store_true", help="list what would be imported; change nothing")
    b.add_argument("--add-clients", action="store_true", help="add clients that do not exist (name from folder)")
    b.add_argument("--pdf", action="store_true", help="also write PDF reports")
    b.add_argument("--rerun", action="store_true", help="reconcile again even if no new file was imported")
    b.add_argument("--example", action="store_true", help="create an example batch folder at FOLDER instead")
    b.set_defaults(func=cmd_batch)

    f = sub.add_parser("firm", help="firm work dashboard: every client's stage for a month, deadlines, staff")
    f.add_argument("--period", required=True, help="tax period (YYYY-MM)")
    f.add_argument("--staff", help="only the clients of this staff member")
    f.add_argument("--excel", help="also save the dashboard to this .xlsx file")
    f.set_defaults(func=cmd_firm)


def permission_for(args) -> str | None:
    if args.command == "firm":
        return "view"
    if args.command == "batch":
        if args.check or args.example:
            return "view"
        return "manage_clients" if args.add_clients else "reconcile"
    if args.command == "tally":
        return "import" if args.action == "import" else "view"
    return None
