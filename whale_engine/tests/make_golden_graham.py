"""Regenerate the Graham golden diagnosis files from the committed snapshots.

Run only when a rubric change is *intended*: uv run python tests/make_golden_graham.py
Then review the diff before committing.

`--check` compares instead of writing and exits 1 on any difference (CI).
"""

from whale_engine.scorers.graham import diagnose

from conftest import GOLDEN_GRAHAM, load_snapshot
from golden_io import check_flag, emit, finish

GOLDEN_TICKERS = ["NVDA", "KO", "F", "AAL"]

if __name__ == "__main__":
    check = check_flag()
    GOLDEN_GRAHAM.mkdir(parents=True, exist_ok=True)
    results = [
        emit(GOLDEN_GRAHAM / f"{ticker}.json", diagnose(load_snapshot(ticker)), check)
        for ticker in GOLDEN_TICKERS
    ]
    finish(results, check)
