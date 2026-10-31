"""Desktop UI for Phase 20."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date  # noqa: E402
from decimal import Decimal as D  # noqa: E402

import pytest  # noqa: E402

pytest.importorskip("pytestqt")

from fintax_gst.services.auth import SETUP_SESSION  # noqa: E402

from .test_ui_phase3 import _window, messages  # noqa: E402,F401


def test_rcm_and_isd_tab(qtbot, db, tmp_path, messages):  # noqa: F811
    from fintax_gst.core.models import Source
    from fintax_gst.samples import CLIENT, gstin

    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    st = win.state
    c = st.clients.create(**CLIENT)
    st.set_client(st.clients.get(c.id))
    win.go("returns")
    tab = win.pages["returns"].rcm_tab
    e = tab.add_entry({"entry_date": date(2025, 4, 1), "supplier_name": "Shri Ram", "taxable": "10000", "rate": "18",
                       "bill_no": "", "description": "Office rent", "supplier_state": "27"})
    assert e is not None and tab.period.text() == "2025-04" and tab.model.rowCount() == 1
    assert "1,800.00" in tab.info.text() and "1 self-invoice" in tab.info.text()
    assert tab.self_invoices(str(tmp_path / "si.pdf"), first=1).exists()
    tab.table.selectRow(0)
    assert tab.remove_entry() and tab.model.rowCount() == 0
    # ISD
    isd = st.clients.create(**{**CLIENT, "gstin": gstin("27", "AABCS1234K", "2"), "name": "Shakti ISD"})
    st.clients.create(**{**CLIENT, "gstin": gstin("27", "AABCS1234K"), "name": "Shakti Pune"})
    st.clients.create(**{**CLIENT, "gstin": gstin("29", "AABCS1234K"), "name": "Shakti Blr", "state_code": "29"})
    (tmp_path / "b.csv").write_text("GSTIN,Supplier Name,Invoice No,Invoice Date,Taxable Value,CGST,SGST\n"
                                    f"{gstin('27', 'AABCM1234K')},Consultant,C-1,05-04-2025,10000,900,900\n")
    st.imports.import_file(isd.id, tmp_path / "b.csv", Source.BOOKS)
    st.set_client(st.clients.get(isd.id))
    assert tab.isd() is None and "No turnover" in tab.isd_info.text()
    shares = tab.isd({u.id: D(500) for u in tab.svc.isd_units(isd.id)})
    assert shares and tab.isd_grid.rowCount() == 2 and "1,800.00" in tab.isd_info.text()
    assert tab.export_isd(str(tmp_path / "isd.xlsx")).exists()
