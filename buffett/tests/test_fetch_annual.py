"""Unit tests for the deep-history annual path (offline, synthetic facts).

Histories mimic the companyfacts dataframes _concept_history returns: one row
per fact with concept/period_type/period_start/period_end/numeric_value/
filing_date. Fiscal years run Feb..Jan (LULU-style) to exercise the
non-calendar case.
"""

from datetime import date

import pandas as pd

from whale_engine.fetch import (
    _annual_at,
    _annual_fiscal_year_ends,
    _fetch_annual_periods,
    FetchError,
)

import pytest


def _history(rows):
    """rows: (period_type, start, end, value, filing_date)"""
    return pd.DataFrame(
        {
            "concept": "us-gaap:Whatever",
            "period_type": [r[0] for r in rows],
            "period_start": [r[1] for r in rows],
            "period_end": [r[2] for r in rows],
            "numeric_value": [r[3] for r in rows],
            "filing_date": [r[4] for r in rows],
        }
    )


FY24 = (date(2023, 1, 30), date(2024, 1, 28))
FY25 = (date(2024, 1, 29), date(2025, 2, 2))


def test_fiscal_year_ends_ignore_quarters_and_ytd():
    hist = _history(
        [
            ("duration", *FY24, 100.0, "2024-03-20"),
            ("duration", *FY25, 120.0, "2025-03-19"),
            ("duration", date(2024, 1, 29), date(2024, 4, 28), 25.0, "2024-06-05"),
            ("duration", date(2024, 1, 29), date(2024, 10, 27), 80.0, "2024-12-05"),
            ("instant", None, date(2025, 2, 2), 999.0, "2025-03-19"),
        ]
    )
    assert _annual_fiscal_year_ends(hist) == {FY24[1], FY25[1]}


def test_fiscal_year_ends_none_history():
    assert _annual_fiscal_year_ends(None) == set()


def test_annual_at_picks_matching_year():
    hist = _history(
        [
            ("duration", *FY24, 100.0, "2024-03-20"),
            ("duration", *FY25, 120.0, "2025-03-19"),
        ]
    )
    hit = _annual_at(hist, FY24[1])
    assert hit == (100.0, FY24[0], FY24[1])


def test_annual_at_restatement_latest_filing_wins():
    hist = _history(
        [
            ("duration", *FY24, 100.0, "2024-03-20"),
            ("duration", *FY24, 105.0, "2025-03-19"),  # restated in next 10-K
        ]
    )
    hit = _annual_at(hist, FY24[1])
    assert hit is not None
    assert hit[0] == 105.0


def test_annual_at_rejects_quarterly_and_far_ends():
    hist = _history(
        [
            ("duration", date(2024, 1, 29), date(2024, 4, 28), 25.0, "2024-06-05"),
        ]
    )
    assert _annual_at(hist, date(2024, 4, 28)) is None
    annual = _history([("duration", *FY24, 100.0, "2024-03-20")])
    assert _annual_at(annual, FY25[1]) is None


def _flow_histories(net_income_hist, revenue_hists):
    empties = {
        "gross_profit": [("GrossProfit", None)],
        "operating_income": [("OperatingIncomeLoss", None)],
        "capital_expenditure": [("PaymentsToAcquirePropertyPlantAndEquipment", None)],
        "depreciation_and_amortization": [("Depreciation", None)],
        "dividends_paid": [("PaymentsOfDividends", None)],
        "share_repurchase": [("PaymentsForRepurchaseOfCommonStock", None)],
        "share_issuance": [("ProceedsFromIssuanceOfCommonStock", None)],
    }
    return {
        "net_income": [("NetIncomeLoss", net_income_hist)],
        "revenue": revenue_hists,
        **empties,
    }


def _no_balances():
    balance_fields = [
        "shareholders_equity",
        "total_assets",
        "total_liabilities",
        "current_assets",
        "current_liabilities",
        "cash_and_equivalents",
        "long_term_debt",
        "outstanding_shares",
    ]
    return (
        {f: [("Tag", None)] for f in balance_fields},
        [("DebtCurrent", None), ("ShortTermBorrowings", None)],
        None,
        None,
    )


def test_fetch_annual_periods_tag_drift_resolves_per_year():
    """The old year filed only SalesRevenueNet; the new year only the ASC 606
    tag. Each fiscal year should resolve through its own tag."""
    ni = _history(
        [
            ("duration", *FY24, 100.0, "2024-03-20"),
            ("duration", *FY25, 120.0, "2025-03-19"),
        ]
    )
    rev_new = _history([("duration", *FY25, 1200.0, "2025-03-19")])
    rev_old = _history([("duration", *FY24, 1000.0, "2024-03-20")])
    flow = _flow_histories(
        ni,
        [
            ("RevenueFromContractWithCustomerExcludingAssessedTax", rev_new),
            ("SalesRevenueNet", rev_old),
        ],
    )
    balances, st_debt, liab_total, shares_proxy = _no_balances()

    annual = _fetch_annual_periods("TEST", flow, balances, st_debt, liab_total, shares_proxy)

    assert [p["period_end"] for p in annual] == ["2025-02-02", "2024-01-28"]
    assert annual[0]["ttm"]["revenue"] == 1200.0
    assert annual[1]["ttm"]["revenue"] == 1000.0
    assert annual[1]["tags_used"]["revenue"].startswith("SalesRevenueNet@")
    assert annual[0]["period_start"] == "2024-01-29"
    # unfiled fields stay None, and derived keys exist
    assert annual[0]["ttm"]["gross_profit"] is None
    assert annual[0]["ttm"]["issuance_or_purchase_of_equity_shares"] is None
    assert "dividends_and_other_cash_distributions" in annual[0]["ttm"]


def test_fetch_annual_periods_hard_fails_without_anchor():
    flow = _flow_histories(None, [("Revenues", None)])
    balances, st_debt, liab_total, shares_proxy = _no_balances()
    with pytest.raises(FetchError):
        _fetch_annual_periods("TEST", flow, balances, st_debt, liab_total, shares_proxy)
