import random
from datetime import date
from decimal import Decimal

import pytest

from fintax_gst.core.models import Category, DocType, ExceptionStatus, Flag, ReconSettings
from fintax_gst.engine import CancelToken, OperationCancelled, reconcile
from fintax_gst.engine.summary import dashboard, itc_at_risk, side_totals, supplier_summary

from .conftest import GSTIN_A, GSTIN_A2, GSTIN_B, rec


def run(books, g2b, **kw):
    return reconcile(books, g2b, **kw).lines


def only(lines):
    assert len(lines) == 1, [(ln.category, ln.books and ln.books.invoice_no, ln.gstr2b and ln.gstr2b.invoice_no)
                             for ln in lines]
    return lines[0]


def cats(lines):
    return sorted(ln.category.value for ln in lines)


def test_perfect_match():
    ln = only(run([rec("B", "INV-1")], [rec("G", "INV-1")]))
    assert ln.category == Category.FULLY_MATCHED
    assert ln.match_level == 1 and ln.confidence == 100
    assert ln.status == ExceptionStatus.NO_ACTION


def test_invoice_number_format_variation_is_matched_and_flagged():
    ln = only(run([rec("B", "INV/001/26")], [rec("G", "INV-001-26")]))
    assert ln.category == Category.NUMBER_VARIATION
    assert ln.books.invoice_no == "INV/001/26" and ln.gstr2b.invoice_no == "INV-001-26"  # originals preserved


def test_leading_zero_variation_matched_in_second_pass():
    ln = only(run([rec("B", "PP-7")], [rec("G", "PP-0007")]))
    assert ln.category == Category.NUMBER_VARIATION
    assert ln.confidence == 95


def test_materially_different_numbers_never_auto_matched():
    lines = run([rec("B", "INV-1001", taxable="5000", cgst="450", sgst="450")],
                [rec("G", "INV-2002", taxable="7000", cgst="630", sgst="630")])
    assert cats(lines) == sorted([Category.MISSING_IN_2B.value, Category.MISSING_IN_BOOKS.value])


@pytest.mark.parametrize("tolerance,days,expected", [
    (7, 3, Category.DATE_DIFFERENCE), (3, 3, Category.DATE_DIFFERENCE), (3, 5, Category.PROBABLE),
    (15, 12, Category.DATE_DIFFERENCE),
])
def test_date_tolerance_configurable(tolerance, days, expected):
    s = ReconSettings(date_tolerance_days=tolerance)
    ln = only(run([rec("B", "X-1", dt=date(2025, 4, 1))], [rec("G", "X-1", dt=date(2025, 4, 1 + days))], settings=s))
    assert ln.category == expected
    assert abs(ln.date_diff_days) == days
    if expected == Category.PROBABLE:
        assert Flag.DATE_BEYOND_TOLERANCE.value in ln.flags


def test_taxable_difference_only():
    ln = only(run([rec("B", "T-1", taxable="1000")], [rec("G", "T-1", taxable="1100")]))
    assert ln.category == Category.TAXABLE_DIFFERENCE
    assert ln.diff("taxable") == Decimal("-100")


def test_igst_difference():
    ln = only(run([rec("B", "I-1", igst="180", cgst="0", sgst="0", gstin=GSTIN_B)],
                  [rec("G", "I-1", igst="120", cgst="0", sgst="0", gstin=GSTIN_B)]))
    assert ln.category == Category.IGST_DIFFERENCE
    assert ln.diff("igst") == Decimal("60")


def test_cgst_sgst_difference_reported_per_component():
    ln = only(run([rec("B", "C-1", cgst="90", sgst="90")], [rec("G", "C-1", cgst="80", sgst="90")]))
    assert ln.category == Category.CGST_SGST_DIFFERENCE
    assert Flag.CGST_DIFF.value in ln.flags and Flag.SGST_DIFF.value not in ln.flags
    assert any("CGST differs" in r for r in ln.reasons)


def test_multiple_differences_listed_separately():
    ln = only(run([rec("B", "M-1", dt="2025-04-01", taxable="1000", cgst="90", sgst="90")],
                  [rec("G", "M-1", dt="2025-04-03", taxable="900", cgst="81", sgst="81")]))
    assert ln.category == Category.MULTIPLE_DIFFERENCES
    assert {Flag.DATE_DIFF.value, Flag.TAXABLE_DIFF.value, Flag.CGST_DIFF.value, Flag.SGST_DIFF.value} <= set(ln.flags)
    assert ln.match_level == 4


def test_rounding_within_tolerance_is_fully_matched_but_noted():
    ln = only(run([rec("B", "R-1", cgst="90.40", sgst="89.60")], [rec("G", "R-1", cgst="90.00", sgst="90.00")]))
    assert ln.category == Category.FULLY_MATCHED
    assert Flag.ROUNDING.value in ln.flags


def test_rounding_tolerance_is_configurable():
    s = ReconSettings(amount_tolerance=Decimal("0"))
    ln = only(run([rec("B", "R-1", cgst="90.40")], [rec("G", "R-1", cgst="90.00")], settings=s))
    assert ln.category == Category.CGST_SGST_DIFFERENCE


def test_duplicate_in_books_not_auto_matched():
    lines = run([rec("B", "D-1"), rec("B", "D-1")], [rec("G", "D-1")])
    assert cats(lines) == sorted([Category.DUPLICATE_IN_BOOKS.value] * 2 + [Category.PROBABLE.value])
    probable = [ln for ln in lines if ln.category == Category.PROBABLE][0]
    assert Flag.COUNTERPART_DUPLICATED.value in probable.flags and len(probable.candidates) == 2


def test_duplicate_in_gstr2b():
    lines = run([rec("B", "D-2")], [rec("G", "D-2"), rec("G", "D/2")])
    assert cats(lines).count(Category.DUPLICATE_IN_2B.value) == 2


def test_same_number_different_financial_year_is_not_duplicate():
    lines = run([rec("B", "1", dt="2025-04-05"), rec("B", "1", dt="2024-04-05", period="2024-04")],
                [rec("G", "1", dt="2025-04-05")])
    assert Category.DUPLICATE_IN_BOOKS.value not in cats(lines)
    assert Category.FULLY_MATCHED.value in cats(lines)


def test_multiple_invoices_with_equal_values_pair_by_number():
    books = [rec("B", f"EQ-{i}") for i in range(1, 6)]
    g2b = [rec("G", f"EQ-{i}") for i in (5, 3, 1, 4, 2)]
    lines = run(books, g2b)
    assert all(ln.category == Category.FULLY_MATCHED for ln in lines)
    assert all(ln.books.invoice_no == ln.gstr2b.invoice_no for ln in lines)


def test_gstin_mismatch_is_suggested_never_confirmed():
    ln = only(run([rec("B", "G-77", gstin=GSTIN_A2)], [rec("G", "G-77", gstin=GSTIN_A)]))
    assert ln.category == Category.PROBABLE
    assert Flag.GSTIN_MISMATCH.value in ln.flags
    assert "same PAN" in ln.reasons[0]


def test_credit_note_not_matched_against_invoice_with_same_number():
    lines = run([rec("B", "N-1", doc=DocType.INVOICE)], [rec("G", "N-1", doc=DocType.CREDIT_NOTE)])
    assert Category.FULLY_MATCHED.value not in cats(lines)
    assert all(not ln.is_paired for ln in lines)


def test_credit_note_sign_convention_and_difference_category():
    lines = run([rec("B", "CN-1", doc=DocType.CREDIT_NOTE, taxable="500", cgst="45", sgst="45")],
                [rec("G", "CN-1", doc=DocType.CREDIT_NOTE, taxable="600", cgst="54", sgst="54")])
    ln = only(lines)
    assert ln.category == Category.CDN_DIFFERENCE
    assert ln.side("books", "itc") == Decimal("-90")  # credit notes reduce ITC
    assert ln.diff("itc") == Decimal("18")
    # Supplier's note reverses 108 but books reverse only 90: 18 of ITC is over-claimed.
    assert itc_at_risk(ln) == Decimal("18")


def test_debit_note_matched_separately():
    ln = only(run([rec("B", "DN-1", doc=DocType.DEBIT_NOTE)], [rec("G", "DN-1", doc=DocType.DEBIT_NOTE)]))
    assert ln.category == Category.FULLY_MATCHED and ln.side("books", "itc") == Decimal("180")


def test_amendment_matched_via_original_number():
    g = rec("G", "AM-1A", is_amendment=True, original_invoice_no="AM-1", original_invoice_date=date(2025, 4, 10))
    ln = only(run([rec("B", "AM-1")], [g]))
    assert ln.category == Category.AMENDED and ln.is_paired
    assert Flag.AMENDMENT.value in ln.flags


def test_amendment_matched_on_revised_number_is_still_marked_amended():
    g = rec("G", "AM-2", is_amendment=True, original_invoice_no="AM-02X")
    assert only(run([rec("B", "AM-2")], [g])).category == Category.AMENDED


def test_fuzzy_clear_suggestion_with_confidence_and_reasons():
    ln = only(run([rec("B", "DOS-1189")], [rec("G", "DOS-1198")]))
    assert ln.category == Category.PROBABLE and ln.match_level == 5
    assert 80 <= ln.confidence < 100
    assert "similarity" in ln.reasons[0]
    assert ln.status == ExceptionStatus.PENDING_REVIEW


def test_ambiguous_fuzzy_candidates_are_not_paired():
    lines = run([rec("B", "ABC-1001")], [rec("G", "ABC-1002"), rec("G", "ABC-1003")])
    books_line = [ln for ln in lines if ln.books is not None][0]
    assert books_line.gstr2b is None
    assert books_line.category == Category.PROBABLE
    assert Flag.AMBIGUOUS.value in books_line.flags and len(books_line.candidates) == 2


def test_fuzzy_can_be_disabled():
    lines = run([rec("B", "DOS-1189")], [rec("G", "DOS-1198")], settings=ReconSettings(enable_fuzzy=False))
    assert cats(lines) == sorted([Category.MISSING_IN_2B.value, Category.MISSING_IN_BOOKS.value])


def test_previous_period_books_matched_and_kept_out_of_current_totals():
    prior = rec("B", "OLD-1", dt="2025-03-20", period="2025-03")
    current = rec("B", "NEW-1")
    res = reconcile([current], [rec("G", "OLD-1", dt="2025-03-20"), rec("G", "NEW-1")], prior_books=[prior],
                    period_start=date(2025, 4, 1))
    by_no = {ln.gstr2b.invoice_no: ln for ln in res.lines}
    assert by_no["OLD-1"].category == Category.PREVIOUS_PERIOD
    books, g2b, prior_t = side_totals(res.lines)
    assert books.count == 1 and prior_t.count == 1 and g2b.count == 2


def test_unmatched_prior_books_do_not_appear():
    res = reconcile([rec("B", "A")], [rec("G", "A")], prior_books=[rec("B", "Z", dt="2025-03-01", period="2025-03")])
    assert len(res.lines) == 1


def test_missing_in_books_dated_before_period_is_flagged():
    ln = only(run([], [rec("G", "OLD-9", dt="2025-02-10")], period_start=date(2025, 4, 1)))
    assert ln.category == Category.MISSING_IN_BOOKS
    assert Flag.DATED_BEFORE_PERIOD.value in ln.flags


def test_itc_not_available_in_2b_puts_itc_at_risk():
    ln = only(run([rec("B", "NA-1")], [rec("G", "NA-1", itc_availability="N", itc_reason="Section 16(4)")]))
    assert ln.category == Category.FULLY_MATCHED
    assert Flag.ITC_NOT_AVAILABLE.value in ln.flags
    assert itc_at_risk(ln) == Decimal("180")
    assert ln.status == ExceptionStatus.PENDING_REVIEW


def _mixed_dataset():
    books = [rec("B", f"INV-{i:03d}", taxable=str(1000 + i), cgst=str(90 + i), sgst=str(90 + i), uid=f"b{i}")
             for i in range(60)]
    g2b = [rec("G", f"INV/{i:03d}", taxable=str(1000 + i), cgst=str(90 + i), sgst=str(90 + i), uid=f"g{i}")
           for i in range(5, 65)]
    books += [rec("B", "DUP-1", uid="bd1"), rec("B", "DUP-1", uid="bd2"), rec("B", "X-0101", uid="bx")]
    g2b += [rec("G", "DUP-1", uid="gd"), rec("G", "X-0110", uid="gx"), rec("G", "INV-030", gstin=GSTIN_B, uid="gb")]
    return books, g2b


def _signature(lines):
    return [(ln.line_no, ln.category, ln.books and ln.books.uid, ln.gstr2b and ln.gstr2b.uid, tuple(ln.flags),
             ln.confidence) for ln in lines]


def test_repeatable_and_independent_of_input_order():
    books, g2b = _mixed_dataset()
    first = reconcile(books, g2b)
    rng = random.Random(42)
    for _ in range(3):
        b2, g2 = books[:], g2b[:]
        rng.shuffle(b2)
        rng.shuffle(g2)
        again = reconcile(b2, g2)
        assert _signature(again.lines) == _signature(first.lines)
        assert again.fingerprint == first.fingerprint


def test_every_record_exactly_once_and_totals_reconcile():
    books, g2b = _mixed_dataset()
    res = reconcile(books, g2b)
    seen = [r.uid for ln in res.lines for r in (ln.books, ln.gstr2b) if r is not None]
    assert sorted(seen) == sorted(r.uid for r in books + g2b)
    d = dashboard(res.lines)
    assert d["itc_as_per_books"] == sum(r.signed("itc") for r in books)
    assert d["itc_as_per_gstr2b"] == sum(r.signed("itc") for r in g2b)
    assert d["itc_difference"] == d["itc_as_per_books"] - d["itc_as_per_gstr2b"]
    sup = supplier_summary(res.lines)
    assert sum(r.books.itc for r in sup) == d["itc_as_per_books"]
    assert sum(r.gstr2b.itc for r in sup) == d["itc_as_per_gstr2b"]


def test_no_many_to_many_pairs():
    books = [rec("B", "SAME", dt="2025-04-01"), rec("B", "SAME", dt="2024-04-01", period="2024-04")]
    g2b = [rec("G", "SAME", dt="2025-04-02"), rec("G", "SAME", dt="2024-06-01")]
    res = reconcile(books, g2b)
    pairs = [(ln.books.uid, ln.gstr2b.uid) for ln in res.lines if ln.books and ln.gstr2b]
    assert len({b for b, _ in pairs}) == len(pairs) == len({g for _, g in pairs})


def test_cancellation_raises_before_any_result():
    token = CancelToken()
    token.cancel()
    with pytest.raises(OperationCancelled):
        reconcile([rec("B", "A")], [rec("G", "A")], cancel=token)


def test_duplicate_uids_rejected():
    with pytest.raises(ValueError):
        reconcile([rec("B", "A", uid="x")], [rec("G", "A", uid="x")])
