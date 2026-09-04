"""Unit checks for Lynch scoring edge cases locked on the rubric ticket."""

import pytest

from whale_engine.errors import MissingDataError
from whale_engine.scorers.lynch import (
    analyze_fundamentals,
    analyze_growth,
    analyze_valuation,
    compute_confidence,
    compute_signal,
    growth_band,
)


def _annual(net_income, revenue, shares=1000.0, period_end="2026-01-31"):
    return {
        "period_end": period_end,
        "ttm": {"net_income": net_income, "revenue": revenue},
        "balance": {"outstanding_shares": shares},
    }


def _window(eps_latest, eps_oldest, rev_latest=100.0, rev_oldest=100.0):
    """5 annual periods, most-recent-first, endpoints pinned (shares 1000)."""
    mid_ni = (eps_latest + eps_oldest) / 2 * 1000
    return [
        _annual(eps_latest * 1000, rev_latest, period_end="2026-01-31"),
        _annual(mid_ni, (rev_latest + rev_oldest) / 2, period_end="2025-01-31"),
        _annual(mid_ni, (rev_latest + rev_oldest) / 2, period_end="2024-01-31"),
        _annual(mid_ni, (rev_latest + rev_oldest) / 2, period_end="2023-01-31"),
        _annual(eps_oldest * 1000, rev_oldest, period_end="2022-01-31"),
    ]


def _quarter(net_income=10.0, revenue=100.0, operating_income=20.0,
             capital_expenditure=-5.0, dna=3.0, equity=100.0,
             short_debt=0.0, long_debt=None, shares=1000.0):
    return {
        "period_end": "2026-05-03",
        "ttm": {
            "net_income": net_income,
            "revenue": revenue,
            "operating_income": operating_income,
            "capital_expenditure": capital_expenditure,
            "depreciation_and_amortization": dna,
        },
        "balance": {
            "outstanding_shares": shares,
            "shareholders_equity": equity,
            "short_term_debt": short_debt,
            "long_term_debt": long_debt,
        },
    }


# ---------------------------------------------------------------------------
# growth: CAGR tiers and the Graham-walks-away rule


def test_cagr_tiers():
    """>=20% +3, >=10% +2, >=3% +1, else 0 — per sub-check, over 4 year-gaps."""
    result = analyze_growth(_window(2.1, 1.0, rev_latest=210.0, rev_oldest=100.0), [])
    assert result["score"] == 6  # 20.4% CAGR on both
    result = analyze_growth(_window(1.5, 1.0, rev_latest=150.0, rev_oldest=100.0), [])
    assert result["score"] == 4  # 10.7% CAGR on both
    result = analyze_growth(_window(1.14, 1.0, rev_latest=114.0, rev_oldest=100.0), [])
    assert result["score"] == 2  # 3.3% CAGR on both
    result = analyze_growth(_window(1.0, 1.0), [])
    assert result["score"] == 0  # flat


def test_negative_eps_endpoint_scores_zero_without_flag():
    """A loss year at an endpoint is real data, not a gap: the sub-check
    scores 0 with a detail line, no flag, no hard-fail."""
    flags = []
    result = analyze_growth(_window(1.0, -0.5, rev_latest=200.0, rev_oldest=100.0), flags)
    assert result["eps_cagr_5y"] is None
    assert result["score"] == 2  # revenue CAGR 18.9% still earns its +2
    assert any("EPS CAGR not meaningful" in d for d in result["details"])
    assert flags == []


def test_annual_split_jump_renormalized_and_flagged():
    """A pre-split annual share count (10x off) is renormalized onto the
    current basis with a flag, not scored as an EPS collapse."""
    window = _window(2.1, 1.0, rev_latest=210.0, rev_oldest=100.0)
    window[-1]["balance"]["outstanding_shares"] = 100.0  # pre-split basis
    window[-1]["ttm"]["net_income"] = 100.0  # EPS 1.0 pre-split = 0.1 current-basis
    flags = []
    result = analyze_growth(window, flags)
    assert result["score"] == 6  # renormalized EPS 0.1 -> 2.1 reads as fast growth
    assert len(flags) == 1 and "renormalized" in flags[0]


def test_unexplained_share_jump_hard_fails():
    """No plausible split factor -> the per-share history is untrustworthy;
    degenerate input aborts, unlike Graham's exclude-and-flag."""
    window = _window(2.0, 1.0)
    window[-1]["balance"]["outstanding_shares"] = 13.0  # x77: no split factor
    with pytest.raises(MissingDataError):
        analyze_growth(window, [])


# ---------------------------------------------------------------------------
# valuation: P/E + PEG (reference-verbatim tiers)


def test_pe_and_peg_tiers():
    # market_cap 1000, TTM NI 100 -> P/E 10 (+2); CAGR 25% -> PEG 0.4 (+3)
    result = analyze_valuation(_quarter(net_income=100.0), 1000.0, 0.25)
    assert result["score"] == 5 and result["peg"] == pytest.approx(0.4)
    # P/E 20 (+1); PEG 20/8 = 2.5 (+1)
    result = analyze_valuation(_quarter(net_income=100.0), 2000.0, 0.08)
    assert result["score"] == 2
    # P/E 40 (+0); PEG 40/10 = 4 (+0)
    result = analyze_valuation(_quarter(net_income=100.0), 4000.0, 0.10)
    assert result["score"] == 0


def test_peg_undefined_without_positive_earnings_or_growth():
    result = analyze_valuation(_quarter(net_income=-5.0), 1000.0, 0.25)
    assert result["pe_ttm"] is None and result["peg"] is None and result["score"] == 0
    result = analyze_valuation(_quarter(net_income=100.0), 1000.0, None)
    assert result["peg"] is None and result["score"] == 2  # P/E point stands
    result = analyze_valuation(_quarter(net_income=100.0), 1000.0, -0.05)
    assert result["peg"] is None


# ---------------------------------------------------------------------------
# fundamentals: D/E, margin, derived FCF


def test_negative_equity_is_data_not_a_gap():
    """AAL shape: negative equity makes D/E meaningless — scored 0 with a
    detail line, never a negative ratio earning the low-debt points and
    never the upstream ai-hedge-fund 1e-9 fallback."""
    result = analyze_fundamentals(_quarter(equity=-50.0, short_debt=40.0))
    assert result["debt_to_equity"] is None
    assert any("not meaningful" in d for d in result["details"])


def test_debt_tiers_and_derived_fcf():
    result = analyze_fundamentals(_quarter(short_debt=30.0, long_debt=10.0))
    assert result["debt_to_equity"] == pytest.approx(0.4)
    assert result["score"] == 4  # D/E +2, margin 20% +1, FCF 10+3-5=8 +1
    result = analyze_fundamentals(
        _quarter(short_debt=80.0, long_debt=0.0, operating_income=5.0,
                 capital_expenditure=-20.0)
    )
    assert result["score"] == 1  # D/E 0.8 +1, margin 5% +0, FCF -7 +0


# ---------------------------------------------------------------------------
# signal, confidence, band


def test_signal_is_garp_gated_both_directions():
    """Score alone never sets the signal (v2, owner review): bullish needs
    PEG defined and < 2 (mirroring Buffett's MoS-gated bullish), and
    bearish needs the GARP story to actually fail — PEG < 2 floors at
    neutral (the MA case)."""
    assert compute_signal(0.80, 1.5) == "bullish"
    assert compute_signal(0.80, 2.0) == "neutral"
    assert compute_signal(0.80, None) == "neutral"
    assert compute_signal(0.69, 0.5) == "neutral"
    assert compute_signal(0.45, 0.5) == "neutral"
    assert compute_signal(0.45, 2.0) == "bearish"
    assert compute_signal(0.40, 1.79) == "neutral"
    assert compute_signal(0.40, None) == "bearish"


def test_confidence_distance_from_boundary():
    assert compute_confidence(0.70) == 50  # on the bullish boundary
    assert compute_confidence(0.45) == 50  # on the bearish boundary
    assert compute_confidence(1.00) == 100  # saturates at 0.30 distance
    assert compute_confidence(2 / 15) == 100  # AAL: 0.317 below bearish


def test_growth_band_edges_match_scoring_tiers():
    assert growth_band(0.20) == "fast_grower"
    assert growth_band(0.10) == "stalwart"
    assert growth_band(0.0999) == "slow_grower"
    assert growth_band(-0.05) == "slow_grower"
    assert growth_band(None) == "not_meaningful"
