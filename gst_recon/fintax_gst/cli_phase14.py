"""Phase 14 commands: tax type / rate checks, 180-day payment tracker, PAN view, Tally journal export."""
from __future__ import annotations


def cmd_tax_check(db, args) -> None:
    from .compliance.tax_checks import KINDS
    from .services.clients import ClientService
    from .services.tax_checks import TaxCheckService

    client = ClientService(db).resolve(args.client)
    issues = TaxCheckService(db).check(client.id, args.period_from, args.period_to)
    for i in issues:
        d = i.doc
        print(f"  {'Purchase' if d.source == 'BOOKS' else 'Sales':<8} {KINDS[i.kind]:<24} {d.invoice_no:<16} "
              f"{d.invoice_date:%d-%m-%Y} {d.gstin:<15} {i.message}")
    print(f"{len(issues)} finding(s).")
    if args.excel:
        print(f"Saved {TaxCheckService.export_xlsx(issues, args.excel, client.name)}")


def cmd_payments(db, args) -> None:
    from .services.clients import ClientService
    from .services.rule37 import Rule37Service

    client = ClientService(db).resolve(args.client)
    sf, result = Rule37Service(db).import_payments(client.id, args.file, args.user)
    print(f"Imported as #{sf.id}: {len(result.rows)} payment(s), Rs. {result.total}.")
    for row, why in result.ignored:
        print(f"  not imported – row {row}: {why}")


def cmd_rule37(db, args) -> None:
    from datetime import date

    from .services.clients import ClientService
    from .services.rule37 import Rule37Service

    client = ClientService(db).resolve(args.client)
    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    svc = Rule37Service(db)
    bills = svc.track(client.id, as_of)
    for b in bills:
        if args.all or b.status in ("Reverse ITC", "Paid late – re-claim"):
            print(f"  {b.status:<22} {b.supplier[:28]:<28} {b.invoice_no:<16} {b.invoice_date:%d-%m-%Y} "
                  f"unpaid {b.unpaid_at_day180:>12} ITC to reverse {b.itc_to_reverse:>10} in {b.reversal_period}"
                  + (f", re-claim {b.itc_to_reclaim} in {b.reclaim_period}" if b.itc_to_reclaim else ""))
    total = sum((b.itc_to_reverse for b in bills if b.status != "Not yet due"), 0)
    print(f"ITC to reverse: {total}")
    if args.excel:
        print(f"Saved {svc.export_xlsx(bills, args.excel, client.name)}")


def cmd_pan_view(db, args) -> None:
    from .services.pan_view import PanViewService

    svc = PanViewService(db)
    if not args.pan:
        for pan, clients in svc.groups(include_single=True):
            print(f"  {pan}  {clients[0].name}: {', '.join(c.gstin for c in clients)}")
        return
    v = svc.view(args.pan, args.fy)
    for r in v.registrations:
        print(f"  {r.state:<16} {r.gstin} ITC books {r.itc_books:>12} 2B {r.itc_2b:>12} 3B {r.itc_3b:>12} "
              f"at risk {r.itc_at_risk:>10} overdue returns {r.returns_overdue}")
    print(f"Total ITC at risk {v.total('itc_at_risk')}; suppliers to follow up {len(v.suppliers)}")
    if args.excel:
        print(f"Saved {svc.export_xlsx(v, args.excel)}")


def add_commands(sub) -> None:
    t = sub.add_parser("tax-check", help="purchases / sales with the wrong tax type (IGST vs CGST+SGST), tax of "
                                         "another state, or tax not matching a GST rate")
    t.add_argument("--client", required=True)
    t.add_argument("--from", dest="period_from", required=True, help="first month (YYYY-MM)")
    t.add_argument("--to", dest="period_to", help="last month (YYYY-MM, default --from)")
    t.add_argument("--excel", help="also save the findings to this .xlsx file")
    t.set_defaults(func=cmd_tax_check)

    p = sub.add_parser("payments", help="import a payment register (payments to suppliers) for the 180-day rule")
    p.add_argument("--client", required=True)
    p.add_argument("--file", required=True, help="payment register (.xlsx, .csv or Tally .xml)")
    p.set_defaults(func=cmd_payments)

    r = sub.add_parser("rule37", help="bills not paid within 180 days: ITC to reverse and to re-claim (Rule 37)")
    r.add_argument("--client", required=True)
    r.add_argument("--as-of", help="date to judge on (YYYY-MM-DD, default today)")
    r.add_argument("--all", action="store_true", help="list every bill, not only those to reverse / re-claim")
    r.add_argument("--excel", help="also save the list to this .xlsx file")
    r.set_defaults(func=cmd_rule37)

    v = sub.add_parser("pan-view", help="all GST registrations of one PAN side by side for a financial year")
    v.add_argument("--pan", help="the PAN (omit to list the businesses and their GSTINs)")
    v.add_argument("--fy", default="2025-26", help="financial year, e.g. 2025-26")
    v.add_argument("--excel", help="also save the view to this .xlsx file")
    v.set_defaults(func=cmd_pan_view)


def permission_for(args) -> str | None:
    if args.command in ("tax-check", "rule37", "pan-view"):
        return "view"
    if args.command == "payments":
        return "import"
    return None
