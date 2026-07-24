"""Same snapshot -> byte-identical diagnosis, at function and CLI level."""

import json

import pytest

from buffett_engine.score import diagnose

from conftest import SNAPSHOT_DATE, SNAPSHOTS, load_snapshot

ALL_SCORABLE = ["AAPL", "KO", "MA", "GM", "F", "AAL", "CCL"]


def _dump(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)


@pytest.mark.parametrize("ticker", ALL_SCORABLE)
def test_diagnose_is_deterministic(ticker):
    first = diagnose(load_snapshot(ticker))
    second = diagnose(load_snapshot(ticker))
    assert first == second
    assert _dump(first) == _dump(second)


def test_cli_output_is_byte_identical(capsys):
    from buffett_engine.cli import main

    args = ["diagnose", "AAPL", "--snapshot", str(SNAPSHOTS / f"AAPL-{SNAPSHOT_DATE}.json")]
    assert main(args) == 0
    first = capsys.readouterr().out
    assert main(args) == 0
    second = capsys.readouterr().out
    assert first == second
