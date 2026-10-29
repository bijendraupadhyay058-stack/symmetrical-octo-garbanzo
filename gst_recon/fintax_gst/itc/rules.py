"""Configurable, effective-dated ITC review rules.

Rules *flag documents for professional review*. They never decide eligibility:
a hit means "an accountant should look at this", with the statutory reference
that explains why. Every rule can be switched off, edited (keywords, supplier
GSTINs, parameters, dates) or added to, globally or for one client.

Rule kinds
----------
``keyword``  – matches words in the supplier name and the narration/description
``gstin``    – matches listed supplier GSTINs (e.g. a client's always-blocked suppliers)
``builtin``  – logic implemented in :mod:`fintax_gst.itc.review` (time limits, GSTR-2B,
               reverse charge, IMS, credit notes, payment within 180 days)
``period``   – applies to a tax period rather than a document (Rule 36(4) schedule)
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date

SEVERITIES = ("high", "medium", "info")


@dataclass
class Rule:
    code: str
    title: str
    reference: str
    kind: str  # keyword | gstin | builtin | period
    category: str  # blocked | eligibility | time_limit | rcm | credit_note | ims | payment | period
    severity: str = "medium"
    effective_from: date = date(2017, 7, 1)
    effective_to: date | None = None
    enabled: bool = True
    keywords: list[str] = field(default_factory=list)
    gstins: list[str] = field(default_factory=list)
    params: dict = field(default_factory=dict)
    guidance: str = ""

    def applies_on(self, d: date | None) -> bool:
        if not self.enabled:
            return False
        if d is None:
            return True
        return self.effective_from <= d and (self.effective_to is None or d <= self.effective_to)

    def keyword_hit(self, *texts: str) -> str | None:
        hay = " ".join(t for t in texts if t).lower()
        for kw in self.keywords:
            if re.search(rf"(?<![a-z0-9]){re.escape(kw.lower())}(?![a-z0-9])", hay):
                return kw
        return None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["effective_from"] = self.effective_from.isoformat()
        d["effective_to"] = self.effective_to.isoformat() if self.effective_to else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Rule":
        d = dict(d)
        d["effective_from"] = date.fromisoformat(d["effective_from"]) if d.get("effective_from") else date(2017, 7, 1)
        d["effective_to"] = date.fromisoformat(d["effective_to"]) if d.get("effective_to") else None
        allowed = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in allowed})


def _blocked(code, title, ref, keywords, guidance, **kw) -> Rule:
    return Rule(code, title, ref, "keyword", "blocked", "medium", keywords=keywords, guidance=guidance, **kw)


DEFAULT_RULES: list[Rule] = [
    # ---------------------------------------------------------- eligibility
    Rule("S16_2_AA", "ITC on a document not reflected in GSTR-2B",
         "Section 16(2)(aa), CGST Act 2017 (inserted w.e.f. 01-01-2022)", "builtin", "eligibility", "high",
         effective_from=date(2022, 1, 1),
         guidance="Credit is available only when the supplier has furnished the document and it is communicated "
                  "in GSTR-2B. Defer the claim until it appears; follow up with the supplier."),
    Rule("ITC_NA_2B", "GSTR-2B marks ITC as not available",
         "GSTR-2B 'ITC availability = No' (e.g. Section 16(4) time limit, place-of-supply rules)", "builtin",
         "eligibility", "high",
         guidance="Read the reason shown in GSTR-2B. Such ITC is reported in GSTR-3B Table 4(D)(2), not claimed."),
    Rule("S16_4", "Time limit for availing ITC", "Section 16(4), CGST Act 2017", "builtin", "time_limit", "high",
         params={"alert_days": 60},
         guidance="For documents of FY 2021-22 onwards the last date is 30 November following the end of the "
                  "financial year (Finance Act 2022, w.e.f. 01-10-2022); earlier years: due date of the September "
                  "GSTR-3B following the year. If the annual return is filed earlier, that date applies. "
                  "Section 16(5) (inserted by Finance (No. 2) Act 2024) relaxes FY 2017-18 to 2020-21."),
    Rule("RCM", "Reverse charge supply", "Section 9(3)/9(4) and Section 31(3)(f), CGST Act; GSTR-3B Table 4(A)(3)",
         "builtin", "rcm", "medium",
         guidance="ITC is available only after the tax is paid in cash under reverse charge; report in 4(A)(3)."),
    Rule("CN_2B_NOT_BOOKED", "Supplier credit note in GSTR-2B not recorded in books",
         "Section 34, CGST Act; ITC to be reduced (GSTR-3B Table 4(A)(5) net / 4(B)(2))", "builtin",
         "credit_note", "high",
         guidance="Record the credit note and reduce ITC in the period it appears in GSTR-2B."),
    Rule("IMS_REJECTED", "Document rejected in IMS but booked",
         "Invoice Management System (w.e.f. 01-10-2024); Section 16(2)(aa)", "builtin", "ims", "high",
         effective_from=date(2024, 10, 1),
         guidance="A rejected document does not flow to GSTR-2B. Do not claim ITC on it; reconcile with the "
                  "supplier and the client."),
    Rule("IMS_PENDING", "Document kept pending in IMS",
         "Invoice Management System (w.e.f. 01-10-2024)", "builtin", "ims", "info",
         effective_from=date(2024, 10, 1),
         guidance="Pending documents are excluded from GSTR-2B of the period; ITC moves to the period in which "
                  "the document is accepted (subject to Section 16(4))."),
    Rule("RULE_37_180", "Payment to supplier within 180 days",
         "Second proviso to Section 16(2), CGST Act; Rule 37, CGST Rules", "builtin", "payment", "info",
         enabled=False, params={"days": 180},
         guidance="If consideration and tax are not paid within 180 days of the invoice date, the ITC must be "
                  "reversed (with interest) and can be reclaimed on payment. Enable when payment data is reviewed."),
    # ------------------------------------------------- blocked credit indicators
    _blocked("S17_5_A_MOTOR", "Motor vehicles / conveyances (possible blocked credit)",
             "Section 17(5)(a), (aa), (ab), CGST Act (as substituted w.e.f. 01-02-2019)",
             ["motor car", "car purchase", "vehicle purchase", "motors", "automobile", "automobiles",
              "car service", "vehicle repair", "vehicle insurance", "motor insurance"],
             "Blocked for motor vehicles with seating capacity up to 13 (including driver) unless used for further "
             "supply, transport of passengers, driving training or transport of goods; also their repair and "
             "insurance."),
    _blocked("S17_5_B_I_FOOD", "Food, beverages or outdoor catering (possible blocked credit)",
             "Section 17(5)(b)(i), CGST Act",
             ["restaurant", "catering", "caterers", "food", "beverages", "canteen", "sweets", "refreshment",
              "refreshments", "lunch", "dinner"],
             "Blocked unless used for making an outward supply of the same category or as part of a taxable "
             "composite/mixed supply, or obligatory for an employer to provide under any law."),
    _blocked("S17_5_B_I_BEAUTY", "Beauty, health, cosmetic or plastic surgery services (possible blocked credit)",
             "Section 17(5)(b)(i), CGST Act",
             ["beauty", "salon", "spa", "cosmetic", "plastic surgery", "health care", "clinic", "hospital"],
             "Blocked unless used for the same category of outward supply or obligatory under any law."),
    _blocked("S17_5_B_I_INSURANCE", "Life or health insurance (possible blocked credit)",
             "Section 17(5)(b)(i), CGST Act", ["life insurance", "health insurance", "mediclaim", "group insurance"],
             "Blocked unless obligatory for the employer under any law or used for the same category of supply."),
    _blocked("S17_5_B_I_CAB", "Renting or hiring of motor vehicles (possible blocked credit)",
             "Section 17(5)(b)(i), CGST Act", ["rent a cab", "car rental", "car hire", "cab", "taxi"],
             "Blocked where the vehicle itself would be blocked, unless obligatory under any law."),
    _blocked("S17_5_B_II_CLUB", "Club membership, health and fitness centre (possible blocked credit)",
             "Section 17(5)(b)(ii), CGST Act", ["club", "gym", "fitness", "membership fee"],
             "Blocked."),
    _blocked("S17_5_B_III_TRAVEL", "Travel benefits to employees on vacation (possible blocked credit)",
             "Section 17(5)(b)(iii), CGST Act", ["leave travel", "holiday", "vacation", "tour package"],
             "Blocked unless obligatory for the employer under any law."),
    _blocked("S17_5_C_D_CONSTRUCTION", "Works contract / construction of immovable property (possible blocked credit)",
             "Section 17(5)(c) and (d), CGST Act",
             ["works contract", "construction", "civil work", "civil works", "builders", "building repair"],
             "Blocked when the construction is capitalised to immovable property (other than plant and machinery), "
             "except where the works contract service is input for further works contract supply."),
    _blocked("S17_5_G_PERSONAL", "Personal consumption (possible blocked credit)",
             "Section 17(5)(g), CGST Act", ["personal", "residence", "home use", "household"],
             "Goods or services used for personal consumption are blocked."),
    _blocked("S17_5_H_GIFTS", "Gifts, free samples, goods lost or written off (possible blocked credit)",
             "Section 17(5)(h), CGST Act", ["gift", "gifts", "free sample", "free samples", "diwali", "festival"],
             "Blocked for goods disposed of by way of gift or free samples, or lost, stolen, destroyed or written off."),
    Rule("CLIENT_BLOCKED_GSTIN", "Supplier marked as blocked / non-business for this client",
         "Section 17(5) / Section 16(1), CGST Act – client-specific review", "gstin", "blocked", "medium",
         guidance="Add supplier GSTINs whose credit the client never claims (e.g. personal or exempt use)."),
    # --------------------------------------------------------------- period
    Rule("R36_4", "Provisional ITC limit over GSTR-2A/2B", "Rule 36(4), CGST Rules (09-10-2019 to 31-12-2021)",
         "period", "period", "high", effective_from=date(2019, 10, 9), effective_to=date(2021, 12, 31),
         params={"schedule": {"2019-10-09": 20, "2020-01-01": 10, "2021-01-01": 5}},
         guidance="ITC on documents not reflected in GSTR-2A/2B was capped at the stated percentage of eligible "
                  "reflected ITC. From 01-01-2022 Section 16(2)(aa) allows only reflected ITC."),
]
DEFAULTS_BY_CODE = {r.code: r for r in DEFAULT_RULES}


def provisional_limit_pct(rule: Rule, period_start: date) -> int | None:
    """Rule 36(4) percentage applicable to a tax period, or None outside the rule's dates."""
    if not rule.applies_on(period_start):
        return None
    pct = None
    for start, value in sorted(rule.params.get("schedule", {}).items()):
        if period_start >= date.fromisoformat(start):
            pct = int(value)
    return pct


def resolve(global_rows: list[dict], client_rows: list[dict]) -> list[Rule]:
    """Defaults, then global overrides/additions, then client-specific ones."""
    rules = {r.code: Rule.from_dict(r.to_dict()) for r in DEFAULT_RULES}
    for layer in (global_rows, client_rows):
        for d in layer:
            rules[d["code"]] = Rule.from_dict(d)
    order = {r.code: i for i, r in enumerate(DEFAULT_RULES)}
    return sorted(rules.values(), key=lambda r: (order.get(r.code, 999), r.code))
