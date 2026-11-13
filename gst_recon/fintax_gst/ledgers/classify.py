"""Classification lists and the rule-based suggestion engine for ledger bifurcation.

Two independent classifications are kept for every part of a ledger:

* **Accounting classification** – what the amount is in the books (trading goods, raw material, repairs, plant &
  machinery …), grouped as purchases, direct expenses, indirect expenses or fixed assets;
* **GST classification** – inputs, input services, capital goods, exempt / nil / non-GST inward supplies, no GST
  (salary, depreciation …), or excluded (counted in another ledger); with the **source** of the supply (regular,
  reverse charge from registered / unregistered persons, import of goods / services, ISD) and the **ITC
  eligibility** (eligible, blocked under section 17(5), reversed under rules 42/43 or 37/37A, non-business use,
  exempt-supply attribution, not availed, reclaimed).

Suggestions come from the ledger name and its Tally group, or from a classification the user approved for the same
ledger name earlier (confidence "saved"). A suggestion is never final: the user approves or changes every one.
An eligible GST classification is never inferred from the fact that GST was charged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# accounting classification -> accounting group
ACCT_GROUPS = ("Purchases", "Direct expenses", "Indirect expenses", "Fixed assets", "Other")
ACCT_CLASSES: dict[str, str] = {
    # purchases
    "Trading goods": "Purchases", "Raw materials": "Purchases", "Manufacturing & consumables": "Purchases",
    "Packing material": "Purchases", "Stores & spares": "Purchases", "Purchase of services": "Purchases",
    "Exempt / non-GST purchases": "Purchases", "Imports": "Purchases", "RCM purchases": "Purchases",
    "Other purchases": "Purchases",
    # expenses
    "Direct expenses": "Direct expenses", "Contract & labour charges": "Direct expenses",
    "Freight & transportation": "Direct expenses", "Power & fuel": "Direct expenses",
    "Professional & consultancy": "Indirect expenses", "Legal & audit fees": "Indirect expenses",
    "Rent & lease": "Indirect expenses", "Repairs & maintenance": "Indirect expenses",
    "Advertisement & marketing": "Indirect expenses", "Telephone & internet": "Indirect expenses",
    "Software & IT services": "Indirect expenses", "Insurance": "Indirect expenses",
    "Bank & finance charges": "Indirect expenses", "Office expenses": "Indirect expenses",
    "Electricity & utilities": "Indirect expenses", "Employee costs": "Indirect expenses",
    "Travel & conveyance": "Indirect expenses", "Printing & stationery": "Indirect expenses",
    "Food, gifts & entertainment": "Indirect expenses", "Non-GST expenses": "Indirect expenses",
    "Depreciation & interest": "Indirect expenses", "Indirect expenses – other": "Indirect expenses",
    "Capital expenditure (booked as expense)": "Fixed assets",
    # fixed assets
    "Plant & machinery": "Fixed assets", "Computers & laptops": "Fixed assets",
    "Furniture & fixtures": "Fixed assets", "Vehicles": "Fixed assets", "Office equipment": "Fixed assets",
    "Electrical equipment": "Fixed assets", "Buildings & civil work": "Fixed assets",
    "Other fixed assets": "Fixed assets",
    # not counted
    "Counted in another ledger": "Other", "Other accounting head": "Other",
}
GST_CLASSES = {"inputs": "Inputs", "services": "Input services", "capital": "Capital goods",
               "exempt": "Exempt / nil / non-GST inward", "nogst": "No GST (outside GST)",
               "excluded": "Excluded – counted elsewhere"}
ITC_CLASSES = ("inputs", "services", "capital")
GST_SOURCES = {"regular": "Regular (B2B)", "rcm_reg": "RCM – registered", "rcm_unreg": "RCM – unregistered",
               "import_g": "Import of goods", "import_s": "Import of services", "isd": "ISD"}
ELIGIBILITY = {"eligible": "Eligible", "blocked": "Blocked – section 17(5)", "rule42": "Reversed – rule 42/43",
               "rule37": "Reversed – rule 37/37A", "nonbusiness": "Non-business use",
               "exempt_attr": "Exempt-supply attribution", "not_availed": "Not availed",
               "reclaimed": "Reclaimed", "na": "Not applicable (no GST)"}
#: eligibility codes whose ITC counts as availed / reversed / ineligible
AVAILED = ("eligible", "reclaimed")
REVERSED = ("rule42", "rule37", "exempt_attr")
INELIGIBLE = ("blocked", "nonbusiness")
GST_BASIS = {"invoices": "From purchase-register invoices", "entered": "Entered from invoices",
             "apportioned": "Apportioned – approved by the user", "": "GST not given"}
CONFIDENCE = ("saved", "high", "medium", "low")


@dataclass
class Suggestion:
    acct_class: str
    gst_class: str
    gst_source: str = "regular"
    head_9c: str = ""
    eligibility: str = "eligible"
    confidence: str = "low"
    reason: str = ""


# (pattern on the ledger name, accounting class, GST class, source, GSTR-9C row, eligibility, note)
RULES: list[tuple[str, str, str, str, str, str, str]] = [
    (r"depreciation|amorti[sz]ation|interest (paid|on|expense)|^interest\b", "Depreciation & interest", "nogst",
     "regular", "14N", "na", "outside GST"),
    (r"salar|wages|bonus|gratuity|provident|\bpf\b|\besi\b|staff welfare|leave encash|director.?s? remuneration",
     "Employee costs", "nogst", "regular", "14H", "na", "employee cost – no GST (check staff welfare items)"),
    (r"motor car|vehicle|car purchase|\bcar\b", "Vehicles", "capital", "regular", "14O", "blocked",
     "motor vehicles – usually blocked under section 17(5)(a); check the use"),
    (r"food|catering|canteen|refreshment|club|membership|gift|entertain|hospitality|party",
     "Food, gifts & entertainment", "services", "regular", "14K", "blocked",
     "food, club, gifts – usually blocked under section 17(5)(b)/(h)"),
    (r"plant|machinery|machine\b", "Plant & machinery", "capital", "regular", "14O", "eligible", ""),
    (r"computer|laptop|server|printer|\bit hardware", "Computers & laptops", "capital", "regular", "14O",
     "eligible", ""),
    (r"furniture|fixture", "Furniture & fixtures", "capital", "regular", "14O", "eligible", ""),
    (r"office equipment|air ?condition|\bac\b|equipment", "Office equipment", "capital", "regular", "14O",
     "eligible", ""),
    (r"electrical (fitting|installation|equipment)|generator|\bdg set|transformer", "Electrical equipment", "capital",
     "regular", "14O", "eligible", ""),
    (r"building|civil|construction|premises", "Buildings & civil work", "capital", "regular", "14O", "blocked",
     "construction of immovable property – usually blocked under section 17(5)(c)/(d)"),
    (r"import", "Imports", "inputs", "import_g", "14D", "eligible", "import – ITC from the bill of entry"),
    (r"raw material|\brm\b", "Raw materials", "inputs", "regular", "14A", "eligible", ""),
    (r"packing|packaging", "Packing material", "inputs", "regular", "14A", "eligible", ""),
    (r"stores|spares|spare parts", "Stores & spares", "inputs", "regular", "14A", "eligible", ""),
    (r"consumable", "Manufacturing & consumables", "inputs", "regular", "14A", "eligible", ""),
    (r"exempt|nil rated|non.?gst|unregistered purchase", "Exempt / non-GST purchases", "exempt", "regular", "14A",
     "na", ""),
    (r"\brcm\b|reverse charge", "RCM purchases", "services", "rcm_unreg", "14N", "eligible",
     "reverse charge – check registered / unregistered supplier"),
    (r"purchase|finished goods|trading|stock", "Trading goods", "inputs", "regular", "14A", "eligible", ""),
    (r"audit fee|legal|advocate|lawyer", "Legal & audit fees", "services", "regular", "14N", "eligible",
     "advocate services are under reverse charge"),
    (r"professional|consultan|chartered accountant|\bca fee|retainer|technical fee", "Professional & consultancy",
     "services", "regular", "14N", "eligible", ""),
    (r"freight|carriage|cartage|transport|\bgta\b|logistic|courier", "Freight & transportation", "services",
     "regular", "14B", "eligible", "goods transport agency – check reverse charge"),
    (r"rent|lease|hire charges", "Rent & lease", "services", "regular", "14E", "eligible",
     "residential rent / rent from unregistered persons may be under reverse charge"),
    (r"insurance", "Insurance", "services", "regular", "14E", "eligible",
     "insurance of motor vehicles / life / health is usually blocked under section 17(5)"),
    (r"repair|maintenance|upkeep|amc", "Repairs & maintenance", "services", "regular", "14M", "eligible",
     "may include spare parts (inputs) or capital improvement – split if so"),
    (r"advertis|marketing|promotion|publicity|sales promotion", "Advertisement & marketing", "services", "regular",
     "14N", "eligible", "free samples / gifts are blocked"),
    (r"telephone|mobile|internet|broadband|communication", "Telephone & internet", "services", "regular", "14N",
     "eligible", ""),
    (r"software|subscription|cloud|hosting|domain|it services", "Software & IT services", "services", "regular",
     "14N", "eligible", "foreign software subscriptions may be import of services (reverse charge)"),
    (r"bank charge|bank commission|processing fee|loan charges", "Bank & finance charges", "services", "regular",
     "14J", "eligible", ""),
    (r"contract|labour|job work|manpower|security service|housekeeping", "Contract & labour charges", "services",
     "regular", "14N", "eligible", ""),
    (r"electricity|power|water charges", "Electricity & utilities", "nogst", "regular", "14C", "na",
     "electricity is outside GST"),
    (r"fuel|diesel|petrol", "Power & fuel", "exempt", "regular", "14C", "na",
     "petrol / diesel are outside GST"),
    (r"travel|conveyance|taxi|cab|tour|hotel|lodging", "Travel & conveyance", "services", "regular", "14I",
     "eligible", "rent-a-cab / travel benefits for employees are usually blocked"),
    (r"printing|stationer|postage", "Printing & stationery", "inputs", "regular", "14L", "eligible", ""),
    (r"office exp|general exp|misc|sundry exp", "Office expenses", "services", "regular", "14N", "eligible",
     "mixed ledger – check the vouchers"),
    (r"rates? & taxes|stamp|registration|govt fee|government fee|penalt|donation|charity|fine",
     "Non-GST expenses", "nogst", "regular", "14N", "na", "outside GST"),
]
_COMPILED = [(re.compile(p, re.I), *rest) for p, *rest in RULES]

#: what a ledger under a group is most likely to be, used when no name rule applies
GROUP_DEFAULTS = {
    "purchase": Suggestion("Trading goods", "inputs", head_9c="14A", reason="ledger under Purchase Accounts"),
    "asset": Suggestion("Other fixed assets", "capital", head_9c="14O", reason="ledger under Fixed Assets"),
    "expense": Suggestion("Indirect expenses – other", "services", head_9c="14N",
                          reason="ledger under an expense group"),
}


def default_head(acct_class: str, gst_class: str) -> str:
    """GSTR-9C Table 14 row for a part whose head was not chosen."""
    from ..gstr9.expenses import row_for

    if gst_class == "capital":
        return "14O"
    for _rx, acct, _g, _s, head, _e, _n in RULES:
        if acct == acct_class:
            return head
    row = row_for(acct_class)
    return "14A" if row == "14N" and gst_class == "inputs" else row


def ledger_key(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def suggest(name: str, parent: str, nature: str, saved: dict | None = None) -> Suggestion | None:
    """A suggestion for a ledger, or None when nothing can be said (then it stays pending)."""
    if saved:
        return Suggestion(saved["acct_class"], saved["gst_class"], saved.get("gst_source", "regular"),
                          saved.get("head_9c", ""), saved.get("eligibility", ""), "saved",
                          "approved earlier for this client")
    text = f"{name}"
    for rx, acct, gst, source, head, elig, note in _COMPILED:
        if rx.search(text):
            group = ACCT_CLASSES.get(acct, "Other")
            agrees = {"Purchases": "purchase", "Fixed assets": "asset", "Direct expenses": "expense",
                      "Indirect expenses": "expense"}.get(group) == nature
            if gst == "capital" and nature == "expense":
                acct, agrees = "Capital expenditure (booked as expense)", False
                note = (note + "; " if note else "") + "a capital item booked as an expense – check"
            conf = "high" if agrees else "medium"
            reason = f"name '{rx.pattern.split('|')[0]}…'" + (" and its group agree" if agrees else
                                                              f" (group: {parent or nature})")
            return Suggestion(acct, gst, source, head, elig, conf, reason + (f" – {note}" if note else ""))
    d = GROUP_DEFAULTS.get(nature)
    if d is None:
        return None
    return Suggestion(d.acct_class, d.gst_class, d.gst_source, d.head_9c, d.eligibility, "low", d.reason)
