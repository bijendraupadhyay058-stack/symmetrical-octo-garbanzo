"""Trial balance from TallyPrime: every ledger with its group and balance, read exactly as exported.

Accepted:

* **Excel / CSV** – a ledger column (*Particulars / Ledger / Name*), optionally a group column (*Group / Under /
  Parent*), and either *Debit* and *Credit* columns or one *Closing balance* column with Dr / Cr. Opening balance
  and the year's debit / credit transactions are read when present (the transactions give the additions of fixed
  assets). A Tally "detailed" trial balance lists groups and their ledgers in one column: rows naming a Tally
  primary group (Purchase Accounts, Indirect Expenses …) open that group, and a row whose amount is the sum of the
  rows after it is taken as a sub-group heading – neither is counted as a ledger.
* **Tally XML** – the Trial Balance report exported as XML (DSPACCNAME / DSPACCINFO), or ledger masters with
  PARENT and CLOSINGBALANCE.
* **Directly from TallyPrime** (XML interface): ledgers with their parent group, opening and closing balance, and
  the group tree, so each ledger's primary group is exact.

Debit balances are positive and credit balances negative. Totals are checked: debits must equal credits.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from ..core.money import ZERO, AmountParseError, parse_amount
from .column_mapping import normalize_header
from .readers import UnsupportedFileError, read_csv, read_excel

#: Tally's reserved primary groups and the nature of the ledgers under them
PRIMARY_GROUPS = {
    "purchase accounts": "purchase", "direct expenses": "expense", "indirect expenses": "expense",
    "fixed assets": "asset", "sales accounts": "income", "direct incomes": "income", "indirect incomes": "income",
    "duties & taxes": "duties", "duties and taxes": "duties", "capital account": "other", "current assets": "other",
    "current liabilities": "other", "loans (liability)": "other", "loans & advances (asset)": "other",
    "investments": "other", "misc. expenses (asset)": "other", "suspense a/c": "other", "branch / divisions": "other",
    "bank accounts": "other", "bank od a/c": "other", "cash-in-hand": "other", "deposits (asset)": "other",
    "provisions": "other", "reserves & surplus": "other", "secured loans": "other", "unsecured loans": "other",
    "stock-in-hand": "other", "sundry creditors": "other", "sundry debtors": "other",
}
NATURES = ("purchase", "expense", "asset", "income", "duties", "other")
#: natures whose ledgers are classified (purchases, expenses, fixed assets)
IN_SCOPE = ("purchase", "expense", "asset")
_TOTAL = re.compile(r"^(grand\s+)?total\b|^difference in opening", re.I)

_COLS = {
    "name": ["particulars", "ledger", "ledger name", "name", "account", "account name", "ledger account"],
    "group": ["group", "under", "parent", "parent group", "group name", "primary group"],
    "debit": ["debit", "closing debit", "dr", "closing balance debit", "debit amount"],
    "credit": ["credit", "closing credit", "cr", "closing balance credit", "credit amount"],
    "closing": ["closing balance", "balance", "amount", "closing"],
    "opening": ["opening balance", "opening"],
    "tr_debit": ["transactions debit", "debit transactions", "period debit", "debit during the year"],
    "tr_credit": ["transactions credit", "credit transactions", "period credit", "credit during the year"],
}


def nature_of(group: str, primary: str = "") -> str:
    for g in (primary, group):
        n = PRIMARY_GROUPS.get((g or "").strip().lower())
        if n:
            return n
    text = f"{group} {primary}".lower()
    if re.search(r"purchase", text):
        return "purchase"
    if re.search(r"expense|expenditure|cost", text):
        return "expense"
    if re.search(r"fixed asset|plant|machinery|furniture|vehicle|computer|equipment|building", text):
        return "asset"
    if re.search(r"sales|income|revenue", text):
        return "income"
    if re.search(r"duties|gst|tax", text):
        return "duties"
    return "other"


@dataclass
class TbRow:
    name: str
    parent: str = ""
    primary: str = ""
    closing: Decimal = ZERO  # debit positive
    opening: Decimal | None = None
    debit: Decimal | None = None  # transactions of the year
    credit: Decimal | None = None
    row: str = ""

    @property
    def nature(self) -> str:
        return nature_of(self.parent, self.primary)


@dataclass
class TrialBalance:
    rows: list[TbRow] = field(default_factory=list)
    layout: str = ""
    warnings: list[str] = field(default_factory=list)
    company: str = ""

    @property
    def total_debit(self) -> Decimal:
        return sum((r.closing for r in self.rows if r.closing > 0), ZERO)

    @property
    def total_credit(self) -> Decimal:
        return -sum((r.closing for r in self.rows if r.closing < 0), ZERO)

    @property
    def difference(self) -> Decimal:
        return self.total_debit - self.total_credit


def _amt(v, where: str) -> Decimal | None:
    if v in (None, ""):
        return None
    text = str(v).strip()
    sign = 1
    m = re.search(r"\b(dr|cr)\.?\s*$", text, re.I)
    if m:
        sign = -1 if m.group(1).lower() == "cr" else 1
        text = text[:m.start()].strip()
    try:
        a = parse_amount(text)
    except AmountParseError as exc:
        raise ValueError(f"{where}: {exc}") from exc
    return None if a is None else a * sign


def _from_table(rows: list[tuple[int, list]], tb: TrialBalance, sheet: str) -> bool:
    header_at, cols = None, {}
    for i, (_n, values) in enumerate(rows[:40]):
        names = [normalize_header(v) for v in values]
        found = {}
        for key, options in _COLS.items():
            for o in options:
                if o in names and names.index(o) not in found.values():
                    found[key] = names.index(o)
                    break
        if "name" in found and ("debit" in found or "closing" in found):
            header_at, cols = i, found
            break
    if header_at is None:
        return False
    raw: list[TbRow] = []
    group, primary = "", ""
    for n, values in rows[header_at + 1:]:
        def cell(key, values=values):
            i = cols.get(key)
            return values[i] if i is not None and i < len(values) else None

        name = str(cell("name") or "").strip()
        if not name or _TOTAL.search(name):
            continue
        where = f"{sheet} row {n}"
        if "debit" in cols:
            dr, cr = _amt(cell("debit"), where) or ZERO, _amt(cell("credit"), where) or ZERO
            closing = dr - abs(cr)  # a debit column may also hold a signed balance (negative = credit)
        else:
            c = _amt(cell("closing"), where)
            closing = c if c is not None else ZERO
        row_group = str(cell("group") or "").strip()
        if not row_group and name.lower() in PRIMARY_GROUPS:
            group = primary = name  # a primary group heading of a detailed trial balance
            continue
        r = TbRow(name, row_group or group, "" if row_group else primary, closing, _amt(cell("opening"), where),
                  _amt(cell("tr_debit"), where), _amt(cell("tr_credit"), where), where)
        if r.debit is not None and r.debit < 0:
            r.debit = -r.debit
        if r.credit is not None and r.credit < 0:
            r.credit = -r.credit
        raw.append(r)
    if "group" not in cols:
        raw = _drop_subgroup_rows(raw, tb)
    tb.rows += raw
    return True


def _drop_subgroup_rows(rows: list[TbRow], tb: TrialBalance) -> list[TbRow]:
    """A row whose balance equals the sum of the next two or more rows (and of no fewer) is a sub-group heading of a
    detailed trial balance: its ledgers follow it. The ledgers keep the sub-group as their parent."""
    out, i = [], 0
    while i < len(rows):
        r = rows[i]
        acc, j = ZERO, i + 1
        found = None
        while j < len(rows) and j - i <= 200:
            acc += rows[j].closing
            if acc == r.closing and j - i >= 2 and r.closing:
                found = j
                break
            j += 1
        if found is not None:
            for k in range(i + 1, found + 1):
                rows[k].primary = rows[k].primary or r.primary or r.parent
                rows[k].parent = r.name
            tb.warnings.append(f"'{r.name}' read as a sub-group heading (its amount is the total of the "
                               f"{found - i} rows after it) – not counted as a ledger")
            i += 1
            continue
        out.append(r)
        i += 1
    return out


def _text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None and el.text else ""


def _from_xml(data: bytes, tb: TrialBalance) -> None:
    from .tally_xml import parse_xml

    root = parse_xml(data)
    ledgers = list(root.iter("LEDGER"))
    if ledgers:
        tb.layout = "Tally XML – ledger masters"
        for el in ledgers:
            name = el.get("NAME") or _text(el.find("NAME"))
            if not name:
                continue
            closing = _text(el.find("CLOSINGBALANCE"))
            opening = _text(el.find("OPENINGBALANCE"))
            # Tally writes debit balances as negative numbers
            tb.rows.append(TbRow(name.strip(), _text(el.find("PARENT")), _text(el.find("PRIMARYGROUP")),
                                 -(parse_amount(closing) or ZERO) if closing else ZERO,
                                 -(parse_amount(opening) or ZERO) if opening else None, row=f"ledger {name}"))
        if not any(el.find("CLOSINGBALANCE") is not None for el in ledgers):
            tb.warnings.append("The ledger masters carry no closing balance – export the Trial Balance instead")
        return
    names = list(root.iter("DSPACCNAME"))
    infos = list(root.iter("DSPACCINFO"))
    if not names or len(names) != len(infos):
        raise UnsupportedFileError("This XML is not a Tally trial balance (no DSPACCNAME / DSPACCINFO or LEDGER)")
    tb.layout = "Tally XML – Trial Balance report"
    rows, group, primary = [], "", ""
    for nm, info in zip(names, infos):
        name = _text(nm.find("DSPDISPNAME"))
        dr = _text(info.find("DSPCLDRAMT/DSPCLDRAMTA"))
        cr = _text(info.find("DSPCLCRAMT/DSPCLCRAMTA"))
        closing = -(parse_amount(dr) or ZERO) + -(parse_amount(cr) or ZERO)  # Tally: debit negative
        if name.lower() in PRIMARY_GROUPS:
            group = primary = name
            continue
        rows.append(TbRow(name, group, primary, closing, row=f"XML {name}"))
    tb.rows += _drop_subgroup_rows(rows, tb)


def read_trial_balance(path: str | Path) -> TrialBalance:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower()
    tb = TrialBalance()
    if suffix == ".xml":
        _from_xml(path.read_bytes(), tb)
    elif suffix in (".xlsx", ".xlsm", ".xls", ".csv"):
        tables = [read_csv(path, path.name)] if suffix == ".csv" else read_excel(path)
        if not any(_from_table(t.rows, tb, t.name) for t in tables):
            raise UnsupportedFileError("No trial balance heading row found – the file needs a Particulars / Ledger "
                                       "column and Debit / Credit (or Closing balance) columns")
        tb.layout = "Trial balance (CSV)" if suffix == ".csv" else "Trial balance (Excel)"
    elif suffix == ".pdf":
        raise UnsupportedFileError("A PDF trial balance cannot be read reliably – export it from TallyPrime as "
                                   "Excel or XML (Alt+E), or fetch it directly from TallyPrime")
    else:
        raise UnsupportedFileError("Use the trial balance exported from TallyPrime as Excel, CSV or XML")
    finish(tb)
    return tb


def finish(tb: TrialBalance) -> None:
    seen: dict[str, TbRow] = {}
    out = []
    for r in tb.rows:
        key = r.name.strip().lower()
        if key in seen:
            tb.warnings.append(f"Ledger '{r.name}' appears more than once ({seen[key].row}, {r.row}) – amounts added")
            seen[key].closing += r.closing
            continue
        seen[key] = r
        out.append(r)
    tb.rows = out
    if not tb.rows:
        raise ValueError("No ledgers found in the trial balance")
    if abs(tb.difference) > Decimal("1"):
        tb.warnings.append(f"Debit total ₹{tb.total_debit:,.2f} and credit total ₹{tb.total_credit:,.2f} differ by "
                           f"₹{tb.difference:,.2f} – check that the export has every ledger (and no group totals "
                           "counted as ledgers)")


# ------------------------------------------------------- direct from TallyPrime
def fetch_from_tally(client, company: str, start, end) -> tuple[bytes, TrialBalance]:
    """Ledgers and groups from TallyPrime's XML interface (``client`` is a TallyClient); returns the XML saved as the
    import file and the trial balance read from it."""
    from .tally_xml import _envelope, _xml_escape, parse_xml

    statics = (f"<SVCURRENTCOMPANY>{_xml_escape(company)}</SVCURRENTCOMPANY>"
               f"<SVFROMDATE TYPE=\"Date\">{start:%d-%b-%Y}</SVFROMDATE>"
               f"<SVTODATE TYPE=\"Date\">{end:%d-%b-%Y}</SVTODATE>")
    groups_xml = client._post(_envelope("FinTaxGroups", '<COLLECTION NAME="FinTaxGroups" ISMODIFY="No">'
                                        "<TYPE>Group</TYPE><FETCH>NAME, PARENT</FETCH></COLLECTION>", statics))
    ledgers_xml = client._post(_envelope("FinTaxTbLedgers", '<COLLECTION NAME="FinTaxTbLedgers" ISMODIFY="No">'
                                         "<TYPE>Ledger</TYPE><FETCH>NAME, PARENT, OPENINGBALANCE, CLOSINGBALANCE"
                                         "</FETCH></COLLECTION>", statics))
    parent = {}
    for g in parse_xml(groups_xml).iter("GROUP"):
        name = (g.get("NAME") or _text(g.find("NAME"))).strip()
        if name:
            parent[name] = _text(g.find("PARENT"))

    def primary_of(group: str) -> str:
        seen = set()
        while group and parent.get(group) and group not in seen and group.lower() not in PRIMARY_GROUPS:
            seen.add(group)
            group = parent[group]
        return group

    root = parse_xml(ledgers_xml)
    for el in root.iter("LEDGER"):
        p = _text(el.find("PARENT"))
        prim = ET.SubElement(el, "PRIMARYGROUP")
        prim.text = primary_of(p)
    data = ET.tostring(root, encoding="utf-8")
    tb = TrialBalance(company=company)
    _from_xml(data, tb)
    tb.layout = "Directly from TallyPrime"
    finish(tb)
    return data, tb
