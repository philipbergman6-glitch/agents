"""Unit checks for scoring edge cases found while building the golden set."""

import pytest

from whale_engine.scorers.buffett import (
    analyze_book_value,
    analyze_fundamentals,
    calculate_intrinsic_value,
    compute_signal,
)


def _period(net_income):
    return {
        "ttm": {
            "net_income": net_income,
            "depreciation_and_amortization": 10.0,
            "capital_expenditure": -8.0,
            "revenue": 100.0,
        },
        "balance": {"current_assets": 50.0, "current_liabilities": 30.0},
    }


def test_negative_latest_earnings_does_not_crash():
    """Latest loss with positive oldest earnings used to produce a complex
    growth rate ((negative ratio) ** (1/years)) and crash the DCF. Growth now
    derives from annual periods; the same guard must hold there."""
    periods = [_period(-20.0), _period(5.0), _period(10.0), _period(15.0), _period(20.0)]
    result = calculate_intrinsic_value(periods, annual_periods=periods)
    assert isinstance(result["intrinsic_value"], float)
    # Fallback growth path: 3% headline, staged down per the locked DCF.
    assert result["dcf_stages"]["stage1_growth"] == pytest.approx(0.03)


def test_zero_debt_is_data_not_a_gap():
    """Intentional deviation from the reference, which truthiness-gates ratios
    and scores an exact D/E of 0.0 as 'unavailable'. Zero debt is the best
    case and must earn the +2, with no missing-data flag."""
    metrics = {
        "return_on_equity": 0.20,
        "debt_to_equity": 0.0,
        "operating_margin": 0.20,
        "current_ratio": 2.0,
    }
    flags = []
    result = analyze_fundamentals(metrics, flags)
    assert result["score"] == 7
    assert any("Debt/equity 0.00 < 0.5" in d for d in result["details"])
    assert flags == []


def _bv_period(period_end, equity, shares):
    return {
        "period_end": period_end,
        "balance": {"shareholders_equity": equity, "outstanding_shares": shares},
    }


def _quarterly_bv_periods(bvps_by_quarter, shares=1000.0):
    """Most-recent-first periods at real quarterly spacing, fixed share count."""
    ends = [
        "2026-04-26", "2026-01-25", "2025-10-26", "2025-07-27", "2025-04-27",
        "2025-01-26", "2024-10-27", "2024-07-28", "2024-04-28", "2024-01-28",
    ]
    return [
        _bv_period(end, bvps * shares, shares)
        for end, bvps in zip(ends, bvps_by_quarter)
    ]


def test_bvps_cagr_is_annualized_not_per_quarter():
    """years used to be len(periods)-1 over quarterly data, so a genuine
    15%/yr compounder (3.6%/quarter) scored 0 on the >15% CAGR check."""
    q = 1.15 ** 0.25  # 15%/yr as a quarterly growth factor
    bvps = [10.0 * q ** (9 - i) for i in range(10)]  # newest first
    flags = []
    result = analyze_book_value(_quarterly_bv_periods(bvps), flags)
    assert result["score"] == 5  # 9/9 grew (+3), CAGR ~15.2% > 15% (+2)
    assert any("CAGR 15." in d for d in result["details"])
    assert flags == []


def test_share_count_outlier_excluded_and_flagged():
    """A pre-split cover-page fact (10x off, NVDA 2024-07-28) must be dropped
    from BVPS with a flag, not silently scored."""
    q = 1.15 ** 0.25
    bvps = [10.0 * q ** (9 - i) for i in range(10)]
    periods = _quarterly_bv_periods(bvps)
    periods[7]["balance"]["outstanding_shares"] = 100.0  # 10x below the rest
    flags = []
    result = analyze_book_value(periods, flags)
    assert len(flags) == 1 and "2024-07-28" in flags[0] and "excluded" in flags[0]
    # 9 clean periods remain: still 8/8 grew (+3) and ~15%/yr CAGR (+2).
    assert result["score"] == 5
    assert any("8/8" in d for d in result["details"])


@pytest.mark.parametrize(
    ("score_pct", "mos", "expected"),
    [
        (0.70, 0.01, "bullish"),   # both bars met exactly
        (0.70, 0.0, "neutral"),    # MoS must be strictly positive
        (0.69, 0.50, "neutral"),   # score bar is inclusive at 0.70 only
        (0.44, 0.50, "bearish"),   # low quality alone is bearish
        (0.90, -0.30, "bearish"),  # deep overvaluation alone is bearish
        (0.60, -0.29, "neutral"),  # just inside both boundaries
    ],
)
def test_signal_boundaries(score_pct, mos, expected):
    assert compute_signal(score_pct, mos) == expected
