"""Sector-only EDGAR route so a young name does not kill a basket.

The portfolio layer needs exactly one EDGAR field — the SIC code — but the
only route to a snapshot was `whale fetch`, which hard-fails any company
without 10 distinct TTM windows. Two things had to become true:

1. a recent IPO in a client's basket must yield a report with a warning, not
   an error about fundamentals depth pointing at the wrong layer;
2. the `insufficient_history` path designed in methodology v1 must be reachable end
   to end by a real young name, not only by a synthetic fixture.

What must stay untouched (rubric-v2 precedent): whale scoring, the fetch depth
requirement, and the 10-TTM-window rule. A sector-only file is therefore not a
snapshot — it lives in its own directory, is marked `kind`, and `diagnose`
refuses it by name.
"""

import json
from datetime import date

import pytest
from test_portfolio import edgar_snapshot, price_snapshot, wiggle

import whale_engine.fetch as fetch
from whale_engine.cli import main
from whale_engine.errors import FetchError
from whale_engine.portfolio import PortfolioError, build_report, load_basket_snapshots


class FakeCompany:
    def __init__(self, cik=320193, name="StubHub Holdings, Inc.", sic="7389",
                 industry="Services-Computer Programming"):
        self.cik, self.name, self.sic, self.industry = cik, name, sic, industry


@pytest.fixture
def edgar_identity(monkeypatch):
    monkeypatch.setenv("EDGAR_IDENTITY", "Test Runner test@example.com")


@pytest.fixture
def fake_edgar(monkeypatch, edgar_identity):
    """Pin the EDGAR lookup and the version string: no network, no drift."""
    company = FakeCompany()
    monkeypatch.setattr(fetch, "_edgar_company", lambda ticker: company)
    monkeypatch.setattr(fetch, "_edgartools_version", lambda: "9.9.9")
    return company


# --- the artifact -----------------------------------------------------------


def test_sector_snapshot_carries_the_sic_code_and_nothing_financial(fake_edgar):
    snapshot = fetch.fetch_sector_snapshot("stub", today=date(2026, 8, 4))
    assert snapshot["kind"] == fetch.SECTOR_SNAPSHOT_KIND
    assert snapshot["schema_version"] == fetch.SECTOR_SCHEMA_VERSION
    assert snapshot["ticker"] == "STUB"
    assert snapshot["fetched_at"] == "2026-08-04"
    assert snapshot["sic"] == "7389"
    assert snapshot["sic_description"] == "Services-Computer Programming"
    assert snapshot["cik"] == "320193"
    assert snapshot["source"]["sector"] == "SEC EDGAR submissions via edgartools 9.9.9"
    assert snapshot["warnings"] == []
    # No fundamentals of any kind: nothing here could be mistaken for scorable.
    assert not {"periods", "annual_periods", "market_cap"} & set(snapshot)


def test_an_unusable_sic_is_a_warning_not_a_failed_fetch(fake_edgar, monkeypatch):
    """Same degradation rule as a full fetch, so the portfolio layer's
    `sector_unavailable` path behaves identically whichever route wrote it."""
    monkeypatch.setattr(fake_edgar, "sic", None)
    snapshot = fetch.fetch_sector_snapshot("STUB")
    assert snapshot["sic"] is None
    assert [w["code"] for w in snapshot["warnings"]] == ["sic_unavailable"]


def test_an_unknown_ticker_hard_fails(monkeypatch, edgar_identity):
    monkeypatch.setattr(fetch, "_edgar_company", lambda ticker: FakeCompany(cik=None))
    with pytest.raises(FetchError, match="EDGAR knows no company"):
        fetch.fetch_sector_snapshot("NOPE")


def test_identity_is_still_required(monkeypatch):
    monkeypatch.delenv("EDGAR_IDENTITY", raising=False)
    with pytest.raises(FetchError, match="EDGAR_IDENTITY"):
        fetch.fetch_sector_snapshot("STUB")


# --- the CLI ----------------------------------------------------------------


def test_fetch_sector_only_writes_to_sectors_never_the_snapshots_root(
    fake_edgar, tmp_path, capsys
):
    assert main(["fetch", "STUB", "--sector-only", "--snapshots-dir", str(tmp_path)]) == 0
    written = list((tmp_path / "sectors").glob("*.json"))
    assert len(written) == 1
    path = written[0]
    assert path.name.startswith("STUB-")
    assert json.loads(path.read_text())["kind"] == fetch.SECTOR_SNAPSHOT_KIND
    assert capsys.readouterr().out.strip() == str(path)
    # The snapshots root — where every scorer looks — stays empty.
    assert list(tmp_path.glob("*.json")) == []


def test_sector_only_refuses_a_market_cap_override(fake_edgar, tmp_path, capsys):
    rc = main(
        ["fetch", "STUB", "--sector-only", "--market-cap", "1000",
         "--snapshots-dir", str(tmp_path)]
    )
    assert rc == 2
    assert "--market-cap has no meaning with --sector-only" in capsys.readouterr().err


def test_diagnose_refuses_a_sector_only_file(fake_edgar, tmp_path, capsys):
    """It can only get here by being copied out of sectors/ — say so by name
    rather than dying inside a scorer on absent fundamentals."""
    snapshot = fetch.fetch_sector_snapshot("STUB")
    (tmp_path / "STUB-2026-08-04.json").write_text(json.dumps(snapshot), encoding="utf-8")
    rc = main(["diagnose", "STUB", "--whale", "buffett", "--snapshots-dir", str(tmp_path)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "sector-only snapshot" in err and "nothing here to score" in err


# --- the portfolio layer ----------------------------------------------------


def sector_snapshot(ticker, sic="7389", fetched_at="2026-08-04"):
    return {
        "schema_version": fetch.SECTOR_SCHEMA_VERSION,
        "kind": fetch.SECTOR_SNAPSHOT_KIND,
        "ticker": ticker,
        "fetched_at": fetched_at,
        "cik": "1949543",
        "company_name": f"{ticker} Inc.",
        "sic": sic,
        "sic_description": "Services-Computer Programming",
        "source": {"sector": "SEC EDGAR submissions via edgartools 9.9.9"},
        "warnings": [],
    }


@pytest.fixture
def pinned(tmp_path):
    """AAA fully fetched, YOUNG priced but with only a sector-only snapshot."""
    (tmp_path / "prices").mkdir()
    (tmp_path / "sectors").mkdir()

    def pin_prices(ticker, closes):
        (tmp_path / "prices" / f"{ticker}-2026-08-04.json").write_text(
            json.dumps(price_snapshot(ticker, closes, fetched_at="2026-08-04")),
            encoding="utf-8",
        )

    pin_prices("AAA", wiggle(200))
    pin_prices("YOUNG", wiggle(30, phase=0.7))
    (tmp_path / "AAA-2026-08-04.json").write_text(
        json.dumps(edgar_snapshot("AAA", "6022") | {"fetched_at": "2026-08-04"}),
        encoding="utf-8",
    )
    (tmp_path / "sectors" / "YOUNG-2026-08-04.json").write_text(
        json.dumps(sector_snapshot("YOUNG")), encoding="utf-8"
    )
    return tmp_path


def test_a_young_name_is_grouped_from_its_sector_only_snapshot(pinned):
    prices, edgar = load_basket_snapshots(["AAA", "YOUNG"], pinned)
    assert edgar["YOUNG"]["sic"] == "7389"
    report = build_report(["AAA", "YOUNG"], prices, edgar)
    groups = {g["sic2"]: g for g in report["sectors"]["groups"]}
    assert groups["73"]["tickers"] == ["YOUNG"] and groups["60"]["tickers"] == ["AAA"]
    # The sector-only name is a full member of the concentration check, not a
    # gap in it: in a two-name basket both halves clear the 40% threshold.
    assert report["sectors"]["flagged_groups"] == ["60", "73"]


def test_the_young_name_reaches_insufficient_history_instead_of_an_error(pinned):
    """The insufficient-history path, finally reachable by a name a client could actually
    own: weighted normally, null pairs, a first-class warning."""
    prices, edgar = load_basket_snapshots(["AAA", "YOUNG"], pinned)
    report = build_report(["AAA", "YOUNG"], prices, edgar)
    assert [b["weight"] for b in report["basket"]] == [0.5, 0.5]
    assert report["correlation"]["matrix"]["AAA|YOUNG"] is None
    warning = next(w for w in report["warnings"] if w["code"] == "insufficient_history")
    assert warning["ticker"] == "YOUNG"


def test_provenance_says_which_route_each_sic_came_from(pinned):
    prices, edgar = load_basket_snapshots(["AAA", "YOUNG"], pinned)
    report = build_report(["AAA", "YOUNG"], prices, edgar)
    assert report["provenance"]["edgar_snapshots"] == [
        {"ticker": "AAA", "snapshot_date": "2026-08-04", "source": "fetch"},
        {"ticker": "YOUNG", "snapshot_date": "2026-08-04", "source": "sector-only"},
    ]


def test_a_full_snapshot_wins_over_a_sector_only_one(pinned):
    """Same SIC field plus everything else: a properly fetched name must never
    silently read from the lightweight file."""
    (pinned / "sectors" / "AAA-2026-08-05.json").write_text(
        json.dumps(sector_snapshot("AAA", sic="9999", fetched_at="2026-08-05")),
        encoding="utf-8",
    )
    _, edgar = load_basket_snapshots(["AAA", "YOUNG"], pinned)
    assert edgar["AAA"]["sic"] == "6022"
    assert edgar["AAA"].get("kind") is None


def test_a_sector_only_file_in_the_snapshots_root_hard_fails(pinned):
    (pinned / "ZZZ-2026-08-04.json").write_text(
        json.dumps(sector_snapshot("ZZZ")), encoding="utf-8"
    )
    (pinned / "prices" / "ZZZ-2026-08-04.json").write_text(
        json.dumps(price_snapshot("ZZZ", wiggle(200), fetched_at="2026-08-04")),
        encoding="utf-8",
    )
    with pytest.raises(PortfolioError, match="where scorers look for fundamentals"):
        load_basket_snapshots(["AAA", "ZZZ"], pinned)


def test_a_sector_snapshot_of_the_wrong_schema_version_hard_fails(pinned):
    (pinned / "sectors" / "YOUNG-2026-08-05.json").write_text(
        json.dumps(sector_snapshot("YOUNG") | {"schema_version": 99}), encoding="utf-8"
    )
    with pytest.raises(PortfolioError, match="schema_version 99"):
        load_basket_snapshots(["AAA", "YOUNG"], pinned)


def test_a_name_with_neither_route_names_both_in_the_error(pinned):
    (pinned / "prices" / "NONE-2026-08-04.json").write_text(
        json.dumps(price_snapshot("NONE", wiggle(200), fetched_at="2026-08-04")),
        encoding="utf-8",
    )
    with pytest.raises(PortfolioError) as excinfo:
        load_basket_snapshots(["AAA", "NONE"], pinned)
    message = str(excinfo.value)
    assert "whale fetch TICKER" in message and "--sector-only" in message
