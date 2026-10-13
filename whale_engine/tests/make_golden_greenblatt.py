"""Regenerate the Greenblatt golden diagnosis files from the committed snapshots.

Run only when a rubric change is *intended*: uv run python tests/make_golden_greenblatt.py
Then review the diff before committing.

`--check` compares instead of writing and exits 1 on any difference (CI).
"""

from whale_engine.scorers.greenblatt import diagnose

from conftest import GOLDEN_GREENBLATT, load_snapshot
from golden_io import check_flag, emit, finish

GOLDEN_TICKERS = ["LULU", "META", "JNJ", "KO", "V", "AAL", "F"]

if __name__ == "__main__":
    check = check_flag()
    GOLDEN_GREENBLATT.mkdir(parents=True, exist_ok=True)
    results = [
        emit(
            GOLDEN_GREENBLATT / f"{ticker}.json",
            diagnose(load_snapshot(ticker, whale="greenblatt")),
            check,
        )
        for ticker in GOLDEN_TICKERS
    ]
    finish(results, check)
