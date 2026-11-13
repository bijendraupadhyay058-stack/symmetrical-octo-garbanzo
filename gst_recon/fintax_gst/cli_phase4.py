"""Phase 4 commands: outward liability, compliance dashboard, supplier letters, working papers,
encrypted synchronisation and the web interface."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from .cli_phase3 import _password
from .compliance.summary import RAG_LABEL
from .core.money import fmt_inr
from .services.clients import ClientService
from .services.common import ServiceError
from .services.reconciliation import months_between


def cmd_liability(db, args) -> None:
    from .services.outward import OutwardService

    client = ClientService(db).resolve(args.client)
    for w in OutwardService(db).liability(client.id, months_between(args.period_from, args.period_to or
                                                                    args.period_from)):
        print(f"\n{client.name} ({client.gstin}) – GSTR-1 vs GSTR-3B Table 3.1, {w.period}")
        print(f"  {'Row':<46} {'GSTR-1 tax':>14} {'Sales tax':>14} {'3B tax':>14} {'3B − GSTR-1':>14}")
        for r in w.rows:
            print(f"  {r.label[:46]:<46} {fmt_inr(r.gstr1.total):>14} {fmt_inr(r.sales.total):>14} "
                  f"{fmt_inr(r.filed.total) if r.filed else '-':>14} "
                  f"{fmt_inr(r.diff_filed_gstr1) if r.diff_filed_gstr1 is not None else '-':>14}")
        for f in w.findings:
            print(f"  [{f.severity.upper():<6}] {f.text}")


def cmd_compliance(db, args) -> None:
    from .services.compliance import ComplianceService

    svc = ComplianceService(db)
    if args.client:
        client = ClientService(db).resolve(args.client)
        summaries = [svc.client_summary(client.id, args.fy)]
    else:
        summaries = svc.annual_dashboard(args.fy)
    for c in summaries:
        print(f"\n{c.name} ({c.gstin}) FY {c.fy}: {RAG_LABEL[c.rag]} – {c.months_with_data} month(s) with data, "
              f"{c.pending} pending, ITC at risk ₹{fmt_inr(c.total('itc_at_risk'))}, possible short payment "
              f"₹{fmt_inr(c.total('short_payment'))}")
        for m in c.months:
            if m.has_data:
                print(f"  {m.period} {RAG_LABEL[m.rag]:<16} " + "; ".join(t for _r, t in m.issues))
    if args.out:
        from .reports.compliance_report import export_client_pdf, export_compliance_excel

        out = Path(args.out)
        print(f"Workbook: {export_compliance_excel(summaries, args.fy, out / f'GST_Dashboard_{args.fy}.xlsx')}")
        if args.pdf:
            for c in summaries:
                print(f"PDF: {export_client_pdf(c, out / f'Compliance_{c.gstin}_{c.fy}.pdf')}")


def cmd_letters(db, args) -> None:
    from .services.letters import LetterService

    svc = LetterService(db)
    gstins = set(args.gstin) if args.gstin else None
    if args.preview or not args.out:
        for lt in svc.preview(args.run, gstins):
            print(f"{lt.gstin} {lt.name[:36]:<36} {len(lt.items):>3} item(s)  ₹{fmt_inr(lt.amount):>12}")
            for it in lt.items:
                print(f"    {it.invoice_no:<20} {it.issue}")
        if not args.out:
            print("\nAdd --out DIR to write the letters.")
        return
    formats = tuple(args.formats.split(","))
    done = svc.generate(args.run, args.out, gstins, formats, args.reply_days, args.signatory or "",
                        update_register=not args.no_register, user=args.user)
    for lt, paths in done:
        print(f"{lt.gstin} {lt.name[:36]:<36} {len(lt.items)} item(s): " + ", ".join(p.name for p in paths))
    print(f"{len(done)} letter(s) written. E-mail drafts (.eml) are not sent – open and send them from your mailbox.")


def cmd_papers(db, args) -> None:
    from .services.papers import WorkingPaperService

    svc = WorkingPaperService(db)
    if args.action == "prepare":
        wp = svc.prepare(args.run, args.out, args.session, include_sources=args.include_sources)
        print(f"Working papers #{wp.id}: {wp.package_path}\nSHA-256 {wp.sha256}")
    elif args.action == "review":
        wp = svc.review(args.id, args.session, args.notes or "")
        print(f"Working papers #{wp.id} reviewed by {wp.reviewed_by}")
    elif args.action == "verify":
        ok, problem = svc.verify(args.id)
        print("Package intact – matches the recorded SHA-256 and its manifest" if ok else f"FAILED: {problem}")
        if not ok:
            raise SystemExit(1)
    else:
        client = ClientService(db).resolve(args.client)
        for wp in svc.list(client.id):
            rev = f"reviewed by {wp.reviewed_by} {wp.reviewed_at:%d-%m-%Y}" if wp.reviewed_by else "not reviewed"
            print(f"#{wp.id:<4} run {wp.run_id:<5} {wp.period_from}..{wp.period_to} prepared by {wp.prepared_by} "
                  f"{wp.prepared_at:%d-%m-%Y} · {rev}\n      {wp.package_path}")


def cmd_sync(db, args) -> None:
    from .services.sync import SyncService

    svc = SyncService(db)
    if args.action in ("authorise", "revoke", "list", "export"):
        if not args.client and args.action != "revoke":
            raise ServiceError("--client is required")
    if args.action == "authorise":
        client = ClientService(db).resolve(args.client)
        a = svc.authorise(client.id, args.granted_by or "", date.fromisoformat(args.valid_until),
                          args.evidence or "", args.session)
        print(f"Authorisation #{a.id} recorded: {a.granted_by}, valid {a.granted_on:%d-%m-%Y} to "
              f"{a.expires_on:%d-%m-%Y}")
    elif args.action == "revoke":
        svc.revoke(args.id, args.session)
        print(f"Authorisation #{args.id} revoked")
    elif args.action == "list":
        client = ClientService(db).resolve(args.client)
        for a in svc.authorisations(client.id):
            state = "revoked" if a.revoked_at else ("active" if a.granted_on <= date.today() <= a.expires_on
                                                    else "expired")
            print(f"#{a.id:<4} {state:<8} {a.granted_by:<30} {a.granted_on:%d-%m-%Y}–{a.expires_on:%d-%m-%Y} "
                  f"ref {a.evidence}")
    elif args.action == "export":
        client = ClientService(db).resolve(args.client)
        pw = _password("Sync password: ", "FINTAX_SYNC_PASSWORD")
        print(f"Encrypted sync package: {svc.export_package(client.id, args.folder, pw, args.session)}")
    elif args.action == "inspect":
        info = svc.inspect(args.file, _password("Sync password: ", "FINTAX_SYNC_PASSWORD"))
        print(f"{info['client']['name']} ({info['client']['gstin']}) package {info['seq']} from "
              f"{info['origin'][:8]}, created {info['created_at']} by {info['created_by']}")
        print(f"Authorised by {info['authorisation']['granted_by']} until {info['authorisation']['expires_on']}")
        print("Rows: " + ", ".join(f"{k} {v}" for k, v in info["rows"].items() if v))
        print(f"Local changes since last sync: {info['local_changes']}")
    elif args.action == "import":
        res = svc.import_package(args.file, _password("Sync password: ", "FINTAX_SYNC_PASSWORD"), args.session,
                                 replace_local=args.replace_local)
        print(f"Imported client #{res['client_id']}: " + ", ".join(f"{k} {v}" for k, v in res["rows"].items() if v))
        if res["safety_backup"]:
            print(f"Local data replaced; previous database saved as {res['safety_backup']}")


def cmd_serve(db, args) -> None:
    from .web.app import serve

    scheme = "https" if args.certfile else "http"
    print(f"FIN TAX PRO web interface on {scheme}://{args.host}:{args.port}/ – Ctrl+C to stop")
    serve(db, args.host, args.port, args.certfile, args.keyfile, args.allow_http_lan)


def add_commands(sub) -> None:
    lb = sub.add_parser("liability", help="GSTR-1 vs sales register vs GSTR-3B Table 3.1")
    lb.add_argument("--client", required=True)
    lb.add_argument("--from", dest="period_from", required=True)
    lb.add_argument("--to", dest="period_to")
    lb.set_defaults(func=cmd_liability, perm="view")

    c = sub.add_parser("compliance", help="client compliance summary / annual dashboard of all clients")
    c.add_argument("--fy", required=True)
    c.add_argument("--client", help="one client (default: all active clients)")
    c.add_argument("--out", help="folder for the Excel dashboard")
    c.add_argument("--pdf", action="store_true", help="also write a compliance PDF per client")
    c.set_defaults(func=cmd_compliance, perm="view")

    lt = sub.add_parser("letters", help="supplier discrepancy letters for a purchase reconciliation run")
    lt.add_argument("--run", type=int, required=True)
    lt.add_argument("--out", help="folder (omit to preview)")
    lt.add_argument("--gstin", action="append", help="only this supplier (repeatable)")
    lt.add_argument("--formats", default="docx,pdf,eml", help="any of docx,pdf,eml")
    lt.add_argument("--reply-days", type=int, default=15)
    lt.add_argument("--signatory", help="name printed above 'Authorised Signatory'")
    lt.add_argument("--no-register", action="store_true", help="do not update the vendor follow-up register")
    lt.add_argument("--preview", action="store_true")
    lt.set_defaults(func=cmd_letters, perm="letters")

    wp = sub.add_parser("papers", help="audit working papers: prepare | review | verify | list")
    wp.add_argument("action", choices=["prepare", "review", "verify", "list"])
    wp.add_argument("--run", type=int)
    wp.add_argument("--out")
    wp.add_argument("--id", type=int)
    wp.add_argument("--client")
    wp.add_argument("--notes")
    wp.add_argument("--include-sources", action="store_true", help="include the imported source files")
    wp.set_defaults(func=cmd_papers)

    sy = sub.add_parser("sync", help="client-authorised encrypted synchronisation packages")
    sy.add_argument("action", choices=["authorise", "revoke", "list", "export", "inspect", "import"])
    sy.add_argument("--client")
    sy.add_argument("--granted-by", help="client's authorised signatory")
    sy.add_argument("--valid-until", help="YYYY-MM-DD")
    sy.add_argument("--evidence", help="reference of the signed consent")
    sy.add_argument("--id", type=int, help="authorisation id (revoke)")
    sy.add_argument("--folder", help="export: folder (e.g. inside your cloud drive)")
    sy.add_argument("--file", help="inspect/import: package file")
    sy.add_argument("--replace-local", action="store_true", help="import: replace local changes (backup first)")
    sy.set_defaults(func=cmd_sync)

    sv = sub.add_parser("serve", help="read-only web interface for phones and browsers")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8765)
    sv.add_argument("--certfile")
    sv.add_argument("--keyfile")
    sv.add_argument("--allow-http-lan", action="store_true", help="allow plain HTTP to other devices (trusted LAN)")
    sv.set_defaults(func=cmd_serve, perm="view")


def permission_for(args) -> str | None:
    if args.command == "papers":
        return {"prepare": "prepare_papers", "review": "review_papers"}.get(args.action, "view")
    if args.command == "sync":
        return "view" if args.action in ("list", "inspect") else "sync"
    return None
