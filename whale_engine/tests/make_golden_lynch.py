"""Regenerate the Lynch golden diagnosis files from the committed snapshots.

Run only when a rubric change is *intended*: uv run python tests/make_golden_lynch.py
Then review the diff before committing.
"""

import json

from whale_engine.scorers.lynch import diagnose

from conftest import GOLDEN_LYNCH, load_snapshot

GOLDEN_TICKERS = ["NVDA", "LULU", "KO", "CCL", "AAL"]

if __name__ == "__main__":
    GOLDEN_LYNCH.mkdir(parents=True, exist_ok=True)
    for ticker in GOLDEN_TICKERS:
        out = GOLDEN_LYNCH / f"{ticker}.json"
        out.write_text(
            json.dumps(diagnose(load_snapshot(ticker)), indent=2, sort_keys=True, ensure_ascii=False)
            + "\n"
        )
        print(out)
