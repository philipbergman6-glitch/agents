"""Rubric v3 pins (owner-signed B1-B4 + the rolling-over guard).

Each test pins one signed judgment change so a regression is a loud failure,
not a silent verdict drift — same pattern as test_truth_in_scoring.py.
"""

import pytest

from whale_engine.scorers.buffett import (
    _affected_dimensions,
    _rolling_over,
    _trend_windows,
    analyze_fundamentals,
    analyze_moat,
    analyze_pricing_power,
    calculate_intrinsic_value,
)


# --- B2: quality-aware confidence -----------------------------------------


def test_affected_dimensions_counts_warns_and_absences_not_bookkeeping():
    dimensions = {
        "fundamentals": {"score": 1},
        "moat": {"score": 0, "excluded": True},  # unscored: never penalized
    }
    dq_warnings = [
        {"dimensions_affected": ["fundamentals", "moat", "valuation"]},
    ]
    flags = [
        "fundamentals: return_on_equity missing, scored 0",
        "moat: fewer than 5 metric periods, excluded from denominator",
        "book_value: share counts renormalized (split factor x2)",  # bookkeeping
        "stale_data: revenue TTM window ends 140 days before the period end",
    ]
    affected = _affected_dimensions(dimensions, dq_warnings, flags)
    # moat is excluded (unscored); the split renorm is not degradation;
    # stale revenue maps to fundamentals + valuation via the field tables.
    assert affected == ["fundamentals", "valuation"]


# --- B1: adjacent trend windows -------------------------------------------


def test_trend_windows_are_adjacent_not_decade_endpoints():
    # Most-recent-first: recent 3y vs the 3y just before, decade tail ignored.
    values = [10.0, 11.0, 12.0, 20.0, 21.0, 22.0, 1.0, 1.0, 1.0, 1.0]
    recent, prior, w = _trend_windows(values)
    assert w == 3
    assert recent == pytest.approx(11.0)
    assert prior == pytest.approx(21.0)


def test_trend_windows_shrink_without_overlap_on_short_history():
    recent, prior, w = _trend_windows([3.0, 2.0, 1.0])
    assert w == 1
    assert (recent, prior) == (3.0, 2.0)


def _pp_period(gross_profit, revenue=100.0):
    return {"ttm": {"gross_profit": gross_profit, "revenue": revenue}}


def test_pricing_power_reads_prior_window_not_decade_floor():
    """BLDR symptom: decade-endpoint comparison scored '+3 expanding' through
    recent decline because the decade-ago margins were far lower."""
    # Recent 3y avg 30% vs prior 3y avg 34% -- declining under v3 even though
    # the decade endpoints (30% recent vs 20% oldest) read as expansion.
    margins = [30.0, 30.0, 30.0, 34.0, 34.0, 34.0, 20.0, 20.0, 20.0, 20.0]
    result = analyze_pricing_power([_pp_period(m) for m in margins], [])
    assert any("declining" in d for d in result["details"])


# --- B1 guard: rolling-over cap -------------------------------------------


def test_rolling_over_detects_two_declining_steps():
    assert _rolling_over([30.4, 32.8, 35.2, 34.1])
    assert not _rolling_over([32.8, 30.4, 35.2])  # latest step is up
    assert not _rolling_over([30.0, 31.0])  # too short to judge


def test_pricing_power_expansion_capped_when_rolling_over():
    """BLDR: recent-3y avg beats prior-3y avg, but the last two annual steps
    decline from a fresh peak -- the +3 is capped at +1."""
    margins = [30.4, 32.8, 35.2, 34.1, 29.4, 26.0, 27.2, 24.9, 24.6, 25.1]
    result = analyze_pricing_power([_pp_period(m) for m in margins], [])
    assert any("rolling over, capped" in d and "(+1)" in d for d in result["details"])
    # Trend contributes exactly 1 (margins ~30% so no average-level points).
    assert result["score"] == 1


def _moat_metrics(operating_margins):
    return [
        {
            "return_on_equity": 0.20,
            "operating_margin": om,
            "asset_turnover": 1.2,
        }
        for om in operating_margins
    ]


def test_moat_margin_check_denied_when_rolling_over():
    margins = [0.24, 0.26, 0.28, 0.22, 0.22, 0.22]  # recent >= prior but 2 down steps
    result = analyze_moat(_moat_metrics(margins), [])
    assert any("rolling over" in d for d in result["details"])
    assert not any("stable/improving" in d and "✓" in d for d in result["details"])


# --- B3: liabilities/equity fallback --------------------------------------


def test_leverage_fallback_scores_when_debt_unresolved():
    metrics = {
        "return_on_equity": 0.20,
        "debt_to_equity": None,
        "liabilities_to_equity": 0.8,
        "operating_margin": 0.20,
        "current_ratio": 2.0,
    }
    flags = []
    result = analyze_fundamentals(metrics, flags)
    assert any("Liabilities/equity 0.80 < 1.0" in d and "fallback" in d for d in result["details"])
    assert result["score"] == 7
    assert any("fallback at the 1.0 bar" in f for f in flags)


def test_leverage_fallback_fails_above_the_bar():
    metrics = {
        "return_on_equity": 0.20,
        "debt_to_equity": None,
        "liabilities_to_equity": 1.82,  # BLDR
        "operating_margin": 0.20,
        "current_ratio": 2.0,
    }
    result = analyze_fundamentals(metrics, [])
    assert any(">= 1.0" in d and "(+0" in d for d in result["details"])
    assert result["score"] == 5


# --- B4: negative growth carries through stage 2 --------------------------


def _dcf_period(net_income):
    return {
        "ttm": {
            "net_income": net_income,
            "depreciation_and_amortization": 10.0,
            "capital_expenditure": -8.0,
            "revenue": 100.0,
        },
        "balance": {"current_assets": 50.0, "current_liabilities": 30.0},
    }


def test_negative_stage1_growth_not_halved_in_stage2():
    # Declining earnings, both endpoints positive: raw CAGR is negative.
    periods = [_dcf_period(x) for x in [10.0, 12.0, 14.0, 17.0, 20.0]]
    result = calculate_intrinsic_value(periods, annual_periods=periods)
    stages = result["dcf_stages"]
    assert stages["stage1_growth"] < 0
    assert stages["stage2_growth"] == pytest.approx(stages["stage1_growth"])


def test_positive_growth_keeps_half_and_cap():
    periods = [_dcf_period(x) for x in [20.0, 17.0, 14.0, 12.0, 10.0]]
    stages = calculate_intrinsic_value(periods, annual_periods=periods)["dcf_stages"]
    assert stages["stage1_growth"] > 0
    assert stages["stage2_growth"] == pytest.approx(
        min(stages["stage1_growth"] * 0.5, 0.04)
    )
