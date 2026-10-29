"""CLI commands for the ITC module, IMS, GSTR-3B, annual reporting, users and security."""
from __future__ import annotations

import getpass
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

from .core.money import fmt_inr
from .importers.gstr3b import TABLE4, Gstr3bValues
from .itc.review import BUCKET_LABELS
from .services.auth import ROLES, AuthService
from .services.clients import ClientService
from .services.common import ServiceError
from .services.gstr3b import Gstr3bService
from .services.itc import ItcService
from .services.reconciliation import months_between
from .services.security import SecurityService


def _password(prompt: str, env: str) -> str:
    return os.environ.get(env) or getpass.getpass(prompt)


def _as_of(args) -> date:
    return date.fromisoformat(args.as_of) if getattr(args, "as_of", None) else date.today()


# ------------------------------------------------------------------ users
def cmd_user(db, args) -> None:
    auth = AuthService(db)
    if args.action == "list":
        for u in auth.users():
            last = f"{u.last_login:%d-%m-%Y %H:%M}" if u.last_login else "never"
            print(f"{u.username:<20} {ROLES[u.role]:<22} {'active' if u.active else 'disabled':<9} last login {last}")
        return
    if args.action == "add":
        pw = _password(f"Password for {args.username}: ", "FINTAX_NEW_PASSWORD")
        auth.create_user(args.username, pw, args.role, args.full_name or "", by=args.session)
        print(f"User '{args.username}' created ({ROLES[args.role]}).")
    elif args.action == "passwd":
        old = _password("Current password: ", "FINTAX_PASSWORD")
        new = _password("New password: ", "FINTAX_NEW_PASSWORD")
        auth.change_password(args.username or args.session.username, old, new)
        print("Password changed.")
    elif args.action == "reset":
        auth.reset_password(args.username, _password("New password: ", "FINTAX_NEW_PASSWORD"), args.session)
        print(f"Password of '{args.username}' reset; the user must change it at next login.")
    elif args.action == "role":
        auth.set_role(args.username, args.role, args.session,
                      active=None if args.active is None else args.active == "yes")
        print(f"'{args.username}' is now {ROLES[args.role]}.")


# ---------------------------------------------------------------- GSTR-3B
def cmd_gstr3b(db, args) -> None:
    client = ClientService(db).resolve(args.client)
    svc = Gstr3bService(db)
    if args.action == "import":
        sf, p = svc.import_file(client.id, args.file, args.period, args.user)
        print(f"GSTR-3B imported as #{sf.id} ({p.layout}) for {', '.join(p.periods)}")
        for w in p.warnings:
            print(f"  ! {w}")
        return
    for period, table in sorted(svc.values(client.id).items()):
        print(f"\nGSTR-3B {period}")
        for code in TABLE4:
            if code in table:
                v = table[code]
                print(f"  {TABLE4[code]:<78} {fmt_inr(v.total):>14}")


# -------------------------------------------------------------------- IMS
def cmd_ims(db, args) -> None:
    client = ClientService(db).resolve(args.client)
    rows, notes = ItcService(db).ims_compare(client.id, [args.period])
    for n in notes:
        print(f"! {n}")
    for r in rows:
        if args.all or r.worst in ("high", "medium"):
            print(f"{r.ims.supplier_gstin} {r.ims.invoice_no:<18} {r.action_label:<28} "
                  f"books {'Y' if r.books else 'N'} 2B {'Y' if r.gstr2b else 'N'}")
            for sev, text in r.observations:
                print(f"      [{sev.upper():6}] {text}")
    print(f"{len(rows)} IMS document(s); {sum(1 for r in rows if r.worst == 'high')} need attention")


# -------------------------------------------------------------------- ITC
def cmd_itc(db, args) -> None:
    itc = ItcService(db)
    if args.action == "review":
        reviews, buckets = itc.review_run(args.run, _as_of(args))
        for rv in reviews:
            for h in rv.hits:
                if args.all or h.open:
                    state = h.decision or "OPEN"
                    print(f"{rv.line_no:>5} {rv.record.invoice_no:<18} {h.severity.upper():<6} {h.code:<22} "
                          f"{state:<9} {h.message}")
        print()
        for k, label in BUCKET_LABELS:
            print(f"  {label:<58} {fmt_inr(buckets[k]):>14}")
        return
    if args.action == "decide":
        client = ClientService(db).resolve(args.client)
        itc.set_review(client.id, args.invoice, args.rule, args.decision.upper(), args.remarks or "", args.user)
        print(f"Flag {args.rule} on document {args.invoice}: {args.decision.upper()}")
        return
    if args.action == "claim":
        if args.invoices:
            client = ClientService(db).resolve(args.client)
            res = itc.claim(client.id, [int(x) for x in args.invoices.split(",")], args.period, args.user)
        else:
            if args.run is None:
                raise ServiceError("Give --run (claim all eligible documents) or --client with --invoices")
            res = itc.claim_eligible_from_run(args.run, args.period, args.user, _as_of(args))
        print(f"Claimed {len(res.claimed)} document(s) in {args.period}; {len(res.skipped)} skipped")
        for inv, why in res.skipped[:30]:
            print(f"   skipped #{inv}: {why}")
        return
    if args.action in ("reverse", "reclaim"):
        client = ClientService(db).resolve(args.client)
        amounts = None
        if args.amounts:
            parts = dict(p.split("=") for p in args.amounts.split(","))
            amounts = Gstr3bValues(*(Decimal(parts.get(k, "0")) for k in ("igst", "cgst", "sgst", "cess")))
        if args.action == "reverse":
            itc.reverse(client.id, args.invoice, args.period, args.user, args.reason or "", args.rule_ref or "",
                        amounts)
        else:
            itc.reclaim(client.id, args.invoice, args.period, args.user, args.reason or "", amounts)
        print(f"{args.action.title()} recorded for document {args.invoice} in {args.period}.")
        return
    if args.action == "table4":
        client = ClientService(db).resolve(args.client)
        for w in itc.table4(client.id, months_between(args.period_from, args.period_to or args.period_from),
                            _as_of(args)):
            print(f"\nGSTR-3B Table 4 working – {w.period}  (books basis: {w.books_basis})")
            print(f"  {'Table':<6} {'2B auto':>14} {'Books/review':>14} {'3B filed':>14} {'3B − 2B':>14}")
            for r in w.rows:
                filed = fmt_inr(r.filed.total) if r.filed else "-"
                diff = fmt_inr(r.diff_filed_2b) if r.diff_filed_2b is not None else "-"
                print(f"  {r.code:<6} {fmt_inr(r.auto_2b.total):>14} {fmt_inr(r.books.total):>14} {filed:>14} {diff:>14}")
            for f in w.findings:
                print(f"  [{f.kind:<10} {f.severity:<6}] {f.text}  ₹{fmt_inr(f.amount)}")
        return
    if args.action == "rules":
        client = ClientService(db).resolve(args.client) if args.client else None
        cid = client.id if client else None
        rules = {r.code: r for r in itc.rules(cid)}
        if args.enable or args.disable or args.add_gstin:
            code = args.enable or args.disable or args.add_gstin[0]
            if code not in rules:
                raise ServiceError(f"Unknown rule {code}")
            r = rules[code]
            if args.enable:
                r.enabled = True
            if args.disable:
                r.enabled = False
            if args.add_gstin:
                r.gstins = sorted(set(r.gstins) | {args.add_gstin[1].upper()})
            itc.save_rule(r, cid, args.user)
            print(f"Rule {code} saved for {'client ' + client.gstin if client else 'all clients'}.")
            return
        for r in rules.values():
            to = f"{r.effective_to:%d-%m-%Y}" if r.effective_to else "-"
            print(f"{r.code:<22} {'on ' if r.enabled else 'off'} {r.severity:<6} {r.effective_from:%d-%m-%Y} to "
                  f"{to:<10} {r.title}  [{r.reference}]")


def cmd_annual(db, args) -> None:
    from .reports.annual_report import export_annual

    client = ClientService(db).resolve(args.client)
    t = ItcService(db).annual(client.id, args.fy, args.cutoff,
                              Decimal(args.portal_8a) if args.portal_8a else None)
    print(f"GSTR-9 Table 8 – FY {args.fy} (GSTR-2B up to {t.cutoff})")
    for label, v in (("8A ITC as per GSTR-2B", t.a), ("8B ITC availed in GSTR-3B 4(A)(5)", t.b),
                     ("8C availed in next year", t.c), ("8D = 8A − (8B + 8C)", t.d)):
        print(f"  {label:<40} {fmt_inr(v.total):>16}")
    if t.b_periods_missing:
        print(f"  ! GSTR-3B missing for {len(t.b_periods_missing)} period(s): {', '.join(t.b_periods_missing)}")
    if args.out:
        print(f"Workbook: {export_annual(db, client.id, args.fy, args.out, args.cutoff, args.portal_8a, args.user)}")


# --------------------------------------------------------------- security
def cmd_secure_backup(db, args) -> None:
    sec = SecurityService(db)
    if args.auto:
        p = sec.auto_backup(force=True)
        print(f"Automatic backup written to {p}; retention applied")
        return
    pw = _password("Backup password: ", "FINTAX_BACKUP_PASSWORD")
    print(f"Encrypted backup written to {sec.encrypted_backup(args.to, pw, args.session)}")


def cmd_secure_restore(db, args) -> None:
    pw = _password("Backup password: ", "FINTAX_BACKUP_PASSWORD")
    safety = SecurityService(db).restore_encrypted(args.file, pw, args.session)
    print(f"Restored. Previous database saved as {safety}")


def cmd_purge(db, args) -> None:
    client = ClientService(db).resolve(args.client)
    counts = SecurityService(db).purge_client(client.id, args.confirm, args.session)
    print(f"Client {client.gstin} and all its data permanently deleted: "
          + ", ".join(f"{k} {v}" for k, v in counts.items() if v))


def cmd_audit_export(db, args) -> None:
    client = ClientService(db).resolve(args.client) if args.client else None
    out = SecurityService(db).export_audit(Path(args.out), client.id if client else None, args.session)
    print(f"Audit log exported to {out}")


def add_commands(sub) -> None:
    u = sub.add_parser("user", help="users and roles (admin)")
    u.add_argument("action", choices=["add", "list", "passwd", "reset", "role"])
    u.add_argument("--username")
    u.add_argument("--role", choices=list(ROLES))
    u.add_argument("--full-name")
    u.add_argument("--active", choices=["yes", "no"])
    u.set_defaults(func=cmd_user)

    g = sub.add_parser("gstr3b", help="import or show GSTR-3B Table 4")
    g.add_argument("action", choices=["import", "show"])
    g.add_argument("--client", required=True)
    g.add_argument("--file")
    g.add_argument("--period")
    g.set_defaults(func=cmd_gstr3b)

    i = sub.add_parser("ims", help="compare IMS actions with books and GSTR-2B")
    i.add_argument("--client", required=True)
    i.add_argument("--period", required=True)
    i.add_argument("--all", action="store_true", help="also list consistent documents")
    i.set_defaults(func=cmd_ims, perm="view")

    t = sub.add_parser("itc", help="ITC review, claims, reversals, Table 4 and rules")
    t.add_argument("action", choices=["review", "decide", "claim", "reverse", "reclaim", "table4", "rules"])
    t.add_argument("--run", type=int)
    t.add_argument("--client")
    t.add_argument("--invoice", type=int, help="document id (see the workbook / review output)")
    t.add_argument("--invoices", help="comma-separated document ids to claim")
    t.add_argument("--rule")
    t.add_argument("--decision", choices=["confirmed", "dismissed", "CONFIRMED", "DISMISSED"])
    t.add_argument("--remarks")
    t.add_argument("--period", help="GSTR-3B period YYYY-MM of the claim / reversal")
    t.add_argument("--from", dest="period_from")
    t.add_argument("--to", dest="period_to")
    t.add_argument("--reason")
    t.add_argument("--rule-ref")
    t.add_argument("--amounts", help="e.g. igst=1000,cgst=0 (default: the full eligible amount)")
    t.add_argument("--as-of", help="review date YYYY-MM-DD (default today)")
    t.add_argument("--all", action="store_true")
    t.add_argument("--enable")
    t.add_argument("--disable")
    t.add_argument("--add-gstin", nargs=2, metavar=("RULE", "GSTIN"))
    t.set_defaults(func=cmd_itc)

    a = sub.add_parser("annual", help="GSTR-9 Table 8 (8A–8D) working")
    a.add_argument("--client", required=True)
    a.add_argument("--fy", required=True)
    a.add_argument("--cutoff", help="last GSTR-2B period included in 8A (default November of next year)")
    a.add_argument("--portal-8a", help="Table 8A total shown on the portal, to compare")
    a.add_argument("--out", help="directory for the annual workbook")
    a.set_defaults(func=cmd_annual, perm="export")

    sb = sub.add_parser("secure-backup", help="encrypted backup (or --auto for the rotating automatic backup)")
    sb.add_argument("--to")
    sb.add_argument("--auto", action="store_true")
    sb.set_defaults(func=cmd_secure_backup, perm="settings")
    sr = sub.add_parser("secure-restore", help="restore from an encrypted backup (admin)")
    sr.add_argument("file")
    sr.set_defaults(func=cmd_secure_restore, perm="restore")
    p = sub.add_parser("purge-client", help="permanently delete a client and all its data (admin)")
    p.add_argument("--client", required=True)
    p.add_argument("--confirm", required=True, help="the client's GSTIN, typed again")
    p.set_defaults(func=cmd_purge, perm="delete_data")
    ae = sub.add_parser("audit-export", help="export the audit log to CSV")
    ae.add_argument("--out", required=True)
    ae.add_argument("--client")
    ae.set_defaults(func=cmd_audit_export, perm="export")


def permission_for(args) -> str | None:
    """Permission needed by a parsed command (None = no login needed)."""
    if getattr(args, "no_db", False):
        return None
    if getattr(args, "perm", None):
        return args.perm
    cmd = args.command
    if cmd == "client":
        return "manage_clients" if args.action == "add" else "view"
    if cmd == "imports":
        return "delete_data" if args.remove else "view"
    if cmd == "user":
        return None if args.action == "passwd" else ("view" if args.action == "list" else "manage_users")
    if cmd == "gstr3b":
        return "import" if args.action == "import" else "view"
    if cmd == "itc":
        return {"review": "view", "table4": "view", "decide": "review", "claim": "claim", "reverse": "claim",
                "reclaim": "claim"}.get(args.action) or ("manage_rules" if (args.enable or args.disable
                                                                          or args.add_gstin) else "view")
    return {"init": "view", "import": "import", "reconcile": "reconcile", "runs": "view", "show": "view",
            "update-line": "review", "match": "review", "vendor": "review", "attach": "review",
            "open-items": "view", "export": "export", "backup": "settings", "restore": "restore"}.get(cmd, "view")
