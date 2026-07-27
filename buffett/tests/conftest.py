import json
from pathlib import Path

import pytest

SNAPSHOT_DATE = "2026-07-27"
SNAPSHOTS = Path(__file__).parent.parent / "snapshots"
GOLDEN = Path(__file__).parent / "golden"
GOLDEN_GRAHAM = GOLDEN / "graham"


def load_snapshot(ticker: str) -> dict:
    return json.loads((SNAPSHOTS / f"{ticker}-{SNAPSHOT_DATE}.json").read_text())


def load_golden(ticker: str) -> dict:
    return json.loads((GOLDEN / f"{ticker}.json").read_text())


def load_golden_graham(ticker: str) -> dict:
    return json.loads((GOLDEN_GRAHAM / f"{ticker}.json").read_text())


@pytest.fixture
def snapshot(request):
    return load_snapshot(request.param)
