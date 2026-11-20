"""Bulk files for the e-invoice portal (IRP, schema INV-01 version 1.1) and the e-way bill portal (bulk JSON)
from the sales register.

* **e-invoice** – invoices, credit and debit notes to registered customers, SEZ units and exports (not B2C);
  one item per HSN line of the register (HSN is mandatory).
* **e-way bill** – outward supplies of goods (no HSN starting 99) with an invoice value above the threshold
  (₹50,000 by default); transport details are taken from what the user enters for the batch; a distance of 0
  lets the portal work it out from the PIN codes.

Seller and buyer addresses / PIN codes come from the client record and the party address book. A document
that misses something the portal requires is left out and listed with the reason; nothing is sent anywhere –
the user uploads the file on the portal.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from ..compliance.tax_checks import EXPORT, fits_rate, pos_code
from ..core.money import ZERO
from ..importers.payments import party_key
from .gstr1_json import SaleDoc

DOC_EINV = {"INV": "INV", "CRN": "CRN", "DBN": "DBN"}
PIN = re.compile(r"(?<!\d)(\d{6})(?!\d)")


@dataclass
class Party:
    name: str
    address: str
    place: str
    pin: str
    state_code: str
    gstin: str = ""
    distance_km: int = 0

    def missing(self) -> list[str]:
        return [label for label, v in (("address", self.address), ("place", self.place),
                                       ("PIN code", self.pin if PIN.fullmatch(self.pin or "") else ""),
                                       ("state", self.state_code)) if not v]


@dataclass
class Transport:
    transporter_id: str = ""
    transporter_name: str = ""
    vehicle_no: str = ""
    mode: int = 1  # 1 road, 2 rail, 3 air, 4 ship
    doc_no: str = ""


@dataclass
class FileIssue:
    doc: SaleDoc | None
    severity: str  # error (left out) / warning
    message: str


@dataclass
class BulkFile:
    payload: object
    count: int
    issues: list[FileIssue] = field(default_factory=list)


def _f(v: Decimal) -> float:
    return float(Decimal(v).quantize(Decimal("0.01")))


def _lines(d: SaleDoc) -> tuple[list[dict], str]:
    """Item lines with HSN, quantity and rate – or the reason they cannot be made."""
    raw = d.hsn_lines or []
    if not raw:
        return [], "no HSN in the sales register (HSN is required)"
    out = []
    for h in raw:
        vals = {k: Decimal(str(h.get(k) or 0)) for k in ("taxable", "igst", "cgst", "sgst", "cess", "qty")}
        rate = fits_rate(vals["taxable"], vals["igst"], vals["cgst"], vals["sgst"])
        if rate is None:
            return [], f"HSN {h.get('hsn')}: tax is not a GST rate of the taxable value"
        if vals["igst"] + vals["cgst"] + vals["sgst"] == 0:
            rate = ZERO
        hsn = re.sub(r"\D", "", str(h.get("hsn") or ""))
        if len(hsn) < 4:
            return [], f"HSN '{h.get('hsn')}' is too short"
        out.append({"hsn": hsn, "qty": vals["qty"], "unit": str(h.get("uqc") or "").upper() or "OTH", "rate": rate,
                    "taxable": vals["taxable"], "igst": vals["igst"], "cgst": vals["cgst"], "sgst": vals["sgst"],
                    "cess": vals["cess"], "service": hsn.startswith("99")})
    return out, ""


def _sup_type(d: SaleDoc) -> str:
    if re.search(r"sez", d.supply_type, re.I):
        return "SEZWP" if d.igst > 0 else "SEZWOP"
    if re.search(r"deemed", d.supply_type, re.I):
        return "DEXP"
    if EXPORT.search(d.supply_type or "") or (pos_code(d.place_of_supply) or "") in ("96", "97"):
        return "EXPWP" if d.igst > 0 else "EXPWOP"
    return "B2B"


def _addr(p: Party) -> dict:
    return {"Addr1": p.address[:100], "Loc": p.place[:50], "Pin": int(p.pin), "Stcd": p.state_code}


def build_einvoices(seller_gstin: str, seller: Party, docs: list[SaleDoc],
                    parties: dict[str, Party]) -> BulkFile:
    issues: list[FileIssue] = []
    if seller.missing():
        return BulkFile([], 0, [FileIssue(None, "error", "Your client's " + ", ".join(seller.missing()) +
                                          " is missing – enter it under 'Seller details'")])
    out = []
    for d in sorted(docs, key=lambda x: (x.date, x.number)):
        sup = _sup_type(d)
        export = sup.startswith("EXP")
        if not d.gstin and not export:
            continue  # B2C: no e-invoice
        items, problem = _lines(d)
        if problem:
            issues.append(FileIssue(d, "error", f"{problem} – left out"))
            continue
        if export:
            buyer = parties.get(d.gstin or party_key(d.name)) or Party(d.name or "Export customer", "Outside India",
                                                                     "Outside India", "999999", "96")
            pos = "96"
        else:
            buyer = parties.get(d.gstin)
            if buyer is None or buyer.missing():
                what = ", ".join(buyer.missing()) if buyer else "address and PIN code"
                issues.append(FileIssue(d, "error", f"customer {d.gstin}: {what} missing in the party address book "
                                                    "– left out"))
                continue
            pos = pos_code(d.place_of_supply) or d.gstin[:2]
        item_list = []
        for n, it in enumerate(items, start=1):
            unit_price = it["taxable"] / it["qty"] if it["qty"] else it["taxable"]
            item_list.append({
                "SlNo": str(n), "IsServc": "Y" if it["service"] else "N", "HsnCd": it["hsn"],
                "Qty": _f(it["qty"]) if it["qty"] else 1.0, "Unit": it["unit"] if not it["service"] else "OTH",
                "UnitPrice": _f(unit_price), "TotAmt": _f(it["taxable"]), "AssAmt": _f(it["taxable"]),
                "GstRt": float(it["rate"]), "IgstAmt": _f(it["igst"]), "CgstAmt": _f(it["cgst"]),
                "SgstAmt": _f(it["sgst"]), "CesRt": 0, "CesAmt": _f(it["cess"]),
                "TotItemVal": _f(it["taxable"] + it["igst"] + it["cgst"] + it["sgst"] + it["cess"])})
        doc = {"Version": "1.1",
               "TranDtls": {"TaxSch": "GST", "SupTyp": sup, "RegRev": "Y" if d.reverse_charge else "N",
                            "IgstOnIntra": "N"},
               "DocDtls": {"Typ": DOC_EINV[d.doc_type], "No": d.number[:16], "Dt": f"{d.date:%d/%m/%Y}"},
               "SellerDtls": {"Gstin": seller_gstin, "LglNm": seller.name[:100], **_addr(seller)},
               "BuyerDtls": {"Gstin": d.gstin if d.gstin else "URP", "LglNm": (buyer.name or d.name)[:100],
                             "Pos": pos, **_addr(buyer)},
               "ItemList": item_list,
               "ValDtls": {"AssVal": _f(d.taxable), "CgstVal": _f(d.cgst), "SgstVal": _f(d.sgst),
                           "IgstVal": _f(d.igst), "CesVal": _f(d.cess),
                           "TotInvVal": _f(d.value or d.taxable + d.igst + d.cgst + d.sgst + d.cess)}}
        if len(d.number) > 16:
            issues.append(FileIssue(d, "warning", "document number longer than 16 characters – shortened; check it"))
        if export:
            doc["ExpDtls"] = {"CntCode": "", "ForCur": "INR"}
            issues.append(FileIssue(d, "warning", "export: add the country, port and shipping bill if known"))
        out.append(doc)
    return BulkFile(out, len(out), issues)


def build_ewaybills(seller_gstin: str, seller: Party, docs: list[SaleDoc], parties: dict[str, Party],
                    transport: Transport, threshold: Decimal = Decimal("50000")) -> BulkFile:
    issues: list[FileIssue] = []
    if seller.missing():
        return BulkFile({"version": "1.0.0621", "billLists": []}, 0, [FileIssue(
            None, "error", "Your client's " + ", ".join(seller.missing()) + " is missing – enter it under 'Seller "
                                                                           "details'")])
    if not transport.vehicle_no and not transport.transporter_id:
        issues.append(FileIssue(None, "warning", "No vehicle number or transporter ID: only Part A can be generated – "
                                                 "add Part B on the portal before the goods move"))
    bills = []
    for d in sorted(docs, key=lambda x: (x.date, x.number)):
        if d.doc_type != "INV":
            continue
        value = d.value or d.taxable + d.igst + d.cgst + d.sgst + d.cess
        if value <= threshold:
            continue
        items, problem = _lines(d)
        if problem:
            issues.append(FileIssue(d, "error", f"{problem} – left out"))
            continue
        goods = [it for it in items if not it["service"]]
        if not goods:
            continue  # services: no e-way bill
        key = d.gstin or party_key(d.name)
        buyer = parties.get(key)
        export = _sup_type(d).startswith("EXP")
        if export and buyer is None:
            issues.append(FileIssue(d, "error", "export: enter the port / place of dispatch as the party's address – "
                                                "left out"))
            continue
        if buyer is None or buyer.missing():
            what = ", ".join(buyer.missing()) if buyer else "address and PIN code"
            issues.append(FileIssue(d, "error", f"{d.name or d.gstin}: {what} missing in the party address book – "
                                                "left out"))
            continue
        to_state = int(buyer.state_code) if buyer.state_code.isdigit() else 99
        main = max(goods, key=lambda it: it["taxable"])
        bills.append({
            "userGstin": seller_gstin, "supplyType": "O", "subSupplyType": 3 if export else 1, "subSupplyDesc": "",
            "docType": "INV", "docNo": d.number[:16], "docDate": f"{d.date:%d/%m/%Y}",
            "fromGstin": seller_gstin, "fromTrdName": seller.name[:100], "fromAddr1": seller.address[:120],
            "fromAddr2": "", "fromPlace": seller.place[:50], "fromPincode": int(seller.pin),
            "actFromStateCode": int(seller.state_code), "fromStateCode": int(seller.state_code),
            "toGstin": d.gstin or "URP", "toTrdName": (buyer.name or d.name)[:100], "toAddr1": buyer.address[:120],
            "toAddr2": "", "toPlace": buyer.place[:50], "toPincode": int(buyer.pin),
            "actToStateCode": to_state, "toStateCode": 99 if export else to_state, "transactionType": 1,
            "totalValue": _f(sum((it["taxable"] for it in goods), ZERO)),
            "cgstValue": _f(sum((it["cgst"] for it in goods), ZERO)),
            "sgstValue": _f(sum((it["sgst"] for it in goods), ZERO)),
            "igstValue": _f(sum((it["igst"] for it in goods), ZERO)),
            "cessValue": _f(sum((it["cess"] for it in goods), ZERO)), "cessNonAdvolValue": 0, "otherValue": 0,
            "totInvValue": _f(value), "transporterId": transport.transporter_id,
            "transporterName": transport.transporter_name, "transDocNo": transport.doc_no, "transMode": transport.mode,
            "transDistance": str(buyer.distance_km or 0), "transDocDate": "", "vehicleNo": transport.vehicle_no,
            "vehicleType": "R", "mainHsnCode": int(main["hsn"]),
            "itemList": [{"itemNo": n, "productName": it["hsn"], "productDesc": "", "hsnCode": int(it["hsn"]),
                          "quantity": _f(it["qty"]), "qtyUnit": it["unit"], "taxableAmount": _f(it["taxable"]),
                          "sgstRate": float(it["rate"]) / 2 if it["sgst"] else 0,
                          "cgstRate": float(it["rate"]) / 2 if it["cgst"] else 0,
                          "igstRate": float(it["rate"]) if it["igst"] else 0, "cessRate": 0, "cessNonAdvol": 0}
                         for n, it in enumerate(goods, start=1)]})
    return BulkFile({"version": "1.0.0621", "billLists": bills}, len(bills), issues)
