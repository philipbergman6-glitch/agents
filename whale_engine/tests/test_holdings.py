"""Offline tests for the 13F whale-holdings module (whale_engine.holdings).

Fixture snapshots are built through the real aggregate path (edgartools-shaped
DataFrames) and written to disk via the real serializer, so the offline
`holdings` scan is exercised end-to-end without network access.
"""

import json

import pandas as pd
import pytest

from whale_engine.holdings import (
    ROSTER_PATH,
    FundHolding,
    format_holdings_markdown,
    load_fund_snapshots,
    load_roster,
    scan_holdings,
    snapshot_filename,
)
from whale_engine.thirteenf import (
    ThirteenFError,
    aggregate_infotable,
    snapshot_from_dict,
    snapshot_to_dict,
)

COLS = ["Issuer", "Class", "Cusip", "Value", "PutCall", "SharesPrnAmount", "Ticker"]

BRKB = "084670702"
AAPL = "037833100"
NOTICK = "999999999"  # CUSIP that never resolved to a ticker


def _snap(rows, *, cik, period, filed, accession):
    return aggregate_infotable(
        pd.DataFrame(rows, columns=COLS),
        cik=cik, form="13F-HR", filing_date=filed,
        report_period=period, accession_no=accession,
    )


def _write(snap, directory):
    path = directory / snapshot_filename(snap.cik, snap.report_period)
    path.write_text(json.dumps(snapshot_to_dict(snap), indent=2, sort_keys=True) + "\n")
    return path


@pytest.fixture
def snapshots_dir(tmp_path):
    """Three funds on disk, mixed periods (Lindsell Train a quarter ahead).

    Berkshire (1067983): held BRK.B... uses AAPL: added 90->100. Also holds a
    no-ticker CUSIP. Giverny (1641864): exited AAPL in Q1. Lindsell Train
    (1484150): opened AAPL in its early Q2 filing.
    """
    d = tmp_path / "13f"
    d.mkdir()
    _write(_snap([
        ["APPLE INC", "COM", AAPL, 1000, "", 100, "AAPL"],
        ["MYSTERY CO", "COM", NOTICK, 500, "", 5, ""],
    ], cik=1067983, period="2026-03-31", filed="2026-05-15", accession="brk-q1"), d)
    _write(_snap([
        ["APPLE INC", "COM", AAPL, 900, "", 90, "AAPL"],
        ["MYSTERY CO", "COM", NOTICK, 400, "", 5, ""],
    ], cik=1067983, period="2025-12-31", filed="2026-02-17", accession="brk-q4"), d)
    _write(_snap([
        ["BERKSHIRE HATHAWAY INC", "CL B", BRKB, 300, "", 3, "BRKB"],
    ], cik=1641864, period="2026-03-31", filed="2026-05-15", accession="giv-q1"), d)
    _write(_snap([
        ["BERKSHIRE HATHAWAY INC", "CL B", BRKB, 250, "", 3, "BRKB"],
        ["APPLE INC", "COM", AAPL, 200, "", 20, "AAPL"],
    ], cik=1641864, period="2025-12-31", filed="2026-02-17", accession="giv-q4"), d)
    _write(_snap([
        ["APPLE INC", "COM", AAPL, 400, "", 40, "AAPL"],
        ["HEICO CORP", "COM", "422806208", 100, "", 10, "HEIA"],
    ], cik=1484150, period="2026-06-30", filed="2026-07-15", accession="lin-q2"), d)
    _write(_snap([
        ["HEICO CORP", "COM", "422806208", 100, "", 10, "HEIA"],
    ], cik=1484150, period="2026-03-31", filed="2026-05-14", accession="lin-q1"), d)
    return d


# ---------------------------------------------------------------------------
# Roster
# ---------------------------------------------------------------------------


def test_roster_loads_16_verified_whales():
    whales = load_roster()
    assert len(whales) == 16
    by_name = {w.name: w for w in whales}
    # Spot-check the entity-resolution decisions from the research doc.
    assert by_name["Berkshire Hathaway"].cik == 1067983
    assert by_name["Greenlight"].cik == 1489933  # DME, not the stale Greenlight CIK
    assert by_name["Giverny"].cik == 1641864  # Rochon, per owner confirmation path
    assert by_name["Leon Cooperman (Omega)"].cik == 898382  # personal CIK
    assert len({w.cik for w in whales}) == 16  # no duplicates


def test_roster_sibling_ciks_are_not_fetched():
    raw = json.loads(ROSTER_PATH.read_text())
    main_ciks = {e["cik"] for e in raw["whales"]}
    siblings = [s["cik"] for e in raw["whales"] for s in e.get("sibling_ciks", [])]
    assert 2026053 in siblings and 1868537 in siblings  # Pershing Inc, Fundsmith ISL
    assert not set(siblings) & main_ciks  # never double-counted


def test_roster_hard_fails_on_malformed(tmp_path):
    bad = tmp_path / "roster.json"
    bad.write_text(json.dumps({"whales": [{"name": "X", "cik": 1}]}))  # no filer
    with pytest.raises(ThirteenFError, match="missing 'filer'"):
        load_roster(bad)
    bad.write_text(json.dumps({"whales": []}))
    with pytest.raises(ThirteenFError, match="no 'whales' list"):
        load_roster(bad)
    with pytest.raises(ThirteenFError, match="not found"):
        load_roster(tmp_path / "missing.json")


# ---------------------------------------------------------------------------
# Snapshot serialization
# ---------------------------------------------------------------------------


def test_snapshot_round_trip():
    snap = _snap([
        ["APPLE INC", "COM", AAPL, 600, "", 60, "AAPL"],
        ["APPLE INC", "COM", AAPL, 400, "", 40, "AAPL"],  # aggregates by CUSIP
        ["SOME ISSUER", "COM", NOTICK, 500, "Put", 50, "X"],  # option row dropped
    ], cik=1067983, period="2026-03-31", filed="2026-05-15", accession="a")
    back = snapshot_from_dict(snapshot_to_dict(snap))
    assert back == snap
    assert back.option_rows == 1
    assert back.positions[AAPL].shares == 100


def test_snapshot_from_dict_hard_fails():
    with pytest.raises(ThirteenFError, match="schema"):
        snapshot_from_dict({"schema": "something-else"})
    with pytest.raises(ThirteenFError, match="missing keys"):
        snapshot_from_dict({"schema": "13f-snapshot/v1", "cik": 1})


def test_load_fund_snapshots_keeps_latest_two_newest_first(snapshots_dir, tmp_path):
    # Add a third, older Berkshire period; it must be ignored.
    _write(_snap([["APPLE INC", "COM", AAPL, 800, "", 80, "AAPL"]],
                 cik=1067983, period="2025-09-30", filed="2025-11-14",
                 accession="brk-q3"), snapshots_dir)
    snaps = load_fund_snapshots(1067983, snapshots_dir)
    assert [s.report_period for s in snaps] == ["2026-03-31", "2025-12-31"]


# ---------------------------------------------------------------------------
# holdings scan + report
# ---------------------------------------------------------------------------


def test_scan_classifies_across_funds_with_mixed_periods(snapshots_dir):
    holdings, absent, matched, label = scan_holdings("AAPL", snapshots_dir)
    assert matched == {AAPL}
    assert label == "APPLE INC (AAPL)"
    by_fund = {h.whale.name: h for h in holdings}
    assert by_fund["Berkshire Hathaway"].action == "added"  # 90 -> 100
    assert by_fund["Berkshire Hathaway"].weight == pytest.approx(1000 / 1500)
    assert by_fund["Giverny"].action == "exited"
    assert by_fund["Giverny"].shares == 0
    assert by_fund["Lindsell Train"].action == "opened"
    assert by_fund["Lindsell Train"].period == "2026-06-30"  # its own quarter, not Q1
    # 13 roster funds have no snapshots on disk -> listed as no-position
    assert len(absent) == 13
    # sorted by current value desc: Berkshire (1000) before Lindsell (400)
    assert [h.whale.name for h in holdings][:2] == ["Berkshire Hathaway", "Lindsell Train"]


def test_ticker_matching_ignores_dots_and_dashes(snapshots_dir):
    holdings, _, matched, _ = scan_holdings("BRK-B", snapshots_dir)
    assert matched == {BRKB}
    assert holdings[0].whale.name == "Giverny"
    assert holdings[0].action == "unchanged"  # 3 -> 3 shares; value moved, shares didn't


def test_cusip_flag_reaches_unresolved_tickers(snapshots_dir):
    with pytest.raises(ThirteenFError, match="not found"):
        scan_holdings("MYSTERY", snapshots_dir)
    holdings, _, matched, label = scan_holdings(None, snapshots_dir, cusip=NOTICK)
    assert matched == {NOTICK}
    assert label == "MYSTERY CO"
    assert holdings[0].whale.name == "Berkshire Hathaway"
    assert holdings[0].action == "unchanged"


def test_scan_hard_fails(snapshots_dir, tmp_path):
    with pytest.raises(ThirteenFError, match="not found in any whale"):
        scan_holdings("ZZZZ", snapshots_dir)
    with pytest.raises(ThirteenFError, match="fetch-13f"):
        scan_holdings("AAPL", tmp_path / "empty")
    with pytest.raises(ThirteenFError, match="ticker or --cusip"):
        scan_holdings(None, snapshots_dir)


def test_report_is_deterministic_and_carries_caveats(snapshots_dir):
    def render():
        return format_holdings_markdown("AAPL", *scan_holdings("AAPL", snapshots_dir))

    text = render()
    assert text == render()  # byte-identical on re-run
    assert "45-day filing lag" in text
    assert "US-listed long positions only" in text
    assert "Filers lag unevenly" in text
    assert "| Berkshire Hathaway | Q1 2026 | added (vs Q4 2025) | 100 | 1,000 | 66.67% |" in text
    assert "| Lindsell Train | Q2 2026 | opened (vs Q1 2026) | 40 | 400 | 80.00% |" in text
    assert "| Giverny | Q1 2026 | exited (vs Q4 2025) | 0 | 0 | 0.00% |" in text
    assert "**2** of 16 roster funds hold it; 1 exited last quarter." in text
    assert "Funds with no reported position:" in text


def test_report_labels_single_snapshot_fund_as_held(snapshots_dir):
    # Strip Giverny's prior period: its BRK.B row becomes "held (no prior)".
    (snapshots_dir / snapshot_filename(1641864, "2025-12-31")).unlink()
    holdings, _, _, _ = scan_holdings("BRKB", snapshots_dir)
    assert holdings[0].action == "held"
    text = format_holdings_markdown("BRKB", holdings, [], {BRKB}, "x")
    assert "held (no prior period fetched)" in text
