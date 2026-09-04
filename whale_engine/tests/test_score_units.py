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
    """Intentional deviation from the upstream ai-hedge-fund heuristics, which
    truthiness-gate ratios and score an exact D/E of 0.0 as 'unavailable'. Zero debt is the best
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
        for end, bvps in zip(ends, bvps_by_quarter, strict=True)
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


def test_stale_share_count_repaired_and_flagged():
    """A pre-split cover-page fact (10x off, NVDA 2024-07-28) is renormalized
    back onto the surrounding basis with a flag (repair, not the
    old exclude-as-outlier), so the period stays in the BVPS series."""
    q = 1.15 ** 0.25
    bvps = [10.0 * q ** (9 - i) for i in range(10)]
    periods = _quarterly_bv_periods(bvps)
    periods[7]["balance"]["outstanding_shares"] = 100.0  # 10x below the rest
    flags = []
    result = analyze_book_value(periods, flags)
    assert len(flags) == 1 and "2024-07-28" in flags[0] and "repaired" in flags[0]
    # All 10 periods remain: 9/9 grew (+3) and ~15%/yr CAGR (+2).
    assert result["score"] == 5
    assert any("9/9" in d for d in result["details"])


def test_split_renormalization_restores_full_history():
    """NVDA shape: two real splits in the annual window must
    renormalize the older cohorts onto the current basis — the old 3x-median
    filter excluded the *correct* post-split years — keeping every period."""
    q = 1.15 ** 0.25
    bvps = [10.0 * q ** (9 - i) for i in range(10)]
    periods = _quarterly_bv_periods(bvps)
    # Raw counts: 3 newest at 1000, 3 middle at 100 (10:1 split), 4 oldest at
    # 25 (4:1 split before that). Equity stays bvps*1000, i.e. correct on the
    # current basis — renormalization must recover bvps exactly.
    for i, p in enumerate(periods):
        p["balance"]["outstanding_shares"] = 1000.0 if i < 3 else (100.0 if i < 6 else 25.0)
    flags = []
    result = analyze_book_value(periods, flags)
    assert len(flags) == 2
    assert all("renormalized" in f for f in flags)
    assert any("x10" in f for f in flags) and any("x4" in f for f in flags)
    # Full history intact on the renormalized basis: 9/9 grew, ~15%/yr CAGR.
    assert result["score"] == 5
    assert any("9/9" in d for d in result["details"])


def test_unexplained_share_jump_excludes_older_segment():
    """CAVA shape: an x80 jump snaps to no plausible split factor,
    so the older segment is excluded with a flag instead of renormalized."""
    q = 1.15 ** 0.25
    bvps = [10.0 * q ** (9 - i) for i in range(10)]
    periods = _quarterly_bv_periods(bvps)
    for p in periods[8:]:
        p["balance"]["outstanding_shares"] = 12.5  # x80 below the rest
    flags = []
    result = analyze_book_value(periods, flags)
    assert len(flags) == 1 and "no plausible split factor" in flags[0]
    assert "2024-04-28" in flags[0] and "2024-01-28" in flags[0]  # both excluded
    # 8 clean periods remain: 7/7 grew (+3), CAGR still ~15%/yr (+2).
    assert result["score"] == 5
    assert any("7/7" in d for d in result["details"])


def test_heavy_dilution_is_not_a_split():
    """AAL 2020 shape: a x1.45 count jump is crisis dilution, a real capital
    change — it must stay in the series unadjusted, with no flag."""
    periods = _quarterly_bv_periods([10.0] * 10)
    for p in periods[5:]:
        p["balance"]["outstanding_shares"] = 690.0  # x1.45 below the rest
    flags = []
    analyze_book_value(periods, flags)
    assert flags == []


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
