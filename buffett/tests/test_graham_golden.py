"""Graham golden tickers: pinned snapshots with known verdicts.

Same two layers as the Buffett goldens:
- semantic bands: a fortress balance sheet must outscore a leveraged cyclical
  — the intent, robust to deliberate rubric retuning;
- exact golden output: the full diagnosis must match the committed golden JSON,
  so *any* unintended scoring change fails loudly. Retuning the rubric means
  regenerating goldens on purpose: uv run python tests/make_golden_graham.py

No golden is bullish: nothing in the snapshot set trades near NCAV or below
its Graham Number — a faithful Graham read of large caps in this market.
"""

import pytest

from whale_engine.scorers.graham import MissingDataError, diagnose

from conftest import load_golden_graham, load_snapshot

# ticker -> (expected signal, min quality pct, max quality pct)
GOLDEN_BANDS = {
    "NVDA": ("neutral", 0.45, 1.00),  # fortress balance sheet, stable EPS
    "KO": ("neutral", 0.30, 0.55),    # dividend blue chip, priced far above Graham Number
    "F": ("bearish", 0.00, 0.25),     # leveraged cyclical, negative TTM EPS
    "AAL": ("bearish", 0.00, 0.25),   # leveraged, negative shareholders' equity
}


@pytest.mark.parametrize("ticker", GOLDEN_BANDS)
def test_semantic_band(ticker):
    signal, lo, hi = GOLDEN_BANDS[ticker]
    result = diagnose(load_snapshot(ticker))
    assert result["signal"] == signal
    assert lo <= result["score"]["pct"] <= hi


@pytest.mark.parametrize("ticker", GOLDEN_BANDS)
def test_exact_golden_output(ticker):
    assert diagnose(load_snapshot(ticker)) == load_golden_graham(ticker)


def test_strong_balance_sheets_outscore_leveraged():
    scores = {t: diagnose(load_snapshot(t))["score"]["total"] for t in GOLDEN_BANDS}
    assert min(scores["NVDA"], scores["KO"]) > max(scores["F"], scores["AAL"])


def test_missing_mandatory_field_hard_fails():
    """Nulling a Graham-mandatory field below the 5-complete-period floor must
    raise, mirroring the Buffett missing-data policy."""
    snapshot = load_snapshot("KO")
    for period in snapshot["periods"][:6]:
        period["balance"]["current_assets"] = None
    with pytest.raises(MissingDataError):
        diagnose(snapshot)


def test_missing_market_cap_hard_fails():
    snapshot = load_snapshot("KO")
    snapshot["market_cap"] = None
    with pytest.raises(MissingDataError):
        diagnose(snapshot)
