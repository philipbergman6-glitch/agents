"""Regenerate the Lynch golden diagnosis files from the committed snapshots.

Run only when a rubric change is *intended*: uv run python tests/make_golden_lynch.py
Then review the diff before committing.

`--check` compares instead of writing and exits 1 on any difference (CI).
"""

from whale_engine.scorers.lynch import diagnose

from conftest import GOLDEN_LYNCH, load_snapshot
from golden_io import check_flag, emit, finish

GOLDEN_TICKERS = ["NVDA", "LULU", "KO", "CCL", "AAL", "MA"]

if __name__ == "__main__":
    check = check_flag()
    GOLDEN_LYNCH.mkdir(parents=True, exist_ok=True)
    results = [
        emit(GOLDEN_LYNCH / f"{ticker}.json", diagnose(load_snapshot(ticker)), check)
        for ticker in GOLDEN_TICKERS
    ]
    finish(results, check)
