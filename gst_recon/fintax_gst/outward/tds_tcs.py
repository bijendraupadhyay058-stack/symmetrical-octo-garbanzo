"""TDS (GSTR-7) and TCS (GSTR-8) credits received by the client, and their checks.

A government department or other notified person deducts TDS (section 51) at 2% of the
taxable value paid under a contract; an e-commerce operator collects TCS (section 52) on
the net value of supplies made through it, at 1% until 9 July 2024 and 0.5% from 10 July
2024. The credit appears on the portal under *TDS and TCS credit received*; the
client accepts or rejects it there, and an accepted credit goes to the electronic cash
ledger.

The download of that page (Excel/CSV, one sheet each for TDS and TCS) is read here.
The checks compare it with the sales register and the statutory rates; they never
change the figures.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from ..core.gstin import normalize_gstin, validate_gstin
from ..core.money import ZERO, AmountParseError, fmt_inr, parse_amount
from ..importers.column_mapping import normalize_header
from ..importers.parsing import parse_period, parse_text
from ..importers.readers import UnsupportedFileError, read_csv, read_excel

TDS_RATE = Decimal("0.02")
TCS_RATE_OLD, TCS_RATE_NEW = Decimal("0.01"), Decimal("0.005")
TCS_RATE_CHANGE = "2024-07"  # 0.5% from 10 July 2024; July 2024 returns may carry either rate
TOLERANCE = Decimal("1.00")

COLUMNS = {
    "gstin": ("gstin of deductor", "gstin of e commerce operator", "gstin of ecommerce operator", "gstin of eco",
              "deductor gstin", "eco gstin", "operator gstin", "gstin of collector", "gstin"),
    "name": ("deductor s name", "deductor name", "name of deductor", "trade name of e commerce operator",
             "e commerce operator name", "ecommerce operator name", "eco name", "trade legal name", "name"),
    "period": ("tax period of gstr 7", "tax period of gstr 8", "tax period", "return period", "period", "month"),
    "value": ("taxable value", "amount paid to deductee on which tax is deducted", "amount paid",
              "net amount liable for tcs", "net value of supplies", "net value", "value"),
    "gross": ("gross value of supplies", "gross value of supplies made", "gross value"),
    "returned": ("value of supplies returned", "supplies returned"),
    "igst": ("integrated tax", "igst", "igst amount", "integrated tax amount"),
    "cgst": ("central tax", "cgst", "cgst amount", "central tax amount"),
    "sgst": ("state ut tax", "state tax", "sgst", "sgst utgst", "state ut tax amount"),
    "action": ("action taken", "action", "status", "accept reject status"),
    "kind": ("type", "credit type", "tds tcs"),
}


@dataclass
class CreditLine:
    kind: str  # TDS or TCS
    period: str
    party_gstin: str
    party_name: str
    value: Decimal
    igst: Decimal
    cgst: Decimal
    sgst: Decimal
    action: str  # ACCEPTED, REJECTED, PENDING
    row: str = ""

    @property
    def tax(self) -> Decimal:
        return self.igst + self.cgst + self.sgst

    def key(self) -> tuple:
        return (self.kind, self.period, self.party_gstin, str(self.value.normalize()), str(self.igst.normalize()),
                str(self.cgst.normalize()), str(self.sgst.normalize()))


def _action(value) -> str:
    text = parse_text(value).lower()
    if text.startswith("accept") or text in ("a", "acc"):
        return "ACCEPTED"
    if text.startswith("reject") or text in ("r", "rej"):
        return "REJECTED"
    return "PENDING"


def _kind_of(sheet: str, names: list[str]) -> str | None:
    text = " ".join([normalize_header(sheet), *names])
    if re.search(r"\btcs\b|e ?commerce|operator|gstr 8", text):
        return "TCS"
    if re.search(r"\btds\b|deductor|gstr 7", text):
        return "TDS"
    return None


def read_credits(path: str | Path) -> tuple[list[CreditLine], list[str]]:
    """Credit lines and row problems (rows with problems are not imported)."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        tables = [read_csv(path, path.name)]
    elif suffix in (".xlsx", ".xlsm"):
        tables = read_excel(path)
    else:
        raise UnsupportedFileError("Use the Excel (.xlsx) or CSV download of 'TDS and TCS credit received'")
    lines: list[CreditLine] = []
    problems: list[str] = []
    found = False
    for t in tables:
        for i, (_n, values) in enumerate(t.rows[:30]):
            names = [normalize_header(v) for v in values]
            col = {f: next((names.index(o) for o in opts if o in names), None) for f, opts in COLUMNS.items()}
            if col["gstin"] is None or col["value"] is None or col["period"] is None:
                continue
            found = True
            sheet_kind = _kind_of(t.name, names)
            for n, vals in t.rows[i + 1:]:
                def cell(f):
                    c = col[f]
                    return vals[c] if c is not None and c < len(vals) else None

                where = f"{t.name}!{n}"
                gstin = normalize_gstin(parse_text(cell("gstin")))
                if not gstin or gstin.lower().startswith("total"):
                    continue
                ok, problem = validate_gstin(gstin)
                if not ok:
                    problems.append(f"{where}: {problem}: '{gstin}' – row not imported")
                    continue
                kind = parse_text(cell("kind")).upper()[:3] if cell("kind") else sheet_kind
                if kind not in ("TDS", "TCS"):
                    problems.append(f"{where}: cannot tell whether the credit is TDS or TCS – row not imported")
                    continue
                period = parse_period(cell("period"))
                if not period:
                    problems.append(f"{where}: tax period '{cell('period')}' not recognised – row not imported")
                    continue
                try:
                    amounts = {f: parse_amount(cell(f)) for f in ("value", "gross", "returned", "igst", "cgst", "sgst")}
                except AmountParseError as exc:
                    problems.append(f"{where}: {exc} – row not imported")
                    continue
                value = amounts["value"]
                if value is None and amounts["gross"] is not None:
                    value = amounts["gross"] - (amounts["returned"] or ZERO)
                lines.append(CreditLine(kind, period, gstin, parse_text(cell("name"))[:200], value or ZERO,
                                        amounts["igst"] or ZERO, amounts["cgst"] or ZERO, amounts["sgst"] or ZERO,
                                        _action(cell("action")), where))
            break
    if not found:
        raise UnsupportedFileError("No heading row with the deductor / e-commerce operator GSTIN, tax period and "
                                   "value found")
    return lines, problems


# --------------------------------------------------------------------------- checks
def expected_rate(c: CreditLine) -> tuple[Decimal, ...]:
    if c.kind == "TDS":
        return (TDS_RATE,)
    if c.period < TCS_RATE_CHANGE:
        return (TCS_RATE_OLD,)
    if c.period == TCS_RATE_CHANGE:
        return (TCS_RATE_OLD, TCS_RATE_NEW)
    return (TCS_RATE_NEW,)


@dataclass
class Finding:
    severity: str  # high | medium | info
    kind: str
    party: str
    period: str
    text: str
    amount: Decimal = ZERO


@dataclass
class PartyRow:
    kind: str
    gstin: str
    name: str
    sales_taxable: Decimal | None  # sales register to this GSTIN (TDS only)
    value: Decimal
    igst: Decimal
    cgst: Decimal
    sgst: Decimal
    accepted: Decimal
    pending: Decimal
    rejected: Decimal

    @property
    def tax(self) -> Decimal:
        return self.igst + self.cgst + self.sgst

    @property
    def difference(self) -> Decimal | None:
        """GSTR-7 value − sales register (TDS)."""
        return None if self.sales_taxable is None else self.value - self.sales_taxable


@dataclass
class TdsTcsStatement:
    months: list[str]
    lines: list[CreditLine]
    parties: list[PartyRow] = field(default_factory=list)
    by_period: list[tuple] = field(default_factory=list)  # (period, kind, igst, cgst, sgst, accepted, pending)
    findings: list[Finding] = field(default_factory=list)

    def total(self, kind: str, action: str | None = None) -> Decimal:
        return sum((c.tax for c in self.lines if c.kind == kind and (action is None or c.action == action)), ZERO)


def _pct(tax: Decimal, value: Decimal) -> str:
    return f"{(tax / value * 100).quantize(Decimal('0.01'))}%" if value else "–"


def build_statement(lines: list[CreditLine], months: list[str], client_gstin: str,
                    sales_by_party: dict[str, Decimal]) -> TdsTcsStatement:
    lines = sorted((c for c in lines if c.period in months), key=lambda c: (c.kind, c.period, c.party_gstin))
    st = TdsTcsStatement(months, lines)
    own_state = client_gstin[:2]
    for c in lines:
        label = "GSTR-7" if c.kind == "TDS" else "GSTR-8"
        rates = expected_rate(c)
        if c.value and not any(abs(c.tax - (c.value * r).quantize(Decimal("0.01"))) <= TOLERANCE for r in rates):
            want = " or ".join(f"{(r * 100).normalize():f}%" for r in rates)
            st.findings.append(Finding("medium", c.kind, c.party_gstin, c.period,
                                       f"{c.kind} of ₹{fmt_inr(c.tax)} on ₹{fmt_inr(c.value)} is {_pct(c.tax, c.value)}; expected "
                                       f"{want} – ask {c.party_name or c.party_gstin} to amend {label}", c.tax))
        if c.kind == "TDS" and c.tax:
            intra = c.party_gstin[:2] == own_state
            if intra and c.igst or not intra and (c.cgst or c.sgst):
                st.findings.append(Finding(
                    "medium", c.kind, c.party_gstin, c.period,
                    f"TDS deducted as {'IGST' if c.igst else 'CGST/SGST'} by a deductor "
                    f"{'in the same state' if intra else 'in another state'} – usually "
                    f"{'CGST + SGST' if intra else 'IGST'}; check the place of supply", c.tax))
        if c.action == "PENDING":
            st.findings.append(Finding("medium", c.kind, c.party_gstin, c.period,
                                       f"₹{fmt_inr(c.tax)} {c.kind} credit not yet accepted on the portal – accept it so it "
                                       "reaches the electronic cash ledger (or reject it if it is not yours)", c.tax))
        elif c.action == "REJECTED":
            st.findings.append(Finding("info", c.kind, c.party_gstin, c.period,
                                       f"₹{fmt_inr(c.tax)} {c.kind} credit rejected – {c.party_name or c.party_gstin} has to "
                                       f"correct it in a later {label}", c.tax))
    groups: dict[tuple, list[CreditLine]] = defaultdict(list)
    for c in lines:
        groups[(c.kind, c.party_gstin)].append(c)
    for (kind, gstin), cs in sorted(groups.items()):
        def tot(f, action=None, cs=cs):
            return sum((getattr(c, f) for c in cs if action is None or c.action == action), ZERO)

        sales = sales_by_party.get(gstin, ZERO) if kind == "TDS" else None
        row = PartyRow(kind, gstin, next((c.party_name for c in cs if c.party_name), ""), sales, tot("value"),
                       tot("igst"), tot("cgst"), tot("sgst"), tot("tax", "ACCEPTED"), tot("tax", "PENDING"),
                       tot("tax", "REJECTED"))
        st.parties.append(row)
        if kind != "TDS":
            continue
        who = row.name or gstin
        if not sales:
            st.findings.append(Finding("high", kind, gstin, "", f"TDS credit of ₹{fmt_inr(row.tax)} from {who}, but no sales to "
                                       "this GSTIN in the sales register for the period – check the deductor's "
                                       "GSTR-7 or record the sale", row.tax))
        elif row.difference > TOLERANCE:
            st.findings.append(Finding("medium", kind, gstin, "", f"Value in GSTR-7 exceeds sales to {who} by "
                                       f"₹{fmt_inr(row.difference)} – payment of an earlier period's invoices, or an error by "
                                       "the deductor", row.difference))
        elif row.difference < -TOLERANCE:
            st.findings.append(Finding("info", kind, gstin, "", f"Sales to {who} of ₹{fmt_inr(-row.difference)} not yet covered "
                                       "by GSTR-7 – payment still due, contract value up to ₹2.5 lakh (no TDS), or "
                                       "GSTR-7 not yet filed", -row.difference))
    per: dict[tuple, list[Decimal]] = defaultdict(lambda: [ZERO] * 5)
    for c in lines:
        p = per[(c.period, c.kind)]
        p[0] += c.igst
        p[1] += c.cgst
        p[2] += c.sgst
        p[3 if c.action == "ACCEPTED" else 4] += c.tax if c.action != "REJECTED" else ZERO
    st.by_period = [(p, k, *v) for (p, k), v in sorted(per.items())]
    order = {"high": 0, "medium": 1, "info": 2}
    st.findings.sort(key=lambda f: (order[f.severity], f.kind, f.period, f.party))
    return st
