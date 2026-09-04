"""`whale portfolio TICKER…` — offline, deterministic, never fetches."""

import json

import pytest

from whale_engine import portfolio, prices
from whale_engine.cli import main

from test_portfolio import edgar_snapshot, price_snapshot, wiggle


@pytest.fixture
def pinned(tmp_path):
    """A two-name basket pinned on disk: price snapshots + EDGAR snapshots."""
    (tmp_path / "prices").mkdir()

    def pin(ticker, closes, sic="7372", price_date="2026-08-01", edgar_date="2026-07-27"):
        snapshot = price_snapshot(ticker, closes, fetched_at=price_date)
        (tmp_path / "prices" / f"{ticker}-{price_date}.json").write_text(
            json.dumps(snapshot), encoding="utf-8"
        )
        edgar = edgar_snapshot(ticker, sic)
        edgar["fetched_at"] = edgar_date
        (tmp_path / f"{ticker}-{edgar_date}.json").write_text(json.dumps(edgar), encoding="utf-8")

    pin("AAA", wiggle(200))
    pin("BBB", wiggle(200, phase=0.7), sic="6022")
    return tmp_path, pin


def run(tmp_path, *tickers, capsys=None):
    rc = main(["portfolio", *tickers, "--snapshots-dir", str(tmp_path)])
    return rc


def test_portfolio_prints_the_report_for_a_pinned_basket(pinned, capsys):
    tmp_path, _ = pinned
    assert run(tmp_path, "AAA", "BBB") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["portfolio_methodology_version"] == portfolio.METHODOLOGY_VERSION
    assert [b["ticker"] for b in report["basket"]] == ["AAA", "BBB"]
    assert report["correlation"]["matrix"]["AAA|BBB"] is not None
    assert report["caveats"] == [portfolio.RESIDUAL_RISK_CAVEAT]


def test_portfolio_never_touches_the_network(pinned, capsys, monkeypatch):
    tmp_path, _ = pinned

    def boom(*args, **kwargs):
        raise AssertionError("portfolio must not fetch — it reads pinned snapshots")

    monkeypatch.setattr(prices, "_av_get_json", boom)
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    assert run(tmp_path, "AAA", "BBB") == 0


def test_portfolio_output_is_byte_identical_across_runs(pinned, capsys):
    tmp_path, _ = pinned
    run(tmp_path, "AAA", "BBB")
    first = capsys.readouterr().out
    run(tmp_path, "AAA", "BBB")
    assert capsys.readouterr().out == first


def test_lowercase_tickers_resolve_to_the_same_report(pinned, capsys):
    tmp_path, _ = pinned
    run(tmp_path, "AAA", "BBB")
    first = capsys.readouterr().out
    run(tmp_path, "aaa", "bbb")
    assert capsys.readouterr().out == first


def test_the_newest_pinned_price_snapshot_wins(pinned, capsys):
    tmp_path, pin = pinned
    pin("AAA", wiggle(200, amplitude=0.09), price_date="2026-08-08")
    run(tmp_path, "AAA", "BBB")
    report = json.loads(capsys.readouterr().out)
    dates = {s["ticker"]: s["snapshot_date"] for s in report["provenance"]["snapshots"]}
    assert dates == {"AAA": "2026-08-08", "BBB": "2026-08-01"}


def test_missing_price_snapshot_exits_non_zero_with_the_fix(pinned, capsys):
    tmp_path, _ = pinned
    assert run(tmp_path, "AAA", "CCC") == 1
    assert "whale prices CCC" in capsys.readouterr().err


def test_missing_edgar_snapshot_exits_non_zero(pinned, capsys, tmp_path):
    tmp, pin = pinned
    snapshot = price_snapshot("CCC", wiggle(200))
    (tmp / "prices" / "CCC-2026-08-01.json").write_text(json.dumps(snapshot), encoding="utf-8")
    assert run(tmp, "AAA", "CCC") == 1
    err = capsys.readouterr().err
    # Both routes named: a young name is a `--sector-only` fetch away,
    # not a dead end.
    assert "no EDGAR sector source" in err and "--sector-only" in err


def test_single_ticker_basket_exits_non_zero(pinned, capsys):
    tmp_path, _ = pinned
    assert run(tmp_path, "AAA") == 1
    assert "2-15" in capsys.readouterr().err


def test_stale_price_schema_is_rejected_rather_than_read(pinned, capsys):
    tmp_path, _ = pinned
    path = tmp_path / "prices" / "AAA-2026-08-01.json"
    snapshot = json.loads(path.read_text())
    snapshot["schema_version"] = 0
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    assert run(tmp_path, "AAA", "BBB") == 1
    assert "schema_version" in capsys.readouterr().err
