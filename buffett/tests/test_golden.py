"""Golden tickers: pinned snapshots with known verdicts (chosen with the owner).

Two layers per ticker:
- semantic bands: a wide-moat compounder must score high, a leveraged cyclical
  low — the intent, robust to deliberate rubric retuning;
- exact golden output: the full diagnosis must match the committed golden JSON,
  so *any* unintended scoring change fails loudly. Retuning the rubric means
  regenerating goldens on purpose: uv run python tests/make_golden.py
"""

import pytest

from whale_engine.scorers.buffett import MissingDataError, diagnose

from conftest import load_golden, load_snapshot

# ticker -> (expected signal, min quality pct, max quality pct)
# No compounder reaches the 70% bullish bar on real data (strict consistency
# dimension), so "high" asserts >= 55% and "low" <= 30%.
GOLDEN_BANDS = {
    "KO": ("bearish", 0.55, 1.00),   # wide-moat compounder
    "MA": ("bearish", 0.55, 1.00),   # wide-moat compounder
    "GM": ("bearish", 0.00, 0.30),   # leveraged cyclical
    "F": ("bearish", 0.00, 0.30),    # leveraged cyclical, negative TTM earnings
}


@pytest.mark.parametrize("ticker", GOLDEN_BANDS)
def test_semantic_band(ticker):
    signal, lo, hi = GOLDEN_BANDS[ticker]
    result = diagnose(load_snapshot(ticker))
    assert result["signal"] == signal
    assert lo <= result["score"]["pct"] <= hi


@pytest.mark.parametrize("ticker", GOLDEN_BANDS)
def test_exact_golden_output(ticker):
    assert diagnose(load_snapshot(ticker)) == load_golden(ticker)


def test_compounders_outscore_cyclicals():
    scores = {t: diagnose(load_snapshot(t))["score"]["total"] for t in GOLDEN_BANDS}
    assert min(scores["KO"], scores["MA"]) > max(scores["GM"], scores["F"])


# field kept alive by the per-filing fallback -> provenance marker prefix
FALLBACK_TICKERS = {
    "MSFT": ("ttm", "depreciation_and_amortization"),
    "V": ("balance", "outstanding_shares"),
}


@pytest.mark.parametrize("ticker", FALLBACK_TICKERS)
def test_filing_fallback_ticker_scores(ticker):
    """companyfacts drops MSFT's extension-tagged D&A and V's class-dimensioned
    share counts; the per-filing fallback recovers both, so these snapshots
    must diagnose cleanly with fallback provenance recorded."""
    snapshot = load_snapshot(ticker)
    result = diagnose(snapshot)
    assert result["signal"] in ("bullish", "neutral", "bearish")
    section, field = FALLBACK_TICKERS[ticker]
    assert any(
        str(p["tags_used"].get(field, "")).startswith("filing-fallback:")
        for p in snapshot["periods"]
    )


def test_valuation_critical_gap_still_hard_fails():
    """Nulling a mandatory field below the 5-complete-period floor must raise:
    the fallback closes real gaps, it does not soften the refusal."""
    snapshot = load_snapshot("MSFT")
    for period in snapshot["periods"][:6]:
        period["ttm"]["depreciation_and_amortization"] = None
    with pytest.raises(MissingDataError):
        diagnose(snapshot)
