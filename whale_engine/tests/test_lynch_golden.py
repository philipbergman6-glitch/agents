"""Lynch golden tickers: pinned snapshots with known verdicts.

Same two layers as the Buffett and Graham goldens:
- semantic bands: a cheap fast grower must read bullish while a leveraged,
  loss-making airline reads bearish — the intent, robust to deliberate
  rubric retuning;
- exact golden output: the full diagnosis must match the committed golden
  JSON, so *any* unintended scoring change fails loudly. Retuning the rubric
  means regenerating goldens on purpose:
  uv run python tests/make_golden_lynch.py
"""

import pytest

from whale_engine.scorers.lynch import MissingDataError, diagnose

from conftest import load_golden_lynch, load_snapshot

# ticker -> (expected signal, min quality pct, max quality pct)
GOLDEN_BANDS = {
    "NVDA": ("bullish", 0.70, 1.00),  # fast grower (EPS CAGR 89%), PEG 0.35
    "LULU": ("bullish", 0.70, 1.00),  # stalwart at 9x earnings, PEG 0.58 — classic GARP
    "KO": ("bearish", 0.25, 0.45),    # slow grower at 26x, PEG 3.3 — growth priced away
    "CCL": ("neutral", 0.45, 0.70),   # cheap (P/E 12) but EPS history crosses zero, no PEG
    "AAL": ("bearish", 0.00, 0.25),   # negative equity, negative TTM EPS, FCF burn
}


@pytest.mark.parametrize("ticker", GOLDEN_BANDS)
def test_semantic_band(ticker):
    signal, lo, hi = GOLDEN_BANDS[ticker]
    result = diagnose(load_snapshot(ticker))
    assert result["signal"] == signal
    assert lo <= result["score"]["pct"] <= hi


@pytest.mark.parametrize("ticker", GOLDEN_BANDS)
def test_exact_golden_output(ticker):
    assert diagnose(load_snapshot(ticker)) == load_golden_lynch(ticker)


def test_garp_names_outscore_expensive_and_broken():
    scores = {t: diagnose(load_snapshot(t))["score"]["total"] for t in GOLDEN_BANDS}
    assert min(scores["NVDA"], scores["LULU"]) > max(scores["KO"], scores["AAL"])


def test_growth_band_labels():
    """Unscored context (#63): bands share the scoring-tier edges."""
    assert diagnose(load_snapshot("NVDA"))["growth_band"]["label"] == "fast_grower"
    assert diagnose(load_snapshot("LULU"))["growth_band"]["label"] == "stalwart"
    assert diagnose(load_snapshot("KO"))["growth_band"]["label"] == "slow_grower"
    assert diagnose(load_snapshot("AAL"))["growth_band"]["label"] == "not_meaningful"


def test_rubric_version_pinned():
    assert diagnose(load_snapshot("KO"))["rubric_version"] == 1


# ---------------------------------------------------------------------------
# hard-fail policy (#63: missing/degenerate rubric input aborts — the
# reference's zeros-and-continue is a bug, not behavior to port)


def test_missing_market_cap_hard_fails():
    snapshot = load_snapshot("KO")
    snapshot["market_cap"] = None
    with pytest.raises(MissingDataError):
        diagnose(snapshot)


def test_missing_annual_periods_hard_fails():
    snapshot = load_snapshot("KO")
    del snapshot["annual_periods"]
    with pytest.raises(MissingDataError):
        diagnose(snapshot)


def test_fewer_than_five_complete_annual_periods_hard_fails():
    snapshot = load_snapshot("KO")
    for period in snapshot["annual_periods"][4:]:
        period["ttm"]["revenue"] = None
    with pytest.raises(MissingDataError):
        diagnose(snapshot)


def test_missing_quarterly_rubric_input_hard_fails():
    snapshot = load_snapshot("KO")
    snapshot["periods"][0]["ttm"]["depreciation_and_amortization"] = None
    with pytest.raises(MissingDataError):
        diagnose(snapshot)


def test_no_resolved_debt_hard_fails():
    """GM resolves neither debt field under any known tag — real debt may be
    invisible, so Lynch refuses to score D/E rather than treat it as zero
    (Buffett/Graham degrade instead; Lynch's owner chose crash-over-silent)."""
    with pytest.raises(MissingDataError, match="debt"):
        diagnose(load_snapshot("GM"))


def test_one_resolved_debt_component_is_enough():
    """LULU files short_term_debt 0.0 and no long_term_debt tag: one resolved
    component keeps the debt sum usable (shared zero-if-one-resolved policy),
    and the exact 0.0 is data, not a gap."""
    result = diagnose(load_snapshot("LULU"))
    assert result["valuation"]["debt_to_equity"] == 0.0
