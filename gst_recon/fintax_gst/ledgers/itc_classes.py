"""Classification of inward supplies for the ITC register, in three independent dimensions, and the engine that
proposes them.

Evidence is used in this order (spec priority): a manual classification of the transaction; a saved mapping rule
(supplier GSTIN + ledger, GSTIN, HSN/SAC, ledger, keyword); the classification approved for the ledger in Ledger
classification; HSN/SAC (a SAC 99… is a service); the words of the ledger / item / narration; nothing → "requires
review". A purchase voucher alone never makes a transaction a trading purchase, and reverse charge is taken only
from the voucher's own reverse-charge mark or a rule – never inferred from the kind of expense.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

NATURES = {"trading": "Trading purchase", "raw": "Raw material", "other_goods": "Other input goods",
           "services": "Input services", "capital": "Capital goods", "nongst": "Non-GST / exempt",
           "unclassified": "Unclassified – review"}
GOODS = ("trading", "raw", "other_goods")
TREATMENTS = {"fcm": "FCM (forward charge)", "rcm_reg": "RCM – registered supplier",
              "rcm_unreg": "RCM – unregistered supplier", "import_g": "Import of goods",
              "import_s": "Import of services", "sez": "SEZ inward supply", "isd": "ISD credit",
              "deemed_exp": "Deemed export inward", "other": "Other / review"}
RCM = ("rcm_reg", "rcm_unreg")
#: ITC eligibility – what the law allows on the supply (independent of what was claimed)
STATUSES = {"eligible": "Eligible", "partial": "Partly eligible", "blocked": "Ineligible / blocked – s.17(5)",
            "reversal_req": "Reversal required – rules 37 / 42 / 43", "pending": "Eligibility to verify"}
#: ITC claim – what was actually done in GSTR-3B (independent of classification and eligibility)
CLAIMS = {"claimed": "Claimed in GSTR-3B", "not_claimed": "Not claimed (yet)", "reversed": "Claimed, then reversed",
          "temp_reversed": "Claimed, temporarily reversed", "reclaimed": "Reclaimed", "unknown": "Claim not verified"}
#: claim states whose ITC was availed in GSTR-3B (GSTR-9 Table 6); reversed ones also go to Table 7
AVAILED = ("claimed", "reversed", "temp_reversed", "reclaimed")
REVERSED = ("reversed", "temp_reversed")
ELIGIBLE = ("eligible", "partial")
CONFIDENCE = {"high": "High", "medium": "Medium", "low": "Low", "manual": "Manual review required"}
SCOPES = {"gstin_ledger": "Supplier GSTIN + ledger", "gstin": "Supplier GSTIN", "hsn": "HSN / SAC",
          "ledger": "Ledger", "keyword": "Word in ledger / item / narration"}
SCOPE_ORDER = ("gstin_ledger", "gstin", "hsn", "ledger", "keyword")

# ledger-bifurcation classes -> nature
_BIF_NATURE = {"services": "services", "capital": "capital", "exempt": "nongst", "nogst": "nongst",
               "excluded": "unclassified"}
_BIF_STATUS = {"eligible": "eligible", "blocked": "blocked", "nonbusiness": "blocked", "rule42": "reversal_req",
               "rule37": "reversal_req", "exempt_attr": "reversal_req", "not_availed": "eligible",
               "reclaimed": "eligible"}
_BIF_TREAT = {"regular": "fcm", "rcm_reg": "rcm_reg", "rcm_unreg": "rcm_unreg", "import_g": "import_g",
              "import_s": "import_s", "isd": "isd"}


def nature_from_bifurcation(acct_class: str, gst_class: str) -> str:
    if gst_class == "inputs":
        return {"Trading goods": "trading", "Raw materials": "raw"}.get(acct_class, "other_goods")
    return _BIF_NATURE.get(gst_class, "unclassified")


def ledger_of(description: str) -> str:
    m = re.match(r"\s*Ledger:\s*([^·|]+)", description or "")
    return m.group(1).strip() if m else ""


@dataclass
class Proposal:
    nature: str = "unclassified"
    treatment: str = ""
    status: str = "pending"
    basis: str = "auto"
    confidence: str = "manual"
    rule_id: int | None = None
    reason: str = ""
    _nature_set: bool = False
    _treatment_set: bool = False
    _status_set: bool = False


def rule_matches(rule, txn) -> bool:
    v = (rule.value or "").strip().lower()
    ledger = (txn.ledger or "").lower()
    if rule.scope == "gstin":
        return bool(txn.gstin) and txn.gstin.upper() == rule.value.upper()
    if rule.scope == "gstin_ledger":
        return bool(txn.gstin) and txn.gstin.upper() == rule.value.upper() and ledger == (rule.value2 or "").lower()
    if rule.scope == "ledger":
        return bool(ledger) and ledger == v
    if rule.scope == "hsn":
        return bool(txn.hsn) and any(h.strip().startswith(v) for h in txn.hsn.split(","))
    if rule.scope == "keyword":
        return bool(v) and v in f"{txn.ledger} {txn.description} {txn.party}".lower()
    return False


def propose(txn, rules: list, ledger_maps: dict[str, dict]) -> Proposal:
    """Nature / treatment / status for a transaction from rules and evidence (manual parts are not touched)."""
    from .classify import suggest

    p = Proposal()
    reasons = []
    # 1. rules, most specific scope first; each dimension from the first rule that sets it
    ordered = sorted(rules, key=lambda r: (SCOPE_ORDER.index(r.scope) if r.scope in SCOPE_ORDER else 9, -r.id))
    for r in ordered:
        if not rule_matches(r, txn):
            continue
        hit = False
        for dim in ("nature", "treatment", "status"):
            val = getattr(r, dim)
            if val and not getattr(p, f"_{dim}_set"):
                setattr(p, dim, val)
                setattr(p, f"_{dim}_set", True)
                hit = True
        if hit:
            p.basis, p.confidence, p.rule_id = "rule", "high", p.rule_id or r.id
            reasons.append(f"rule: {SCOPES.get(r.scope, r.scope)} '{r.value}'" + (f" + '{r.value2}'" if r.value2 else ""))
    nature_set = getattr(p, "_nature_set", False)
    # 2. classification approved for the ledger (Ledger classification)
    led = (txn.ledger or "").strip().lower()
    m = ledger_maps.get(re.sub(r"\s+", " ", led)) if led else None
    if m and not nature_set:
        p.nature = nature_from_bifurcation(m["acct_class"], m["gst_class"])
        nature_set = True
        if p.basis != "rule":
            p.confidence = "medium" if m.get("firm") else "high"
        reasons.append(f"ledger '{txn.ledger}' " + ("in the firm's mapping template as " if m.get("firm") else
                                                    "approved as ") + m["acct_class"])
        if not getattr(p, "_status_set", False) and m.get("eligibility") in _BIF_STATUS:
            p.status = _BIF_STATUS[m["eligibility"]]
            p._status_set = True
        if not getattr(p, "_treatment_set", False) and m.get("gst_source") in _BIF_TREAT and m["gst_source"] != "regular":
            p.treatment = _BIF_TREAT[m["gst_source"]]
            p._treatment_set = True
    # 3. HSN / SAC
    if not nature_set and txn.hsn:
        codes = [h.strip() for h in txn.hsn.split(",") if h.strip()]
        if codes and all(c.startswith("99") for c in codes):
            p.nature, nature_set, p.confidence = "services", True, "medium"
            reasons.append(f"SAC {codes[0]} is a service")
    # 4. words of the ledger / item / narration
    if not nature_set:
        text = f"{txn.ledger} {txn.description}".strip()
        sg = suggest(text, "", "", None) if text else None
        if sg is not None and sg.confidence != "low":
            p.nature = nature_from_bifurcation(sg.acct_class, sg.gst_class)
            nature_set = p.nature != "unclassified"
            p.confidence = "medium" if txn.ledger else "low"
            reasons.append(f"words '{sg.reason.split('…')[0].replace('name ', '').strip(chr(39))}…'")
            if not getattr(p, "_status_set", False) and sg.eligibility == "blocked":
                p.status, p._status_set = "blocked", True
                reasons.append("usually blocked under section 17(5) – check")
    if not nature_set:
        p.nature, p.confidence = "unclassified", "manual"
        reasons.append("not enough evidence – classify by hand")
    # treatment: only from the voucher's reverse-charge mark, the supplier's registration, or rules
    if not getattr(p, "_treatment_set", False):
        if txn.reverse_charge:
            p.treatment = "rcm_reg" if txn.gstin else "rcm_unreg"
            reasons.append("reverse charge marked on the voucher")
        elif txn.gstin:
            p.treatment = "fcm"
        else:
            p.treatment = "other"
            reasons.append("supplier without GSTIN – treatment to be decided (RCM is not assumed)")
            if p.confidence == "high":
                p.confidence = "medium"
    p.reason = "; ".join(reasons)[:400]
    return p
