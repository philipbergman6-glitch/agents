"""Golden tickers: pinned snapshots with known verdicts (chosen with the owner).

Two layers per ticker:
- semantic bands: a wide-moat compounder must score high, a leveraged cyclical
  low — the intent, robust to deliberate rubric retuning;
- exact golden output: the full diagnosis must match the committed golden JSON,
  so *any* unintended scoring change fails loudly. Retuning the rubric means
  regenerating goldens on purpose: uv run python tests/make_golden.py
"""

import pytest

from buffett_engine.score import MissingDataError, diagnose

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


@pytest.mark.parametrize("ticker", ["V", "MSFT"])
def test_unscorable_ticker_hard_fails(ticker):
    """V has no share-count data on EDGAR, MSFT no quarterly D&A before 2025.

    The engine must refuse loudly rather than score around the gap.
    """
    with pytest.raises(MissingDataError):
        diagnose(load_snapshot(ticker))
