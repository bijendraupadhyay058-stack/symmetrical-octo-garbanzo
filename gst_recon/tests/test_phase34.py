"""Rule 37A reversal / re-availment in the GSTR-3B draft of the month recorded."""
from datetime import date
from decimal import Decimal as D

from fintax_gst.samples import CLIENT
from fintax_gst.services.clients import ClientService
from fintax_gst.services.gstr3b_draft import Gstr3bDraftService
from fintax_gst.services.rule37a import Rule37aService

from .test_phase32 import SUP, SUP2, add_docs


def test_rule37a_flows_into_gstr3b_draft(db):
    c = ClientService(db).create(**CLIENT)
    add_docs(db, c.id, [
        ("GSTR2B", SUP, "INV", "A1", date(2024, 6, 3), "2024-06", 10000, 1800, ""),
        ("GSTR2B", SUP2, "INV", "B1", date(2024, 8, 3), "2024-08", 20000, 3600, ""),
    ])
    r37 = Rule37aService(db)
    r37.set_status(SUP, "2024-06", False)
    r37.set_status(SUP2, "2024-08", True, date(2025, 10, 15))  # filed late
    draft = Gstr3bDraftService(db)
    before = draft.draft(c.id, "2025-10")
    assert before.t4["4B2"].total == 0 and not any("Rule 37A" in n for n in before.notes)
    r37.record(c.id, SUP, "2024-06", reversed_in="2025-10")
    r37.record(c.id, SUP2, "2024-08", reversed_in="2025-10")
    oct_ = draft.draft(c.id, "2025-10")
    assert oct_.t4["4B2"].cgst == D(900) + D(1800) and oct_.t4["4B2"].sgst == D(2700)
    assert oct_.t4["4C"].total == before.t4["4C"].total - D(5400)
    assert any("Rule 37A: Rs. 5400" in n and "2 supplier period(s)" in n for n in oct_.notes)
    # re-availment of the late filer in November
    r37.record(c.id, SUP2, "2024-08", reclaimed_in="2025-11")
    nov = draft.draft(c.id, "2025-11")
    assert nov.t4["4A5"].total >= D(3600) and nov.t4["4D1"].total == D(3600)
    assert any("re-availed in 4(A)(5)" in n for n in nov.notes)
    assert not any("Rule 37A" in n for n in draft.draft(c.id, "2025-12").notes)
    # re-availing a supplier that has not filed is warned about
    r37.record(c.id, SUP, "2024-06", reclaimed_in="2025-12")
    dec = draft.draft(c.id, "2025-12")
    assert any("not shown as filed" in n for n in dec.notes)
    m = r37.month(c.id, "2025-10")
    assert m["reverse"]["cgst"] == D(2700) and len(m["lines"]) == 2
