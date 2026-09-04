"""Regenerate the golden portfolio reports from the pinned snapshots.

Run only when a methodology or contract change is *intended*:
    uv run python tests/make_golden_portfolio.py
Then review the diff — and remember that changing methodology v1 needs a
signed judgment review and a `portfolio_methodology_version` bump.

`--check` compares instead of writing and exits 1 on any difference (CI).
"""

from whale_engine.portfolio import build_report

from conftest import GOLDEN_PORTFOLIO, load_portfolio_inputs
from golden_io import check_flag, emit, finish
from test_portfolio_golden import GOLDEN_BASKETS

if __name__ == "__main__":
    check = check_flag()
    GOLDEN_PORTFOLIO.mkdir(parents=True, exist_ok=True)
    results = []
    for name, basket in GOLDEN_BASKETS.items():
        prices, edgar = load_portfolio_inputs(basket)
        results.append(emit(GOLDEN_PORTFOLIO / f"{name}.json", build_report(basket, prices, edgar), check))
    finish(results, check)
