"""`whale panel TICKER` — offline, deterministic, hard-fails on a missing snapshot."""

import json
import shutil

import pytest

from whale_engine.cli import main

from conftest import SNAPSHOTS


@pytest.fixture
def pinned(tmp_path):
    shutil.copy(SNAPSHOTS / "KO-2026-07-27.json", tmp_path / "KO-2026-07-27.json")
    return tmp_path


def run(tmp_path, *argv):
    return main(["panel", *argv, "--snapshots-dir", str(tmp_path)])


def test_panel_prints_the_summary_for_a_pinned_snapshot(pinned, capsys):
    assert run(pinned, "KO") == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ticker"] == "KO"
    assert result["engine_count"] == "Engine count: bullish 0, neutral 0, bearish 3, walked away 0"
    assert result["provenance"]["snapshot"].endswith("KO-2026-07-27.json")


def test_panel_output_is_byte_identical_across_runs(pinned, capsys):
    run(pinned, "KO")
    first = capsys.readouterr().out
    run(pinned, "ko")
    assert capsys.readouterr().out == first


def test_the_newest_snapshot_wins_unless_one_is_named(pinned, capsys):
    shutil.copy(SNAPSHOTS / "KO-2026-08-04.json", pinned / "KO-2026-08-04.json")
    run(pinned, "KO")
    assert json.loads(capsys.readouterr().out)["provenance"]["snapshot_fetched_at"] == "2026-08-04"
    run(pinned, "KO", "--snapshot", str(pinned / "KO-2026-07-27.json"))
    assert json.loads(capsys.readouterr().out)["provenance"]["snapshot_fetched_at"] == "2026-07-27"


def test_missing_snapshot_exits_non_zero_with_the_fix(pinned, capsys):
    assert run(pinned, "ZZZ") != 0
    assert "whale fetch ZZZ" in capsys.readouterr().err


def test_a_sector_only_snapshot_is_refused(pinned, capsys):
    sector = next((SNAPSHOTS / "sectors").glob("*.json"))
    assert run(pinned, "STUB", "--snapshot", str(sector)) != 0
    assert "sector-only" in capsys.readouterr().err


def test_panel_never_touches_the_network(pinned, monkeypatch):
    monkeypatch.delenv("EDGAR_IDENTITY", raising=False)
    assert run(pinned, "KO") == 0  # conftest refuses any socket
