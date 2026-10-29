"""GSTIN normalisation and validation (format + mod-36 check digit)."""
from __future__ import annotations

import re

GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PAN_PATTERN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

STATE_CODES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "25": "Daman and Diu", "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra",
    "28": "Andhra Pradesh (Old)", "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala",
    "33": "Tamil Nadu", "34": "Puducherry", "35": "Andaman and Nicobar Islands", "36": "Telangana",
    "37": "Andhra Pradesh", "38": "Ladakh", "96": "Foreign Country", "97": "Other Territory",
    "99": "Centre Jurisdiction",
}


def normalize_gstin(value) -> str:
    if value is None:
        return ""
    return re.sub(r"[\s\-./]", "", str(value)).upper()


def check_digit(first14: str) -> str:
    total = 0
    for index, char in enumerate(first14):
        product = _CHARSET.index(char) * (2 if index % 2 else 1)
        total += product // 36 + product % 36
    return _CHARSET[(36 - total % 36) % 36]


def validate_gstin(gstin: str) -> tuple[bool, str | None]:
    """Return (format_ok, problem). A checksum problem is reported but format_ok stays True
    so the caller can decide whether to warn or reject."""
    if not gstin:
        return False, "GSTIN is blank"
    if len(gstin) != 15:
        return False, f"GSTIN must have 15 characters (found {len(gstin)})"
    if not GSTIN_PATTERN.match(gstin):
        return False, "GSTIN format is invalid"
    if gstin[:2] not in STATE_CODES:
        return False, f"GSTIN state code {gstin[:2]} is not recognised"
    if check_digit(gstin[:14]) != gstin[14]:
        return True, "GSTIN check digit does not verify"
    return True, None


def is_valid_gstin(gstin: str) -> bool:
    ok, problem = validate_gstin(gstin)
    return ok and problem is None


def pan_of(gstin: str) -> str:
    return gstin[2:12] if len(gstin) >= 12 else ""


def state_of(gstin: str) -> str:
    return STATE_CODES.get(gstin[:2], "") if gstin else ""
