"""Regenerate the golden diagnosis files from the committed snapshots.

Run only when a rubric change is *intended*: uv run python tests/make_golden.py
Then review the diff before committing.

`--check` compares instead of writing and exits 1 on any difference (CI).
"""

from whale_engine.scorers.buffett import diagnose

from conftest import GOLDEN, load_snapshot
from golden_io import check_flag, emit, finish

GOLDEN_TICKERS = ["KO", "MA", "GM", "F"]

if __name__ == "__main__":
    check = check_flag()
    GOLDEN.mkdir(parents=True, exist_ok=True)
    results = [
        emit(GOLDEN / f"{ticker}.json", diagnose(load_snapshot(ticker)), check)
        for ticker in GOLDEN_TICKERS
    ]
    finish(results, check)
