"""`whale prices TICKER…` — the CLI shape later portfolio tickets depend on."""

import json
from datetime import date
from pathlib import Path

import pytest

import whale_engine.prices as prices
from whale_engine.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 8, 4)
FAKE_KEY = "NOT-A-REAL-KEY-JUST-A-TEST"


@pytest.fixture(autouse=True)
def paused(monkeypatch):
    """Record burst-limit pauses instead of sleeping through them."""
    waits = []
    monkeypatch.setattr(prices, "_pause", waits.append)
    return waits


@pytest.fixture
def seam(monkeypatch):
    """Vendor seam + a pinned `today`, so the CLI never touches the network."""
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", FAKE_KEY)
    calls = []

    def fake(symbol, api_key):
        calls.append(symbol)
        return json.loads((FIXTURES / "av_weekly_adjusted_IBM.json").read_text())

    monkeypatch.setattr(prices, "_av_get_json", fake)
    monkeypatch.setattr(prices, "_today", lambda: TODAY)
    return calls


def test_prices_writes_a_snapshot_under_the_prices_dir(seam, tmp_path, capsys):
    rc = main(["prices", "IBM", "--snapshots-dir", str(tmp_path)])
    assert rc == 0
    path = tmp_path / "prices" / "IBM-2026-08-04.json"
    assert path.exists()
    snapshot = json.loads(path.read_text())
    assert snapshot["ticker"] == "IBM"
    assert snapshot["series"] == "TIME_SERIES_WEEKLY_ADJUSTED"
    out = capsys.readouterr().out
    assert str(path) in out
    assert FAKE_KEY not in out


def test_prices_reuses_a_fresh_snapshot_without_a_request(seam, tmp_path, capsys):
    main(["prices", "IBM", "--snapshots-dir", str(tmp_path)])
    rc = main(["prices", "IBM", "--snapshots-dir", str(tmp_path)])
    assert rc == 0
    assert seam == ["IBM"]  # second run spent no request
    assert "reused" in capsys.readouterr().out


def test_prices_accepts_a_multi_ticker_basket(seam, tmp_path, monkeypatch):
    def per_symbol(symbol, api_key):
        body = json.loads((FIXTURES / "av_weekly_adjusted_IBM.json").read_text())
        body["Meta Data"]["2. Symbol"] = symbol
        seam.append(symbol)
        return body

    monkeypatch.setattr(prices, "_av_get_json", per_symbol)
    rc = main(["prices", "IBM", "MSFT", "--snapshots-dir", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "prices" / "IBM-2026-08-04.json").exists()
    assert (tmp_path / "prices" / "MSFT-2026-08-04.json").exists()
    assert seam == ["IBM", "MSFT"]


def test_a_basket_is_paced_under_the_one_request_per_second_burst_limit(
    seam, tmp_path, monkeypatch, paused
):
    """Back-to-back requests earn an `Information` body from the free tier."""

    def per_symbol(symbol, api_key):
        body = json.loads((FIXTURES / "av_weekly_adjusted_IBM.json").read_text())
        body["Meta Data"]["2. Symbol"] = symbol
        seam.append(symbol)
        return body

    monkeypatch.setattr(prices, "_av_get_json", per_symbol)
    main(["prices", "IBM", "MSFT", "KO", "--snapshots-dir", str(tmp_path)])
    assert paused == [prices.BURST_PAUSE_SECONDS] * 2  # never before the first request


def test_reused_snapshots_cost_no_pause(seam, tmp_path, monkeypatch, paused):
    main(["prices", "IBM", "--snapshots-dir", str(tmp_path)])
    paused.clear()
    main(["prices", "IBM", "IBM", "--snapshots-dir", str(tmp_path)])
    assert paused == []


def test_prices_hard_fails_on_an_information_body(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", FAKE_KEY)
    monkeypatch.setattr(
        prices,
        "_av_get_json",
        lambda symbol, api_key: {"Information": "standard API rate limit is 25/day"},
    )
    rc = main(["prices", "IBM", "--snapshots-dir", str(tmp_path)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "25/day" in err
    assert FAKE_KEY not in err


def test_prices_hard_fails_without_a_key(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    rc = main(["prices", "IBM", "--snapshots-dir", str(tmp_path)])
    assert rc == 1
    assert "ALPHAVANTAGE_API_KEY" in capsys.readouterr().err


def test_stale_ok_reuses_an_old_snapshot(seam, tmp_path, monkeypatch, capsys):
    main(["prices", "IBM", "--snapshots-dir", str(tmp_path)])
    monkeypatch.setattr(prices, "_today", lambda: date(2026, 9, 1))

    def boom(symbol, api_key):
        raise AssertionError("must not fetch under --stale-ok")

    monkeypatch.setattr(prices, "_av_get_json", boom)
    rc = main(["prices", "IBM", "--snapshots-dir", str(tmp_path), "--stale-ok"])
    assert rc == 0
    assert "reused-stale" in capsys.readouterr().out


def test_force_refetches(seam, tmp_path):
    main(["prices", "IBM", "--snapshots-dir", str(tmp_path)])
    main(["prices", "IBM", "--snapshots-dir", str(tmp_path), "--force"])
    assert seam == ["IBM", "IBM"]
