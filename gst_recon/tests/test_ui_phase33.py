"""Desktop UI: Rule 37A reversal, sign-off, letters from note findings."""
import os
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("pytestqt")

from fintax_gst.samples import CLIENT  # noqa: E402
from fintax_gst.services.auth import Session  # noqa: E402
from fintax_gst.services.mailer import MailService  # noqa: E402

from .test_phase32 import SUP, SUP2, add_docs  # noqa: E402
from .test_ui_phase3 import _window, messages  # noqa: E402,F401


def test_rule37a_signoff_letters(qtbot, db, tmp_path, messages):  # noqa: F811
    win = _window(qtbot, db, tmp_path, Session("asha", "accountant"))
    st = win.state
    from fintax_gst.services.clients import ClientService

    c = ClientService(db).create(**CLIENT)
    add_docs(db, c.id, [
        ("GSTR2B", SUP, "INV", "A1", date(2024, 6, 3), "2024-06", 10000, 1800, ""),
        ("GSTR2B", SUP2, "INV", "B1", date(2024, 8, 3), "2024-08", 20000, 3600, ""),
        ("BOOKS", SUP, "CRN", "SCN-1", date(2024, 8, 1), "2024-08", 1000, 180, ""),
    ])
    st.clients.list()
    st.set_client(c)
    st.set_fy("2024-25")
    # Rule 37A
    win.go("rule37a")
    page = win.pages["rule37a"]
    page.reload()
    assert page.model.rowCount() == 2 and all(r[9].startswith("Filing status not known") for r in page.model.rows)
    page.select([next(i for i, r in enumerate(page.model.rows) if r[0] == SUP)])
    assert page.set_status(False) == 1
    row = next(r for r in page.model.rows if r[0] == SUP)
    assert row[9].startswith("Not filed") and "Table 4B(2)" in row[13]
    page.select([next(i for i, r in enumerate(page.model.rows) if r[0] == SUP)])
    assert page.record("reversed_in", "2025-10") == 1
    assert next(r for r in page.model.rows if r[0] == SUP)[11] == "2025-10"
    assert page.export(str(tmp_path / "r.xlsx"), open_file=False).exists()
    # letters from note findings
    win.go("docchecks")
    dc = win.pages["docchecks"]
    dc.reload()
    assert dc.letters(confirm=False) == 1 and any("1 draft(s) added to the Outbox" in m for m in messages)
    assert len(MailService(db).drafts("draft", c.id)) == 1
    # sign-off: preparer cannot review
    win.go("signoff")
    so = win.pages["signoff"]
    so.reload()
    r = next(i for i, x in enumerate(so.rows) if x.area == "rule37a")
    so.table.selectRow(r)
    assert so.prepare("checked")
    assert so.model.rows[r][1] == "Prepared – awaiting review" and so.model.rows[r][2] == "asha"
    so.table.selectRow(r)
    assert not so.review("") and any("cannot review" in m for m in messages)
    st.session = Session("partner", "manager")
    st.user = "partner"
    so.table.selectRow(r)
    assert so.review("ok")
    assert so.model.rows[r][1] == "Reviewed" and so.model.rows[r][5] == "partner"
    assert so.export(str(tmp_path / "s.xlsx"), open_file=False).exists()


def test_rule37a_in_gstr3b_draft_dialog(qtbot, db, tmp_path, messages):  # noqa: F811
    from fintax_gst.services.clients import ClientService
    from fintax_gst.services.rule37a import Rule37aService
    from fintax_gst.ui.dialogs.gstr3b_draft import Gstr3bDraftDialog

    win = _window(qtbot, db, tmp_path, Session("asha", "accountant"))
    st = win.state
    c = ClientService(db).create(**CLIENT)
    add_docs(db, c.id, [("GSTR2B", SUP, "INV", "A1", date(2024, 6, 3), "2024-06", 10000, 1800, "")])
    Rule37aService(db).set_status(SUP, "2024-06", False)
    Rule37aService(db).record(c.id, SUP, "2024-06", reversed_in="2025-10")
    st.set_client(c)
    dlg = Gstr3bDraftDialog(win, st, "2025-10")
    qtbot.addWidget(dlg)
    row = next(r for r in dlg.model.rows if r[0].startswith("4(B)(2)"))
    assert row[3] == 900 and row[4] == 900
    assert "Rule 37A: Rs. 1800" in dlg.notes.text()
    assert dlg.save_pdf(str(tmp_path / "3b.pdf"), open_file=False)
