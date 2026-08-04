"""Regenerate the golden portfolio reports from the pinned snapshots.

Run only when a methodology or contract change is *intended*:
    uv run python tests/make_golden_portfolio.py
Then review the diff — and remember that changing methodology v1 needs an
owner-signed judgment review and a `portfolio_methodology_version` bump.
"""

import json
from pathlib import Path

from whale_engine.portfolio import build_report

from conftest import GOLDEN_PORTFOLIO, load_portfolio_inputs
from test_portfolio_golden import GOLDEN_BASKETS

if __name__ == "__main__":
    Path(GOLDEN_PORTFOLIO).mkdir(parents=True, exist_ok=True)
    for name, basket in GOLDEN_BASKETS.items():
        prices, edgar = load_portfolio_inputs(basket)
        out = GOLDEN_PORTFOLIO / f"{name}.json"
        out.write_text(
            json.dumps(
                build_report(basket, prices, edgar), indent=2, sort_keys=True, ensure_ascii=False
            )
            + "\n"
        )
        print(out)
