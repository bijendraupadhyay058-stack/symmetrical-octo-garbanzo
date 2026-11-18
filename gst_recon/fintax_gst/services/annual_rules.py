"""Year-specific reporting notes for the annual returns, recorded per financial year.

The program keeps every working (e.g. GSTR-9C Table 14 expense-wise ITC) whatever the year's instructions allow to be
left blank; this module only says what the user has recorded about the year's reporting relaxations, so the workings
can show it. Notifications are entered by the user (Settings / the working itself) – the program does not assume
them.
"""
from __future__ import annotations

import json

from ..db.database import Database
from ..db.models import AppSetting

KEY = "annual_relaxations"
#: notes recorded with this version, as stated by the user (editable; verify against the notification)
DEFAULTS = {
    "2025-26": "Notification No. 05/2026–Central Tax dated 26-10-2026 (as recorded by the user) extends the GSTR-9 / "
               "GSTR-9C reporting relaxations to FY 2025-26 onwards – Table 14 of GSTR-9C may be left blank in the "
               "return. The full expense-wise working is prepared and kept regardless.",
}
GENERIC = ("Table 14 of GSTR-9C (ITC on expenses): check the year's notification on whether it must be reported. The "
           "full expense-wise working is prepared and kept regardless.")


def notes(db: Database) -> dict[str, str]:
    with db.session() as s:
        row = s.get(AppSetting, KEY)
        saved = json.loads(row.value_json) if row else {}
    return {**DEFAULTS, **saved}


def table14_status(db: Database, fy: str) -> str:
    all_notes = notes(db)
    if fy in all_notes:
        return all_notes[fy]
    later = [y for y in all_notes if y <= fy and "onwards" in all_notes[y]]
    return all_notes[max(later)] if later else GENERIC


def set_note(db: Database, fy: str, text: str, user: str = "") -> None:
    from ..services.common import audit

    with db.session() as s:
        row = s.get(AppSetting, KEY)
        if row is None:
            row = AppSetting(key=KEY, value_json="{}")
            s.add(row)
        data = json.loads(row.value_json)
        if text.strip():
            data[fy] = text.strip()
        else:
            data.pop(fy, None)
        row.value_json = json.dumps(data)
        audit(s, "SETTING", "app_settings", KEY, {"fy": fy, "note": text}, user)
