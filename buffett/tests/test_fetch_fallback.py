"""Unit tests for the per-filing XBRL fallback (offline, synthetic facts).

Shapes mirror MSFT's real filings: msft:DepreciationAmortizationAndOther is
extension-tagged (invisible to companyfacts), reported as fiscal-year annuals
in 10-Ks and YTD windows in 10-Qs, with prior-year comparatives.
"""

from datetime import date

from buffett_engine.fetch import _ttm_from_filing_durations

TAG = "DepreciationAmortizationAndOther"
CONCEPT = f"msft:{TAG}"


def _facts(entries):
    return {TAG: {(s, e): (v, CONCEPT) for s, e, v in entries}}


def test_direct_annual_window():
    facts = _facts([(date(2023, 7, 1), date(2024, 6, 30), 22_000.0)])
    hit = _ttm_from_filing_durations(facts, date(2024, 6, 30))
    assert hit is not None
    value, provenance = hit
    assert value == 22_000.0
    assert provenance == f"filing-fallback:{CONCEPT}@2023-07-01..2024-06-30"


def test_stitched_ttm_annual_plus_ytd_minus_prior_ytd():
    facts = _facts(
        [
            (date(2023, 7, 1), date(2024, 6, 30), 22_000.0),  # FY2024 annual
            (date(2024, 7, 1), date(2024, 12, 31), 13_000.0),  # H1 FY2025 YTD
            (date(2023, 7, 1), date(2023, 12, 31), 10_000.0),  # H1 FY2024 YTD
        ]
    )
    hit = _ttm_from_filing_durations(facts, date(2024, 12, 31))
    assert hit is not None
    value, provenance = hit
    assert value == 22_000.0 + 13_000.0 - 10_000.0
    assert provenance == (
        f"filing-fallback:{CONCEPT}@FY2024-06-30+YTD2024-12-31-YTD2023-12-31"
    )


def test_no_mixing_across_concepts():
    # Annual under one tag, YTDs under another: stitching must not combine them.
    facts = {
        "DepreciationDepletionAndAmortization": {
            (date(2023, 7, 1), date(2024, 6, 30)): (22_000.0, "us-gaap:DepreciationDepletionAndAmortization"),
        },
        TAG: {
            (date(2024, 7, 1), date(2024, 12, 31)): (13_000.0, CONCEPT),
            (date(2023, 7, 1), date(2023, 12, 31)): (10_000.0, CONCEPT),
        },
    }
    assert _ttm_from_filing_durations(facts, date(2024, 12, 31)) is None


def test_missing_prior_ytd_returns_none():
    facts = _facts(
        [
            (date(2023, 7, 1), date(2024, 6, 30), 22_000.0),
            (date(2024, 7, 1), date(2024, 12, 31), 13_000.0),
        ]
    )
    assert _ttm_from_filing_durations(facts, date(2024, 12, 31)) is None


def test_no_facts_for_window_returns_none():
    facts = _facts([(date(2023, 7, 1), date(2024, 6, 30), 22_000.0)])
    assert _ttm_from_filing_durations(facts, date(2025, 3, 31)) is None


def test_three_month_facts_do_not_masquerade_as_ttm():
    # Only quarterly facts ending at the window: no annual, nothing to stitch.
    facts = _facts(
        [
            (date(2024, 10, 1), date(2024, 12, 31), 7_000.0),
            (date(2023, 10, 1), date(2023, 12, 31), 6_000.0),
        ]
    )
    assert _ttm_from_filing_durations(facts, date(2024, 12, 31)) is None


def test_fiscal_week_calendar_tolerance():
    # 52/53-week filers end a few days off calendar quarter ends.
    facts = _facts([(date(2023, 7, 2), date(2024, 6, 28), 22_000.0)])
    hit = _ttm_from_filing_durations(facts, date(2024, 6, 30))
    assert hit is not None
    assert hit[0] == 22_000.0
