"""Unit tests for Cboe-derived market cap (market-cap sourcing). Offline:
the Cboe network seam (_cboe_get_json) is monkeypatched with the real response
shape observed live 2026-07-28.
"""

from datetime import date

import pandas as pd
import pytest

import whale_engine.fetch as fetch
from whale_engine.fetch import FetchError

TODAY = date(2026, 7, 28)


def _payload(close=336.91, prev_day_close=336.91, last_trade_time="2026-07-27T16:00:00"):
    # Real shape from cdn.cboe.com delayed_quotes (AAPL, observed 2026-07-28).
    return {
        "timestamp": "2026-07-28 06:13:32",
        "data": {
            "symbol": "AAPL",
            "current_price": 337.308,
            "close": close,
            "prev_day_close": prev_day_close,
            "last_trade_time": last_trade_time,
        },
        "symbol": "AAPL",
    }


# --- _fetch_cboe_close ------------------------------------------------------


def test_close_happy_path(monkeypatch):
    monkeypatch.setattr(fetch, "_cboe_get_json", lambda t: _payload())
    price, field, last_trade = fetch._fetch_cboe_close("AAPL", TODAY)
    assert price == 336.91
    assert field == "close"
    assert last_trade == "2026-07-27T16:00:00"


def test_missing_ticker_hard_fails_and_names_override(monkeypatch):
    def boom(_):
        raise OSError("HTTP Error 403: Forbidden")

    monkeypatch.setattr(fetch, "_cboe_get_json", boom)
    with pytest.raises(FetchError, match=r"--market-cap"):
        fetch._fetch_cboe_close("ZZZZQQ", TODAY)


def test_stale_quote_hard_fails(monkeypatch):
    monkeypatch.setattr(
        fetch, "_cboe_get_json", lambda t: _payload(last_trade_time="2026-07-20T16:00:00")
    )
    with pytest.raises(FetchError, match=r"8 calendar days old"):
        fetch._fetch_cboe_close("AAPL", TODAY)


def test_staleness_boundary_five_days_ok(monkeypatch):
    monkeypatch.setattr(
        fetch, "_cboe_get_json", lambda t: _payload(last_trade_time="2026-07-23T16:00:00")
    )
    price, _, _ = fetch._fetch_cboe_close("AAPL", TODAY)
    assert price == 336.91


def test_zero_close_falls_to_prev_day_close(monkeypatch):
    monkeypatch.setattr(
        fetch, "_cboe_get_json", lambda t: _payload(close=0.0, prev_day_close=101.5)
    )
    price, field, _ = fetch._fetch_cboe_close("AAPL", TODAY)
    assert price == 101.5
    assert field == "prev_day_close"


def test_no_usable_price_hard_fails(monkeypatch):
    monkeypatch.setattr(
        fetch, "_cboe_get_json", lambda t: _payload(close=0.0, prev_day_close=None)
    )
    with pytest.raises(FetchError, match=r"no usable close price"):
        fetch._fetch_cboe_close("AAPL", TODAY)


def test_unparseable_last_trade_time_hard_fails(monkeypatch):
    monkeypatch.setattr(
        fetch, "_cboe_get_json", lambda t: _payload(last_trade_time=None)
    )
    with pytest.raises(FetchError, match=r"last_trade_time"):
        fetch._fetch_cboe_close("AAPL", TODAY)


# --- manual override --------------------------------------------------------


def test_manual_override_valid():
    cap, source = fetch._manual_market_cap(5e9)
    assert cap == 5e9
    assert source == "manual:owner-supplied"


@pytest.mark.parametrize("bad", [0, -1.0, "abc", None])
def test_manual_override_invalid_hard_fails(bad):
    with pytest.raises(FetchError):
        fetch._manual_market_cap(bad)


def test_cli_passes_override_through(monkeypatch, tmp_path, capsys):
    """`fetch T --market-cap X` must reach fetch_snapshot as the override."""
    from whale_engine import cli

    captured = {}

    def fake_fetch_snapshot(ticker, market_cap_override=None):
        captured["ticker"] = ticker
        captured["override"] = market_cap_override
        return {
            "ticker": ticker.upper(),
            "fetched_at": "2026-07-28",
            "market_cap": market_cap_override,
        }

    monkeypatch.setattr(fetch, "fetch_snapshot", fake_fetch_snapshot)
    rc = cli.main(
        ["fetch", "KO", "--market-cap", "5e9", "--snapshots-dir", str(tmp_path)]
    )
    assert rc == 0
    assert captured == {"ticker": "KO", "override": 5e9}
    assert (tmp_path / "KO-2026-07-28.json").exists()


# --- freshest share count ---------------------------------------------------


def _history(rows):
    """rows: [(period_end, value, filing_date)] as instants."""
    return pd.DataFrame(
        {
            "period_type": "instant",
            "period_end": [r[0] for r in rows],
            "numeric_value": [r[1] for r in rows],
            "filing_date": [r[2] for r in rows],
        }
    )


def test_freshest_instant_picks_latest_filed():
    hist = _history(
        [
            ("2026-01-25", 24_304_000_000.0, "2026-02-26"),  # FY-end, stale
            ("2026-06-30", 24_100_000_000.0, "2026-07-15"),  # freshest cover page
        ]
    )
    value, end = fetch._freshest_instant(hist)
    assert value == 24_100_000_000.0
    assert end == "2026-06-30"


def test_freshest_share_count_prefers_dei_on_date_tie():
    dei = _history([("2026-06-30", 1_000.0, "2026-07-15")])
    gaap = _history([("2026-06-30", 999.0, "2026-07-20")])
    shares, source = fetch._freshest_share_count(
        "TST",
        [("CommonStockSharesOutstanding", gaap), (fetch.COVER_SHARES_TAG, dei)],
        cover_rows=[],
        shares_proxy_history=None,
        latest_window_end=date(2026, 6, 30),
    )
    assert shares == 1_000.0
    assert source == "dei:EntityCommonStockSharesOutstanding@2026-06-30"


def test_freshest_share_count_fresher_gaap_beats_dei():
    dei = _history([("2026-06-30", 1_000.0, "2026-07-15")])
    gaap = _history([("2026-07-10", 999.0, "2026-07-20")])
    shares, source = fetch._freshest_share_count(
        "TST",
        [("CommonStockSharesOutstanding", gaap), (fetch.COVER_SHARES_TAG, dei)],
        cover_rows=[],
        shares_proxy_history=None,
        latest_window_end=date(2026, 6, 30),
    )
    assert shares == 999.0
    assert source == "CommonStockSharesOutstanding@2026-07-10"


def test_freshest_share_count_stale_dei_loses_to_current_proxy():
    # The MA witness-gate shape: MA's dei companyfacts history topped out at a 2010
    # pre-split fact while the weighted-average proxy was current.
    dei = _history([("2010-10-27", 122_530_193.0, "2010-11-02")])
    proxy = _history([])
    proxy = pd.DataFrame(
        {
            "period_type": "duration",
            "period_end": ["2026-03-31"],
            "numeric_value": [891_000_000.0],
            "filing_date": ["2026-04-29"],
        }
    )
    shares, source = fetch._freshest_share_count(
        "MA",
        [(fetch.COVER_SHARES_TAG, dei)],
        cover_rows=[],
        shares_proxy_history=proxy,
        latest_window_end=date(2026, 3, 31),
    )
    assert shares == 891_000_000.0
    assert source == f"proxy:{fetch.SHARES_PROXY_TAG}@2026-03-31"


def test_freshest_share_count_uses_cover_rows_for_multiclass():
    cover_rows = [
        (date(2026, 1, 22), 1_815_172_471.0, 4, "2026-01-30"),
        (date(2025, 10, 20), 1_820_000_000.0, 4, "2025-11-15"),
    ]
    shares, source = fetch._freshest_share_count(
        "V",
        [(fetch.COVER_SHARES_TAG, None)],
        cover_rows=cover_rows,
        shares_proxy_history=None,
        latest_window_end=date(2026, 3, 31),
    )
    assert shares == 1_815_172_471.0
    assert "sum of 4 classes" in source


def test_freshest_share_count_no_source_hard_fails():
    with pytest.raises(FetchError, match=r"--market-cap"):
        fetch._freshest_share_count(
            "TST", [(fetch.COVER_SHARES_TAG, None)], [], None, date(2026, 6, 30)
        )


# --- yfinance cross-check (optional, never load-bearing) --------------------


def test_crosscheck_unavailable_warns_not_fails(monkeypatch):
    def boom(_):
        raise RuntimeError("yfinance broke again")

    monkeypatch.setattr(fetch, "_yfinance_reference_cap", boom)
    warnings: list = []
    check = fetch._yfinance_crosscheck("KO", 3.6e11, warnings)
    assert check is None
    assert len(warnings) == 1
    assert warnings[0]["severity"] == "WARN"
    assert warnings[0]["code"] == "yfinance-crosscheck-unavailable"


def test_crosscheck_available_records_deviation(monkeypatch):
    monkeypatch.setattr(
        fetch, "_yfinance_reference_cap", lambda t: (3.5e11, "yfinance:fast_info.market_cap")
    )
    warnings: list = []
    check = fetch._yfinance_crosscheck("KO", 3.6e11, warnings)
    assert warnings == []
    assert check["reference"] == 3.5e11
    assert check["derived"] == 3.6e11
    assert check["deviation_pct"] == pytest.approx((3.6e11 - 3.5e11) / 3.5e11 * 100)


# --- witness gate -----------------------------------------------------


def test_witness_gate_hard_fails_past_tolerance():
    check = {
        "derived": 6.891e10,
        "reference": 4.986e11,
        "reference_source": "yfinance:fast_info.market_cap",
        "deviation_pct": -86.2,
    }
    with pytest.raises(FetchError, match=r"-86\.2%.*--market-cap"):
        fetch._gate_market_cap_witness("MA", 6.891e10, "derived:cboe...", check)


def test_witness_gate_passes_within_tolerance():
    check = {
        "derived": 3.6e11,
        "reference": 3.5e11,
        "reference_source": "yfinance:fast_info.market_cap",
        "deviation_pct": 2.9,
    }
    fetch._gate_market_cap_witness("KO", 3.6e11, "derived:cboe...", check)


def test_witness_gate_skips_when_witness_unavailable():
    fetch._gate_market_cap_witness("KO", 3.6e11, "derived:cboe...", None)
