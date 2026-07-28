"""Contract of the deep-history annual_periods key, post rubric v2 (#40).

Graham is pinned by goldens and must still ignore annual_periods entirely.
Buffett v2 *requires* them: a schema-v1 snapshot hard-fails with a refetch
message instead of silently diagnosing from the shallow quarterly window.
"""

import copy

import pytest

from conftest import load_snapshot
from whale_engine.errors import MissingDataError
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


def _without_annual(snapshot: dict) -> dict:
    stripped = copy.deepcopy(snapshot)
    del stripped["annual_periods"]
    stripped["schema_version"] = 1
    return stripped


def _with_fake_annual(snapshot: dict) -> dict:
    extended = copy.deepcopy(snapshot)
    extended["annual_periods"] = FAKE_ANNUAL
    extended["schema_version"] = 2
    return extended


def test_graham_ignores_annual_periods():
    snapshot = load_snapshot("KO")
    assert graham.diagnose(snapshot) == graham.diagnose(_with_fake_annual(snapshot))
    assert graham.diagnose(snapshot) == graham.diagnose(_without_annual(snapshot))


def test_buffett_v2_requires_annual_periods():
    snapshot = _without_annual(load_snapshot("KO"))
    with pytest.raises(MissingDataError, match="annual_periods"):
        buffett.diagnose(snapshot)


def test_buffett_v2_requires_min_complete_annual():
    snapshot = _with_fake_annual(load_snapshot("KO"))  # 1 incomplete annual entry
    with pytest.raises(MissingDataError, match="complete annual periods"):
        buffett.diagnose(snapshot)


def test_buffett_output_carries_rubric_version():
    result = buffett.diagnose(load_snapshot("KO"))
    assert result["rubric_version"] == 2
