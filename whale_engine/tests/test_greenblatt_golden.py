"""Greenblatt golden tickers: pinned snapshots with known verdicts.

Same two layers as the other scorers' goldens:
- semantic bands: a high-return name at a real earnings yield must read
  bullish while a thin-margin leveraged airline reads bearish — the intent,
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
    "LULU": ("bullish", 0.70, 1.00),
    "META": ("neutral", 0.70, 1.00),   # 8/10 capped: after-tax EY under the 6% hurdle
    "JNJ": ("neutral", 0.30, 0.70),
    "KO": ("neutral", 0.30, 0.70),
    "AAL": ("bearish", 0.00, 0.30),
}

# ticker -> substring of the walk-away reason
WALK_AWAYS = {
    "JPM": "walks away",                 # SIC 6021: bank
    "F": "short_term_debt+long_term_debt",  # neither debt tag resolves: EV unknowable
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


def test_capped_name_carries_the_pinned_line():
    result = diagnose(load_snapshot("META", whale="greenblatt"))
    assert any(
        d.startswith("Capped at neutral: after-tax earnings yield")
        for d in result["dimensions"]["earnings_yield"]["details"]
    )


def test_rubric_version_pinned():
    assert diagnose(load_snapshot("LULU", whale="greenblatt"))["rubric_version"] == 1
