"""Regenerate the Graham golden diagnosis files from the committed snapshots.

Run only when a rubric change is *intended*: uv run python tests/make_golden_graham.py
Then review the diff before committing.
"""

import json

from whale_engine.scorers.graham import diagnose

from conftest import GOLDEN_GRAHAM, load_snapshot

GOLDEN_TICKERS = ["NVDA", "KO", "F", "AAL"]

if __name__ == "__main__":
    GOLDEN_GRAHAM.mkdir(parents=True, exist_ok=True)
    for ticker in GOLDEN_TICKERS:
        out = GOLDEN_GRAHAM / f"{ticker}.json"
        out.write_text(
            json.dumps(diagnose(load_snapshot(ticker)), indent=2, sort_keys=True, ensure_ascii=False)
            + "\n"
        )
        print(out)
