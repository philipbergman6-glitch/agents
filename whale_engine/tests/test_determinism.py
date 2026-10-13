"""Same snapshot -> byte-identical diagnosis, at function and CLI level."""

import json

import pytest

from whale_engine.scorers import WHALES, get_diagnose

from conftest import load_snapshot, snapshot_path

ALL_SCORABLE = ["AAPL", "KO", "MA", "GM", "F", "AAL", "CCL"]

# GM and F resolve no debt tags in any period: Buffett/Graham degrade (D/E
# scored 0 as a data gap), but Lynch and Greenblatt hard-fail by rubric
# (crash-over-silent), so they are not scorable for them. Greenblatt also
# needs the net_fixed_assets field, so his roster reads the later snapshot
# date pinned in conftest (WHALE_SNAPSHOT_DATE).
#
# Every registered whale needs a roster here; a missing one fails
# `test_every_registered_whale_has_a_scorable_roster` below rather than
# breaking collection.
SCORABLE = {
    "buffett": ALL_SCORABLE,
    "graham": ALL_SCORABLE,
    "lynch": ["AAPL", "KO", "MA", "AAL", "CCL"],
    "greenblatt": ["KO", "LULU", "META", "AAL"],
}


def _dump(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)


@pytest.mark.parametrize(
    "whale,ticker", [(w, t) for w in WHALES for t in SCORABLE.get(w, ())]
)
def test_diagnose_is_deterministic(ticker, whale):
    diagnose = get_diagnose(whale)
    first = diagnose(load_snapshot(ticker, whale=whale))
    second = diagnose(load_snapshot(ticker, whale=whale))
    assert first == second
    assert _dump(first) == _dump(second)


def test_every_registered_whale_has_a_scorable_roster():
    assert set(SCORABLE) == set(WHALES)
    assert all(SCORABLE[w] for w in WHALES)


def test_cli_output_is_byte_identical(capsys):
    from whale_engine.cli import buffett_main as main

    args = ["diagnose", "AAPL", "--snapshot", str(snapshot_path("AAPL"))]
    assert main(args) == 0
    first = capsys.readouterr().out
    assert main(args) == 0
    second = capsys.readouterr().out
    assert first == second


# Buffett's path is covered by the alias test above.
@pytest.mark.parametrize(
    "whale,ticker",
    [(w, SCORABLE[w][0]) for w in WHALES if w != "buffett" and SCORABLE.get(w)],
)
def test_whale_cli_output_is_byte_identical(capsys, whale, ticker):
    from whale_engine.cli import main

    args = [
        "diagnose", ticker,
        "--whale", whale,
        "--snapshot", str(snapshot_path(ticker, whale)),
    ]
    assert main(args) == 0
    first = capsys.readouterr().out
    assert main(args) == 0
    second = capsys.readouterr().out
    assert first == second
