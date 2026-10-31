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


def add_commands(sub) -> None:
    t = sub.add_parser("tax-check", help="purchases / sales with the wrong tax type (IGST vs CGST+SGST), tax of "
                                         "another state, or tax not matching a GST rate")
    t.add_argument("--client", required=True)
    t.add_argument("--from", dest="period_from", required=True, help="first month (YYYY-MM)")
    t.add_argument("--to", dest="period_to", help="last month (YYYY-MM, default --from)")
    t.add_argument("--excel", help="also save the findings to this .xlsx file")
    t.set_defaults(func=cmd_tax_check)


def permission_for(args) -> str | None:
    if args.command == "tax-check":
        return "view"
    return None
