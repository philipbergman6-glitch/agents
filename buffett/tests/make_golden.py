"""Regenerate the golden diagnosis files from the committed snapshots.

Run only when a rubric change is *intended*: uv run python tests/make_golden.py
Then review the diff before committing.
"""

import json
from pathlib import Path

from buffett_engine.score import diagnose

from conftest import GOLDEN, load_snapshot

GOLDEN_TICKERS = ["KO", "MA", "GM", "F"]

if __name__ == "__main__":
    Path(GOLDEN).mkdir(exist_ok=True)
    for ticker in GOLDEN_TICKERS:
        out = GOLDEN / f"{ticker}.json"
        out.write_text(
            json.dumps(diagnose(load_snapshot(ticker)), indent=2, sort_keys=True, ensure_ascii=False)
            + "\n"
        )
        print(out)
