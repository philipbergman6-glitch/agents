import json
from pathlib import Path

import pytest

SNAPSHOT_DATE = "2026-07-27"
SNAPSHOTS = Path(__file__).parent.parent / "snapshots"
GOLDEN = Path(__file__).parent / "golden"
GOLDEN_GRAHAM = GOLDEN / "graham"
GOLDEN_LYNCH = GOLDEN / "lynch"
GOLDEN_PORTFOLIO = GOLDEN / "portfolio"

# The portfolio layer needs price snapshots and the SIC fields, so its
# goldens read a later, explicitly pinned snapshot date than the scorers'.
PORTFOLIO_SNAPSHOT_DATE = "2026-08-04"


def load_snapshot(ticker: str) -> dict:
    return json.loads((SNAPSHOTS / f"{ticker}-{SNAPSHOT_DATE}.json").read_text())


def load_golden(ticker: str) -> dict:
    return json.loads((GOLDEN / f"{ticker}.json").read_text())


def load_golden_graham(ticker: str) -> dict:
    return json.loads((GOLDEN_GRAHAM / f"{ticker}.json").read_text())


def load_golden_lynch(ticker: str) -> dict:
    return json.loads((GOLDEN_LYNCH / f"{ticker}.json").read_text())


def load_portfolio_inputs(basket: list[str]) -> tuple[dict, dict]:
    """Pinned price + EDGAR snapshots for a golden basket.

    Dates are explicit rather than latest-wins: a golden must not change
    because someone refetched a ticker.
    """
    prices = {
        ticker: json.loads(
            (SNAPSHOTS / "prices" / f"{ticker}-{PORTFOLIO_SNAPSHOT_DATE}.json").read_text()
        )
        for ticker in basket
    }
    # Sector source per name, full snapshot first: a name too young for
    # the fundamentals depth a full fetch needs has only the sector-only file.
    edgar = {}
    for ticker in basket:
        full = SNAPSHOTS / f"{ticker}-{PORTFOLIO_SNAPSHOT_DATE}.json"
        sector = SNAPSHOTS / "sectors" / f"{ticker}-{PORTFOLIO_SNAPSHOT_DATE}.json"
        edgar[ticker] = json.loads((full if full.exists() else sector).read_text())
    return prices, edgar


def load_golden_portfolio(name: str) -> dict:
    return json.loads((GOLDEN_PORTFOLIO / f"{name}.json").read_text())


@pytest.fixture
def snapshot(request):
    return load_snapshot(request.param)
