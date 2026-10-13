"""Greenblatt golden tickers: pinned snapshots with known verdicts.

Same two layers as the other scorers' goldens:
- semantic bands: a high-return name at a real earnings yield must read
  bullish while a thin-margin leveraged airline and a loss-maker read bearish — the intent,
  robust to deliberate rubric retuning;
- exact golden output: the full diagnosis must match the committed golden
  JSON, so *any* unintended scoring change fails loudly. Retuning the rubric
  means regenerating goldens on purpose:
  uv run python tests/make_golden_greenblatt.py

The walk-away roster has no golden files: a walk-away is a MissingDataError
with a reason, pinned here by message.
"""

import pytest

from whale_engine.scorers.greenblatt import MissingDataError, diagnose

from conftest import load_golden_greenblatt, load_snapshot

# ticker -> (expected signal, min score pct, max score pct)
GOLDEN_BANDS = {
    "LULU": ("bullish", 0.70, 1.00),  # ROC 71%, after-tax EY 18%: the formula's ideal
    "META": ("neutral", 0.45, 0.70),  # ROC 31% but after-tax EY 3.5%, peak_earnings flagged
    "JNJ": ("neutral", 0.30, 0.70),   # ROC 110% on thin tangible capital, EY 2.6%
    "KO": ("neutral", 0.30, 0.70),    # ROC 124%, EY 2.7%
    "V": ("neutral", 0.45, 0.70),     # asset-light: capital <= 0, full ROC marks, EY 2.9%
    "AAL": ("bearish", 0.00, 0.30),   # ROC 4.5%, EY 2.2%
    "F": ("bearish", 0.00, 0.30),     # negative TTM EBIT: 0 on both dimensions
}

# ticker -> substring of the walk-away reason
WALK_AWAYS = {
    "JPM": "walks away",  # SIC 6021: bank
}


@pytest.mark.parametrize("ticker", GOLDEN_BANDS)
def test_semantic_band(ticker):
    signal, lo, hi = GOLDEN_BANDS[ticker]
    result = diagnose(load_snapshot(ticker, whale="greenblatt"))
    assert result["signal"] == signal
    assert lo <= result["score"]["pct"] <= hi


@pytest.mark.parametrize("ticker", GOLDEN_BANDS)
def test_exact_golden_output(ticker):
    assert diagnose(load_snapshot(ticker, whale="greenblatt")) == load_golden_greenblatt(ticker)


@pytest.mark.parametrize("ticker", WALK_AWAYS)
def test_walk_away_by_reason(ticker):
    with pytest.raises(MissingDataError, match=WALK_AWAYS[ticker]):
        diagnose(load_snapshot(ticker, whale="greenblatt"))


def test_pre_field_snapshot_walks_away_with_refetch_message():
    """Every snapshot pinned before the net_fixed_assets field is unscorable
    for Greenblatt — by refetch message, never by a silent zero."""
    with pytest.raises(MissingDataError, match="refetch"):
        diagnose(load_snapshot("KO"))


def test_asset_light_name_scores_without_a_ratio():
    result = diagnose(load_snapshot("V", whale="greenblatt"))
    assert result["valuation"]["asset_light"] is True
    assert result["valuation"]["return_on_capital"] is None
    assert result["dimensions"]["return_on_capital"]["score"] == 5


def test_negative_ebit_name_is_bearish_not_a_walk_away():
    result = diagnose(load_snapshot("F", whale="greenblatt"))
    assert result["score"]["total"] == 0
    assert result["valuation"]["ebit_ttm"] < 0


def test_peak_earnings_context_is_narrated_not_scored():
    """META's TTM EBIT runs > 1.5x its 5-year average: flagged in the
    context block, invisible to the score."""
    result = diagnose(load_snapshot("META", whale="greenblatt"))
    assert result["earnings_context"]["peak_earnings"] is True
    assert result["score"]["total"] == 6


def test_rubric_version_pinned():
    assert diagnose(load_snapshot("LULU", whale="greenblatt"))["rubric_version"] == 2
