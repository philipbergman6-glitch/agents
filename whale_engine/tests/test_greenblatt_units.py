"""Unit checks for Greenblatt scoring rules locked on the rubric v1 ticket."""

import pytest

from whale_engine.errors import MissingDataError
from whale_engine.scorers.greenblatt import (
    analyze_earnings_yield,
    analyze_return_on_capital,
    compute_confidence,
    compute_signal,
    diagnose,
    penalized_dimensions,
)

# ---------------------------------------------------------------------------
# return on capital: EBIT / (NWC + NFA), pre-tax


def test_return_on_capital_tiers():
    """>= 25% +5, >= 15% +3, > 0% +1, <= 0% +0 (ROC = EBIT / capital)."""
    assert analyze_return_on_capital(ebit=25.0, capital=100.0)["score"] == 5
    assert analyze_return_on_capital(ebit=15.0, capital=100.0)["score"] == 3
    assert analyze_return_on_capital(ebit=14.9, capital=100.0)["score"] == 1
    assert analyze_return_on_capital(ebit=0.0, capital=100.0)["score"] == 0
    assert analyze_return_on_capital(ebit=-5.0, capital=100.0)["score"] == 0


def test_return_on_capital_max_is_five():
    assert analyze_return_on_capital(ebit=25.0, capital=100.0)["max"] == 5


def test_negative_capital_with_positive_ebit_is_asset_light_five():
    """Capital <= 0 with EBIT > 0 is real data (the business runs on
    suppliers' money), not a gap: full marks, flagged asset_light."""
    result = analyze_return_on_capital(ebit=10.0, capital=-20.0)
    assert result["score"] == 5
    assert result["asset_light"] is True
    assert result["return_on_capital"] is None
    assert any("asset-light" in d for d in result["details"])


def test_negative_capital_with_nonpositive_ebit_scores_zero():
    result = analyze_return_on_capital(ebit=-10.0, capital=-20.0)
    assert result["score"] == 0
    assert result["asset_light"] is False
    result = analyze_return_on_capital(ebit=0.0, capital=0.0)
    assert result["score"] == 0


def test_negative_ebit_with_positive_capital_scores_zero_no_asset_light():
    result = analyze_return_on_capital(ebit=-10.0, capital=100.0)
    assert result["score"] == 0
    assert result["asset_light"] is False


# ---------------------------------------------------------------------------
# earnings yield: after-tax EBIT / EV, tiers as fractions of the 6% hurdle


def test_earnings_yield_tiers_after_tax():
    """EY = EBIT x (1 - 0.21) / EV. >= 6% +5, >= 4.5% +3, >= 3% +1, else 0.
    EBIT 100 on EV 1000 is 10% pre-tax, 7.9% after tax."""
    assert analyze_earnings_yield(ebit=100.0, enterprise_value=1000.0)["score"] == 5
    # 6% after tax exactly: 6 / 0.79 pre-tax on EV 100
    at_hurdle = analyze_earnings_yield(ebit=6.0 / 0.79, enterprise_value=100.0)
    assert at_hurdle["score"] == 5
    assert at_hurdle["earnings_yield_after_tax"] == 0.06
    assert analyze_earnings_yield(ebit=5.0 / 0.79, enterprise_value=100.0)["score"] == 3
    assert analyze_earnings_yield(ebit=3.0 / 0.79, enterprise_value=100.0)["score"] == 1
    assert analyze_earnings_yield(ebit=2.9 / 0.79, enterprise_value=100.0)["score"] == 0


def test_earnings_yield_max_is_five():
    assert analyze_earnings_yield(ebit=100.0, enterprise_value=1000.0)["max"] == 5


def test_nonpositive_enterprise_value_scores_zero_with_detail():
    """EV <= 0 (cash exceeds cap plus debt) is degenerate-but-real: 0 points,
    detail line, no yield, no flag (Lynch precedent)."""
    result = analyze_earnings_yield(ebit=100.0, enterprise_value=-50.0)
    assert result["score"] == 0
    assert result["earnings_yield_after_tax"] is None
    assert any("not meaningful" in d for d in result["details"])


def test_negative_ebit_scores_zero_with_detail():
    result = analyze_earnings_yield(ebit=-100.0, enterprise_value=1000.0)
    assert result["score"] == 0
    assert result["earnings_yield_after_tax"] is not None  # a real, negative yield
    assert any("EBIT" in d and "<= 0" in d for d in result["details"])


# ---------------------------------------------------------------------------
# signal: Graham thresholds, bullish gated on the hurdle (one direction)


def test_signal_thresholds():
    assert compute_signal(0.7, ey_after_tax=0.08) == "bullish"
    assert compute_signal(0.5, ey_after_tax=0.08) == "neutral"
    assert compute_signal(0.3, ey_after_tax=0.08) == "bearish"
    assert compute_signal(0.0, ey_after_tax=None) == "bearish"


def test_bullish_requires_after_tax_yield_at_hurdle():
    """A qualifying score whose after-tax EY sits under 6% caps at neutral;
    the gate never lifts a low score, and never pushes anything to bearish."""
    assert compute_signal(0.8, ey_after_tax=0.045) == "neutral"
    assert compute_signal(0.8, ey_after_tax=None) == "neutral"
    assert compute_signal(0.8, ey_after_tax=0.06) == "bullish"
    assert compute_signal(0.3, ey_after_tax=0.01) == "bearish"


# ---------------------------------------------------------------------------
# confidence: Graham distance rule minus 5 per WARN-affected dimension


def test_confidence_distance_rule():
    assert compute_confidence(1.0, affected_dimensions=[]) == 100
    assert compute_confidence(0.7, affected_dimensions=[]) == 50
    assert compute_confidence(0.5, affected_dimensions=[]) == 83
    assert compute_confidence(0.0, affected_dimensions=[]) == 100


def test_penalized_dimensions_skip_generic_stitched_warning():
    """Rubric v2: the generic ttm_stitched WARN is the normal state of EDGAR
    TTM data (it fires on operating_income for every pinned name and
    saturated the two-dimension penalty at -10). It keeps its
    dimensions_affected on the warning but no longer costs confidence; the
    escalations (stale window, stale-vs-price, restatement) and missing-input
    flags still do."""
    stitched = {"code": "ttm_stitched", "context": {"field": "operating_income"},
                "dimensions_affected": ["return_on_capital", "earnings_yield"]}
    stale = {"code": "ttm_stale_window", "context": {"field": "operating_income"},
             "dimensions_affected": ["return_on_capital", "earnings_yield"]}
    price_stale = {"code": "fundamentals_stale_vs_price", "context": {},
                   "dimensions_affected": ["return_on_capital", "earnings_yield"]}
    assert penalized_dimensions([stitched], []) == []
    assert penalized_dimensions([stale], []) == ["earnings_yield", "return_on_capital"]
    assert penalized_dimensions([price_stale], []) == ["earnings_yield", "return_on_capital"]
    assert penalized_dimensions([stitched], [
        "long_term_debt: missing, treated as 0 in enterprise value"]) == ["earnings_yield"]


def test_diagnose_generic_stitched_warning_costs_no_confidence():
    snap = _snapshot()
    snap["periods"][0]["tags_used"]["operating_income_warning"] = (
        "Some quarters were derived from YTD or annual facts.")
    result = diagnose(snap)
    codes = [w["code"] for w in result["data_quality"]["warnings"]]
    assert "ttm_stitched" in codes
    assert result["data_quality"]["confidence_penalty"] == 0
    assert result["data_quality"]["dimensions_affected"] == []
    assert result["confidence"] == diagnose(_snapshot())["confidence"]


def test_confidence_penalty_per_affected_dimension_floors_at_fifty():
    assert compute_confidence(1.0, affected_dimensions=["earnings_yield"]) == 95
    assert compute_confidence(
        1.0, affected_dimensions=["earnings_yield", "return_on_capital"]
    ) == 90
    assert compute_confidence(0.7, affected_dimensions=["earnings_yield"]) == 50


# ---------------------------------------------------------------------------
# diagnose: synthetic snapshots (post-NFA-field shape)


def _period(period_end, *, operating_income=100.0, current_assets=400.0,
            current_liabilities=200.0, cash=100.0, nfa=300.0, short_debt=50.0,
            long_debt=150.0, nfa_tag="PropertyPlantAndEquipmentNet@{end}",
            nfa_key=True):
    balance = {
        "outstanding_shares": 1000.0,
        "shareholders_equity": 500.0,
        "total_assets": 1000.0,
        "total_liabilities": 500.0,
        "current_assets": current_assets,
        "current_liabilities": current_liabilities,
        "cash_and_equivalents": cash,
        "short_term_debt": short_debt,
        "long_term_debt": long_debt,
    }
    tags = {}
    if nfa_key:
        balance["net_fixed_assets"] = nfa
        if nfa is not None:
            tags["net_fixed_assets"] = nfa_tag.format(end=period_end)
    return {
        "as_of_quarter": period_end,
        "period_end": period_end,
        "ttm": {
            "net_income": 70.0,
            "revenue": 1000.0,
            "operating_income": operating_income,
            "capital_expenditure": -20.0,
            "depreciation_and_amortization": 10.0,
        },
        "balance": balance,
        "tags_used": tags,
    }


def _snapshot(*, market_cap=1000.0, sic=5812, annual_ebit=(100.0, 100.0, 100.0,
              100.0, 100.0), **period_kw):
    """One quarterly period + five annual ones; defaults land ROC 25%
    (EBIT 100 / (NWC 150 + NFA 300)... see each test) and a clean EV."""
    snap = {
        "schema_version": 2,
        "ticker": "SYN",
        "fetched_at": "2026-08-01",
        "market_cap": market_cap,
        "market_cap_source": "test",
        "source": {"fundamentals": "test", "market_data": "test"},
        "periods": [_period("2026-06-30", **period_kw)],
        "annual_periods": [
            {**_period(f"{2025 - i}-12-31", **period_kw), "ttm": {
                **_period("x", **period_kw)["ttm"], "operating_income": e}}
            for i, e in enumerate(annual_ebit)
        ],
    }
    if sic is not None:
        snap["sic"] = sic
        snap["sic_description"] = "test"
    return snap


def test_diagnose_scores_a_clean_snapshot():
    """EBIT 100; NWC = (400-100) - (200-50) = 150; NFA 300 -> capital 450,
    ROC 22.2% (+3); EV = 1000 + 50 + 150 - 100 = 1100, after-tax EY
    79/1100 = 7.2% (+5): 8/10 bullish, EY clears the hurdle."""
    result = diagnose(_snapshot())
    assert result["rubric_version"] == 2
    assert result["score"] == {"total": 8, "max": 10, "max_possible": 10, "pct": 0.8}
    assert result["signal"] == "bullish"
    assert result["dimensions"]["return_on_capital"]["score"] == 3
    assert result["dimensions"]["earnings_yield"]["score"] == 5
    v = result["valuation"]
    assert v["net_working_capital"] == 150.0
    assert v["capital"] == 450.0
    assert v["enterprise_value"] == 1100.0
    assert v["net_fixed_assets_tag"] == "PropertyPlantAndEquipmentNet@2026-06-30"
    assert result["flags"] == []
    assert result["provenance"]["quarterly_period"] == "2026-06-30"


def test_bullish_score_under_hurdle_caps_at_neutral_with_pinned_line():
    """ROC 5 + EY 3 = 8/10 but after-tax EY in [4.5%, 6%): neutral, pinned
    detail line on the earnings_yield dimension."""
    # EBIT 150 on capital 450 -> 33% (+5); EV 1100 + extra cap -> tune EY to 5%
    # after-tax: 150*0.79 / EV = 0.05 -> EV = 2370 -> market cap 2270.
    result = diagnose(_snapshot(operating_income=150.0, market_cap=2270.0))
    assert result["score"]["total"] == 8
    assert result["signal"] == "neutral"
    assert (
        "Capped at neutral: after-tax earnings yield 5.0% is below the 6% bond hurdle."
        in result["dimensions"]["earnings_yield"]["details"]
    )


def test_financial_and_utility_sic_walk_away():
    for sic in (6021, 6199 + 300, 6798, 4911):
        with pytest.raises(MissingDataError, match="walks away"):
            diagnose(_snapshot(sic=sic))


def test_sic_6199_is_not_walked():
    diagnose(_snapshot(sic=6199))


def test_missing_sic_warns_and_scores():
    result = diagnose(_snapshot(sic=None))
    assert result["signal"] in ("bullish", "neutral", "bearish")
    assert any("sic_unavailable" in f for f in result["flags"])


def test_pre_field_snapshot_hard_fails_with_refetch():
    with pytest.raises(MissingDataError, match="refetch"):
        diagnose(_snapshot(nfa_key=False))


def test_unresolved_nfa_hard_fails():
    with pytest.raises(MissingDataError, match="net_fixed_assets"):
        diagnose(_snapshot(nfa=None))


def test_both_debt_fields_none_hard_fails():
    with pytest.raises(MissingDataError, match="debt"):
        diagnose(_snapshot(short_debt=None, long_debt=None))


def test_short_term_debt_none_alone_is_zero_with_warn_flag():
    result = diagnose(_snapshot(short_debt=None))
    assert any("short_term_debt" in f for f in result["flags"])
    # NWC no longer nets short-term debt out of current liabilities: 300 - 200
    assert result["valuation"]["net_working_capital"] == 100.0
    assert result["valuation"]["enterprise_value"] == 1050.0


@pytest.mark.parametrize(
    "field", ["operating_income", "current_assets", "current_liabilities",
              "cash_and_equivalents"],
)
def test_missing_mandatory_input_hard_fails(field):
    snap = _snapshot()
    section = "ttm" if field == "operating_income" else "balance"
    snap["periods"][0][section][field] = None
    with pytest.raises(MissingDataError, match=field):
        diagnose(snap)


def test_missing_market_cap_hard_fails():
    with pytest.raises(MissingDataError):
        diagnose(_snapshot(market_cap=None))


def test_negative_ebit_scores_zero_on_both_dimensions_no_walk_away():
    result = diagnose(_snapshot(operating_income=-50.0, annual_ebit=(-50.0,) * 5))
    assert result["score"]["total"] == 0
    assert result["signal"] == "bearish"


def test_peak_earnings_context_is_unscored():
    """TTM EBIT > 1.5x the 5-year annual average flags peak_earnings in the
    context block; the score is untouched."""
    peak = diagnose(_snapshot(operating_income=200.0, annual_ebit=(100.0,) * 5))
    flat = diagnose(_snapshot(operating_income=200.0, annual_ebit=(200.0,) * 5))
    assert peak["earnings_context"]["peak_earnings"] is True
    assert peak["earnings_context"]["ebit_5y_average"] == 100.0
    assert flat["earnings_context"]["peak_earnings"] is False
    assert peak["score"] == flat["score"]
