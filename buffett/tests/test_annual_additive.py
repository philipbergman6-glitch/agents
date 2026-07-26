"""The deep-history annual_periods key is additive: no scorer may read it.

Buffett is a frozen, sold product and Graham is pinned by goldens, so a
schema-v2 snapshot (with annual_periods) must diagnose identically to the
same snapshot without it.
"""

import copy

from conftest import load_snapshot
from whale_engine.scorers import buffett, graham

FAKE_ANNUAL = [
    {
        "period_start": "2015-01-01",
        "period_end": "2015-12-31",
        "ttm": {"net_income": 1.0, "revenue": 2.0},
        "balance": {"total_assets": 3.0},
        "tags_used": {},
    }
]


def _with_annual(snapshot: dict) -> dict:
    extended = copy.deepcopy(snapshot)
    extended["annual_periods"] = FAKE_ANNUAL
    extended["schema_version"] = 2
    return extended


def test_buffett_ignores_annual_periods():
    snapshot = load_snapshot("KO")
    assert buffett.diagnose(snapshot) == buffett.diagnose(_with_annual(snapshot))


def test_graham_ignores_annual_periods():
    snapshot = load_snapshot("KO")
    assert graham.diagnose(snapshot) == graham.diagnose(_with_annual(snapshot))
