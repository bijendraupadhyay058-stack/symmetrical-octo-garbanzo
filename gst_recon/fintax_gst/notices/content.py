"""What goes into a draft reply to a GST notice.

Supported forms:

* **DRC-01B** (rule 88C) – GSTR-1 / IFF liability above the tax paid in GSTR-3B.
* **DRC-01C** (rule 88D) – ITC availed in GSTR-3B above the ITC available in GSTR-2B.
* **ASMT-10** (section 61) – scrutiny of returns. The reply carries both comparisons and
  a section for the officer's other observations.
* **OTHER** – a covering reply with both comparisons.

The draft holds only what the imported data, the reconciliations, the interest working
and the recorded settlements establish. Anything the preparer must supply or confirm is
a ``[[placeholder]]``, highlighted in the Word file, and never invented: the reason for
a difference that no finding explains, DRC-03 references, the documents enclosed and
the officer's details.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..core.money import ZERO, fmt_inr

FORMS = {
    "DRC-01B": "Intimation of difference in liability reported in GSTR-1 / IFF and GSTR-3B (rule 88C)",
    "DRC-01C": "Intimation of difference in ITC available in GSTR-2B and availed in GSTR-3B (rule 88D)",
    "ASMT-10": "Notice for intimating discrepancies in the return after scrutiny (section 61, rule 99)",
    "OTHER": "Notice / communication",
}
HEADS = ("igst", "cgst", "sgst", "cess")


def ph(text: str) -> str:
    """A placeholder the preparer completes (highlighted in the Word file)."""
    return f"[[{text}]]"


def note(text: str) -> str:
    """Internal working information for the preparer – highlighted, and to be deleted before sending."""
    return ph(f"Working note – delete before sending: {text}")


@dataclass
class Section:
    heading: str
    paragraphs: list[str] = field(default_factory=list)
    table: tuple[list[str], list[list[str]]] | None = None


@dataclass
class ReplyDraft:
    form: str
    subject: str
    sections: list[Section]
    placeholders: int = 0
    difference: Decimal | None = None  # per the working, for comparison with the notice


@dataclass
class NoticeFacts:
    form: str
    reference: str
    notice_date: date
    period_from: str
    period_to: str
    amount: Decimal | None
    officer: str
    client_name: str
    client_gstin: str


@dataclass
class PeriodComparison:
    period: str
    left: Decimal  # GSTR-1 tax (DRC-01B) / ITC in GSTR-3B (DRC-01C)
    right: Decimal  # GSTR-3B tax / ITC per GSTR-2B
    findings: list[tuple[str, str, Decimal]] = field(default_factory=list)  # (kind, text, amount)

    @property
    def difference(self) -> Decimal:
        return self.left - self.right


def _comparison(title: str, left_label: str, right_label: str, rows: list[PeriodComparison], diff_label: str,
                notice_amount: Decimal | None, no_reason: str) -> list[Section]:
    total = sum((r.difference for r in rows), ZERO)
    table_rows = [[r.period, fmt_inr(r.left), fmt_inr(r.right), fmt_inr(r.difference)] for r in rows]
    table_rows.append(["Total", fmt_inr(sum((r.left for r in rows), ZERO)), fmt_inr(sum((r.right for r in rows), ZERO)),
                       fmt_inr(total)])
    paras = ["The month-wise position per the returns filed is given below (tax in ₹, all heads)."]
    if notice_amount is not None:
        gap = notice_amount - total
        paras.append(f"The difference per our reconciliation is ₹{fmt_inr(total)}, against ₹{fmt_inr(notice_amount)} "
                     "in the notice" + (" – the figures agree." if abs(gap) < 1 else
                                        f"; the variation of ₹{fmt_inr(gap)} is " + ph("explain the variation") + "."))
    sections = [Section(title, paras, (["Period", left_label, right_label, diff_label], table_rows))]
    if any(abs(r.difference) >= 1 for r in rows):
        # the explanation is the preparer's; the working's findings are offered as notes, never as reply text
        reasons = [ph(no_reason)]
        for r in rows:
            for kind, text, amount in r.findings:
                reasons.append(note(f"{r.period}: {text}" + (f" (₹{fmt_inr(amount)})" if amount else "")
                                    + (f" [{kind}]" if kind else "")))
        sections.append(Section("Reasons for the difference", reasons))
    return sections


def _settlements(kind_label: str, exposures: list, as_of: date, act: str) -> Section | None:
    """Payment / reversal position from the interest working (11A)."""
    if not exposures:
        return None
    paras = []
    by_period: dict[str, list] = {}
    for e in exposures:
        by_period.setdefault(e.period, []).append(e)
    for p, es in sorted(by_period.items()):
        amount = sum((e.amount for e in es), ZERO)
        interest = sum((e.interest for e in es), ZERO)
        heads = ", ".join(f"{e.head.upper()} ₹{fmt_inr(e.amount)}" for e in es)
        status = es[0].status
        if status == "SETTLED":
            paras.append(f"{p}: {kind_label} of ₹{fmt_inr(amount)} ({heads}) {act} on {es[0].end:%d-%m-%Y}"
                         + (f" vide {es[0].reference}" if es[0].reference else f" vide {ph('DRC-03 ARN')}")
                         + f", with interest under section 50 of ₹{fmt_inr(interest)} "
                         + ph("confirm the interest was paid, with its reference") + ".")
        elif status == "NOT_PAYABLE":
            reason = es[0].basis.split("not payable: ", 1)[-1]
            paras.append(f"{p}: the amount of ₹{fmt_inr(amount)} ({heads}) is not payable: {reason}.")
        else:
            paras.append(ph(f"state whether the amount for {p} is being {act.split()[-1]} through DRC-03 / GSTR-3B, "
                            "or why it is not payable"))
            paras.append(note(f"{p}: ₹{fmt_inr(amount)} ({heads}) not recorded as settled; interest under section 50 "
                              f"to {as_of:%d-%m-%Y} would be ₹{fmt_inr(interest)}"))
    return Section("Payment / reversal and interest", paras)


def build_reply(facts: NoticeFacts, liability: list[PeriodComparison], itc: list[PeriodComparison],
                short_payments: list, excess_itc: list, as_of: date) -> ReplyDraft:
    form = facts.form if facts.form in FORMS else "OTHER"
    span = (f"{facts.period_from}" if facts.period_from == facts.period_to
            else f"{facts.period_from} to {facts.period_to}")
    ref = facts.reference or ph("notice reference / DIN")
    subject = (f"Reply to {form if form != 'OTHER' else 'notice'} {ref} dated {facts.notice_date:%d-%m-%Y} – "
               f"{facts.client_name} (GSTIN {facts.client_gstin}) – tax period {span}")
    what = {"DRC-01B": "intimation in Form GST DRC-01B", "DRC-01C": "intimation in Form GST DRC-01C",
            "ASMT-10": "notice in Form GST ASMT-10"}.get(form, "notice")
    opening = (f"We refer to the {what} {ref} dated {facts.notice_date:%d-%m-%Y}"
               + f" for the tax period {span}"
               + (f", communicating a difference of ₹{fmt_inr(facts.amount)}" if facts.amount is not None else "")
               + ". We have reconciled the returns with our books of account and submit as under.")
    sections = [Section("", [opening])]
    difference = None
    if form in ("DRC-01B", "ASMT-10", "OTHER") and liability:
        sections += _comparison("Output tax: GSTR-1 / IFF compared with GSTR-3B", "GSTR-1 / IFF", "GSTR-3B 3.1(a)+(b)",
                                liability, "Difference", facts.amount if form == "DRC-01B" else None,
                                "explain why the tax in GSTR-1 is more than in GSTR-3B for these months (e.g. "
                                "amendments, advances, invoices reported in GSTR-1 of another month)")
        s = _settlements("tax short paid", short_payments, as_of, "was paid")
        if s:
            sections.append(s)
        difference = sum((r.difference for r in liability), ZERO)
    if form in ("DRC-01C", "ASMT-10", "OTHER") and itc:
        sections += _comparison("Input tax credit: GSTR-3B compared with GSTR-2B", "ITC in GSTR-3B 4(C)",
                                "ITC per GSTR-2B", itc, "Excess", facts.amount if form == "DRC-01C" else None,
                                "explain the excess ITC (e.g. ITC on invoices of earlier months reported late, "
                                "import IGST, ISD credit, ITC reclaimed)")
        s = _settlements("excess ITC", excess_itc, as_of, "was reversed")
        if s:
            sections.append(s)
        if form == "DRC-01C":
            difference = sum((r.difference for r in itc), ZERO)
    if (form in ("DRC-01B",) and not liability) or (form == "DRC-01C" and not itc):
        sections.append(Section("Reconciliation", [ph("the returns for these periods are not imported – import "
                                                      "GSTR-1, GSTR-3B and GSTR-2B, or give the reconciliation here")]))
    if form == "ASMT-10":
        sections.append(Section("Other discrepancies in the notice", [
            ph("reply to each discrepancy in the notice, point by point, with the supporting documents")]))
    part_b = {"DRC-01B": " Part B of Form GST DRC-01B is being filed accordingly.",
              "DRC-01C": " Part B of Form GST DRC-01C is being filed accordingly."}.get(form, "")
    sections.append(Section("", [
        "In view of the above, we request that the explanation be accepted and the matter be closed." + part_b,
        "Documents enclosed: " + ph("list the reconciliation statements, DRC-03 challans and other documents"),
        "We shall be glad to furnish any further information required."]))
    count = sum(p.count("[[") for s in sections for p in s.paragraphs) + subject.count("[[")
    return ReplyDraft(form, subject, sections, count, difference)
