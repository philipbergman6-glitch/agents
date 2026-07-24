"""Unit checks for scoring edge cases found while building the golden set."""

import pytest

from buffett_engine.score import calculate_intrinsic_value, compute_signal


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
    """Latest TTM loss with positive oldest earnings used to produce a complex
    growth rate ((negative ratio) ** (1/years)) and crash the DCF."""
    periods = [_period(-20.0), _period(5.0), _period(10.0), _period(15.0), _period(20.0)]
    result = calculate_intrinsic_value(periods)
    assert isinstance(result["intrinsic_value"], float)
    # Fallback growth path: 3% headline, staged down per the locked DCF.
    assert result["dcf_stages"]["stage1_growth"] == pytest.approx(0.03)


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
