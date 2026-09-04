"""fetch_snapshot end to end over a fake edgartools company (offline).

The network seams (`_edgar_company`, `_cboe_get_json`,
`_yfinance_reference_cap`, the filings-text and Form 4 collectors) are
monkeypatched; everything between them — quarter dedupe, TTM assembly,
balance matching, annual periods, market cap derivation, snapshot shape and
the validation section — runs for real. The fake company answers the same
three questions edgartools does: `get_ttm`, `facts.query().by_concept()` and
`get_filings`.
"""

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
import pytest

from whale_engine import fetch
from whale_engine.fetch import FetchError, fetch_snapshot

TODAY = date(2026, 7, 27)
LATEST_WINDOW = date(2026, 3, 31)  # what EDGAR has actually filed by TODAY
SHARES = 1_000_000.0
PRICE = 50.0


def _quarter_ends(latest: date, n: int) -> list[date]:
    ends, d = [], latest
    for _ in range(n):
        ends.append(d)
        # Previous quarter end: the last day of the month three months earlier.
        month = ends[-1].month - 3
        year = ends[-1].year
        if month <= 0:
            month, year = month + 12, year - 1
        d = (date(year, month, 28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return ends


@dataclass
class _TTM:
    value: float
    as_of_date: date
    has_gaps: bool = False
    warning: str | None = None


class _Query:
    def __init__(self, df):
        self._df = df

    def by_concept(self, tag):
        return _Query(self._df[self._df["concept"].str.endswith(":" + tag)])

    def to_dataframe(self):
        return self._df


class _Facts:
    def __init__(self, df):
        self._df = df

    def query(self):
        return _Query(self._df)


class _Filings(list):
    def head(self, n):
        return self[:n]


class FakeCompany:
    """Ten years of clean, boring filings: one net-income TTM window per
    quarter, a full balance sheet at every quarter end and fiscal year end."""

    sic = "7372"
    industry = "Services-Prepackaged Software"

    def __init__(self, distinct_windows: int = 12, with_shares: bool = True):
        self.window_ends = _quarter_ends(LATEST_WINDOW, distinct_windows)
        self.with_shares = with_shares
        self.facts = _Facts(self._facts_frame())

    # --- edgartools surface -------------------------------------------------
    def get_ttm(self, tag, as_of):
        year, q = int(as_of[:4]), int(as_of[-1])
        asked = (date(year, 3 * q, 28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        end = min(asked, LATEST_WINDOW)  # edgartools clamps to the latest window
        if end not in self.window_ends:
            return None
        i = self.window_ends.index(end)
        base = {
            "NetIncomeLoss": 10_000_000.0,
            "Revenues": 100_000_000.0,
            "NetCashProvidedByUsedInOperatingActivities": 12_000_000.0,
            "PaymentsToAcquirePropertyPlantAndEquipment": 2_000_000.0,
            "DepreciationDepletionAndAmortization": 1_500_000.0,
        }.get(tag)
        if base is None:
            return None
        return _TTM(value=base * (1 + 0.02 * (len(self.window_ends) - i)), as_of_date=end)

    def get_filings(self, form):
        return _Filings()  # no 8-K 4.02 restatements, no fallback filings needed

    # --- fixture data -------------------------------------------------------
    def _facts_frame(self):
        rows = []
        fy_ends = [e for e in self.window_ends if e.month == 12]
        for end in fy_ends:
            rows.append(
                ("us-gaap:NetIncomeLoss", "duration", end - timedelta(days=364), end, 40e6, end)
            )
        instants = {
            "us-gaap:StockholdersEquity": 200e6,
            "us-gaap:Assets": 500e6,
            "us-gaap:Liabilities": 300e6,
            "us-gaap:AssetsCurrent": 150e6,
            "us-gaap:LiabilitiesCurrent": 100e6,
            "us-gaap:CashAndCashEquivalentsAtCarryingValue": 80e6,
            "us-gaap:LongTermDebtNoncurrent": 50e6,
        }
        if self.with_shares:
            instants["us-gaap:CommonStockSharesOutstanding"] = SHARES
        for end in self.window_ends:
            for concept, value in instants.items():
                rows.append((concept, "instant", None, end, value, end + timedelta(days=40)))
        return pd.DataFrame(
            rows,
            columns=[
                "concept",
                "period_type",
                "period_start",
                "period_end",
                "numeric_value",
                "filing_date",
            ],
        )


@pytest.fixture
def offline_seams(monkeypatch):
    monkeypatch.setenv("EDGAR_IDENTITY", "Test Runner test@example.com")
    monkeypatch.setattr(
        fetch,
        "_cboe_get_json",
        lambda ticker: {"data": {"close": PRICE, "last_trade_time": f"{TODAY}T16:00:00"}},
    )
    monkeypatch.setattr(
        fetch, "_yfinance_reference_cap", lambda ticker: (PRICE * SHARES, "yfinance:fake")
    )
    monkeypatch.setattr(fetch, "_edgartools_version", lambda: "0.0-test")
    monkeypatch.setattr(
        "whale_engine.filings_text.extract_filings_text", lambda company, ticker: (None, [])
    )
    monkeypatch.setattr(
        "whale_engine.insider.collect_insider_activity", lambda company, today: (None, None)
    )


def test_happy_path_builds_a_complete_snapshot(offline_seams, monkeypatch):
    company = FakeCompany()
    monkeypatch.setattr(fetch, "_edgar_company", lambda ticker: company)

    snap = fetch_snapshot("FAKE", today=TODAY)

    assert snap["ticker"] == "FAKE" and snap["fetched_at"] == "2026-07-27"
    assert snap["schema_version"] == 2
    assert snap["source"]["fundamentals"] == "SEC EDGAR via edgartools 0.0-test"
    assert len(snap["periods"]) == fetch.N_PERIODS
    # Labelled from the window EDGAR actually returned, not the quarter asked for.
    assert snap["periods"][0]["period_end"] == "2026-03-31"
    assert snap["periods"][0]["as_of_quarter"] == "2026-Q1"
    assert [p["period_end"] for p in snap["periods"]] == sorted(
        (p["period_end"] for p in snap["periods"]), reverse=True
    )
    first = snap["periods"][0]
    assert first["ttm"]["revenue"] > first["ttm"]["net_income"] > 0
    assert first["balance"]["outstanding_shares"] == SHARES
    assert first["tags_used"]["net_income"] == "NetIncomeLoss"

    # Market cap is derived from the pinned price and the freshest filed count.
    assert snap["market_cap"] == PRICE * SHARES
    assert snap["market_cap_source"].startswith("derived:cboe.close@")
    assert snap["price_reference"]["price"] == PRICE
    assert snap["market_cap_check"]["deviation_pct"] == 0.0

    assert snap["sic"] == "7372" and snap["sic_description"].startswith("Services")
    assert snap["annual_periods"] and snap["annual_periods"][0]["ttm"]["net_income"] == 40e6
    assert "restatement_402" in snap["validation"]["checks_run"]
    assert "insider_activity" not in snap and "filings_sidecar" not in snap


def test_too_few_ttm_windows_hard_fails_before_any_scoring(offline_seams, monkeypatch):
    company = FakeCompany(distinct_windows=4)
    monkeypatch.setattr(fetch, "_edgar_company", lambda ticker: company)

    with pytest.raises(FetchError, match=r"only 4 distinct TTM windows found on EDGAR \(need 10\)"):
        fetch_snapshot("YOUNG", today=TODAY)


def test_no_share_count_anywhere_hard_fails_the_market_cap(offline_seams, monkeypatch):
    company = FakeCompany(with_shares=False)
    monkeypatch.setattr(fetch, "_edgar_company", lambda ticker: company)

    with pytest.raises(FetchError, match="no share count on EDGAR under any known tag"):
        fetch_snapshot("BARE", today=TODAY)
