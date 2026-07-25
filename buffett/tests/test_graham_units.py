"""Unit checks for Graham scoring edge cases locked on the rubric ticket."""

import pytest

from whale_engine.scorers.graham import (
    analyze_earnings_stability,
    analyze_financial_strength,
    analyze_valuation,
    compute_confidence,
    compute_signal,
)


def _period(net_income, shares=1000.0, period_end="2026-04-30", **balance):
    return {
        "period_end": period_end,
        "ttm": {"net_income": net_income},
        "balance": {"outstanding_shares": shares, **balance},
    }


def test_eps_endpoint_growth_is_latest_vs_oldest():
    """Ordering is explicit (reference defect: it never pins which end is
    which): periods are most-recent-first, so growth = eps[0] > eps[-1]."""
    periods = [_period(50.0), _period(30.0), _period(10.0)]  # newest first, growing
    result = analyze_earnings_stability(periods, [])
    assert result["score"] == 4  # +3 all positive, +1 endpoint growth
    shrinking = list(reversed(periods))
    assert analyze_earnings_stability(shrinking, [])["score"] == 3  # growth point lost


def test_eps_share_count_outlier_excluded_and_flagged():
    """A pre-split cover-page share fact (10x off the median) must be dropped
    from the EPS series with a flag, not scored as an EPS collapse."""
    periods = [_period(100.0 - i) for i in range(9)]  # newest first, growing
    periods.append(_period(100.0, shares=100.0, period_end="2024-07-28"))  # 10x below
    flags = []
    result = analyze_earnings_stability(periods, flags)
    assert len(flags) == 1 and "2024-07-28" in flags[0] and "excluded" in flags[0]
    assert result["score"] == 4  # 9 clean periods: all positive, latest > oldest


def test_zero_liabilities_is_data_not_a_gap():
    """House convention (reference truthiness-gates): an exact 0.0 for total
    liabilities is the best case and must earn the +2, with no flag."""
    periods = [
        _period(
            10.0,
            current_assets=200.0,
            current_liabilities=50.0,
            total_assets=500.0,
            total_liabilities=0.0,
        )
    ]
    flags = []
    result = analyze_financial_strength(periods, flags)
    assert any("Debt ratio 0.00 < 0.50" in d for d in result["details"])
    assert not any("debt_ratio" in f for f in flags)


def test_dividends_absent_scores_zero_with_flag():
    periods = [
        _period(
            10.0,
            current_assets=200.0,
            current_liabilities=50.0,
            total_assets=500.0,
            total_liabilities=100.0,
        )
    ]
    flags = []
    result = analyze_financial_strength(periods, flags)
    assert result["score"] == 4  # current ratio +2, debt ratio +2, dividends 0
    assert flags == ["financial_strength: dividends absent, scored 0"]


def test_net_net_scores_four():
    """NCAV above the whole market cap is the classic deep-value +4."""
    periods = [
        _period(
            5.0,
            current_assets=2000.0,
            total_liabilities=500.0,
            shareholders_equity=1500.0,
        )
    ]
    result = analyze_valuation(periods, market_cap=1000.0, flags=[])
    assert result["ncav"] == 1500.0
    assert result["score"] >= 4


def test_partial_net_net_scores_two():
    """NCAV/share at two-thirds of price/share earns the moderate +2."""
    periods = [
        _period(
            0.0,  # EPS 0 -> no Graham Number points, isolates the net-net check
            current_assets=1200.0,
            total_liabilities=500.0,
            shareholders_equity=700.0,
        )
    ]
    result = analyze_valuation(periods, market_cap=1000.0, flags=[])
    assert result["ncav"] == 700.0  # NCAV/share 0.70 >= 2/3 of price/share 1.00
    assert result["score"] == 2


def test_negative_eps_graham_number_is_legitimate_zero_not_flagged():
    """EPS <= 0 means Graham walks away: a detail line, no missing-data flag."""
    periods = [
        _period(
            -10.0,
            current_assets=100.0,
            total_liabilities=500.0,
            shareholders_equity=200.0,
        )
    ]
    flags = []
    result = analyze_valuation(periods, market_cap=1000.0, flags=flags)
    assert result["graham_number"] is None
    assert result["score"] == 0
    assert flags == []
    assert any("needs both > 0" in d for d in result["details"])


@pytest.mark.parametrize(
    ("score_pct", "expected"),
    [
        (0.70, "bullish"),   # inclusive at the bullish bar
        (0.6999, "neutral"),
        (0.30, "bearish"),   # inclusive at the bearish bar
        (0.3001, "neutral"),
        (1.00, "bullish"),
        (0.00, "bearish"),
    ],
)
def test_signal_boundaries(score_pct, expected):
    assert compute_signal(score_pct) == expected


@pytest.mark.parametrize(
    ("score_pct", "expected"),
    [
        (0.70, 50),   # on a boundary: minimum confidence
        (0.30, 50),
        (0.50, 83),   # midpoint: 0.20 from either bar
        (1.00, 100),  # max attainable distance (0.30) saturates the range
        (0.00, 100),
    ],
)
def test_confidence_range(score_pct, expected):
    assert compute_confidence(score_pct) == expected
