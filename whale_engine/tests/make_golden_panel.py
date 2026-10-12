"""Regenerate the golden panel summaries from the pinned snapshots.

Run only when a panel contract change is *intended*:
    uv run python tests/make_golden_panel.py
Then review the diff — and remember that changing panel v1 needs a signed
judgment review and a `panel_version` bump.

`--check` compares instead of writing and exits 1 on any difference (CI).
"""

from whale_engine.panel import build_panel

from conftest import GOLDEN_PANEL, load_panel_snapshot
from golden_io import check_flag, emit, finish
from test_panel_golden import GOLDEN_PANELS

if __name__ == "__main__":
    check = check_flag()
    GOLDEN_PANEL.mkdir(parents=True, exist_ok=True)
    results = [
        emit(GOLDEN_PANEL / f"{name}.json", build_panel(load_panel_snapshot(name)), check)
        for name in GOLDEN_PANELS
    ]
    finish(results, check)
