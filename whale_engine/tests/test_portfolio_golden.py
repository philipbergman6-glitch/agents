"""Golden portfolio reports over real pinned snapshots.

Two layers, as with the whale scorers:
- semantic expectations: V and MA are the textbook "same bet", a card network
  and a bank and a beverage company are not, and two of four names in SIC 73
  is a sector concentration — the intent, robust to deliberate retuning;
- exact golden output: the whole report must match the committed JSON, so any
  unintended change to the arithmetic, the shape, or the pinned caveat fails
  loudly. Retuning means regenerating on purpose (and, for methodology v1
  itself, an owner-signed review):
      uv run python tests/make_golden_portfolio.py
"""

import pytest

from whale_engine.portfolio import build_report

from conftest import load_golden_portfolio, load_portfolio_inputs

GOLDEN_BASKETS = {
    # two card networks + a bank + a beverage: one flagged pair, one flagged sector
    "payments-bank-beverage": ["V", "MA", "JPM", "KO"],
    # a young restaurant chain against the same card networks
    "payments-restaurant": ["V", "MA", "CAVA"],
    # a 2025 IPO with under a year of trading history, alongside two old names:
    # the insufficient-history path on a real name, reachable only via
    # the sector-only EDGAR route
    "beverage-bank-ipo": ["KO", "JPM", "STUB"],
}


def report(name: str) -> dict:
    basket = GOLDEN_BASKETS[name]
    prices, edgar = load_portfolio_inputs(basket)
    return build_report(basket, prices, edgar)


@pytest.mark.parametrize("name", GOLDEN_BASKETS)
def test_exact_golden_output(name):
    assert report(name) == load_golden_portfolio(name)


@pytest.mark.parametrize("name", GOLDEN_BASKETS)
def test_report_is_deterministic(name):
    assert report(name) == report(name)


def test_the_two_card_networks_flag_as_the_same_bet():
    result = report("payments-bank-beverage")
    assert result["correlation"]["matrix"]["MA|V"] >= 0.80
    assert {"MA", "V"} == set(result["correlation"]["flagged_pairs"][0]["pair"])


def test_a_card_network_and_a_beverage_company_do_not():
    result = report("payments-bank-beverage")
    assert result["correlation"]["matrix"]["KO|V"] < 0.80
    assert all(set(p["pair"]) != {"KO", "V"} for p in result["correlation"]["flagged_pairs"])


def test_the_business_services_group_is_flagged_at_half_the_basket():
    result = report("payments-bank-beverage")
    groups = {g["sic2"]: g for g in result["sectors"]["groups"]}
    assert groups["73"]["tickers"] == ["MA", "V"]
    assert groups["73"]["share"] == 0.5 and groups["73"]["flagged"] is True
    assert groups["60"]["tickers"] == ["JPM"] and groups["60"]["flagged"] is False
    assert groups["20"]["tickers"] == ["KO"]
    assert result["sectors"]["flagged_groups"] == ["73"]


def test_every_pair_of_a_real_basket_is_measured_over_the_same_window():
    result = report("payments-bank-beverage")
    window = result["correlation"]["window"]
    assert window["observations"] == 156
    assert all(n == 156 for n in result["correlation"]["observations"].values())
    assert result["warnings"] == []


def test_provenance_pins_the_vendor_series_and_snapshot_vintages():
    result = report("payments-restaurant")
    provenance = result["provenance"]
    assert provenance["vendor"] == "Alpha Vantage"
    assert provenance["series"] == "TIME_SERIES_WEEKLY_ADJUSTED"
    assert all(s["last_complete_week"] == "2026-07-31" for s in provenance["snapshots"])


def test_a_real_ipo_lands_in_insufficient_history_rather_than_killing_the_report():
    """StubHub listed in 2025, so it has under a year of weekly returns — the
    insufficient-history path on a name a client could actually own. Before the
    sector-only route existed this basket produced no report at all: the SIC
    lookup demanded a full fundamentals snapshot STUB cannot support."""
    result = report("beverage-bank-ipo")
    warning = next(w for w in result["warnings"] if w["code"] == "insufficient_history")
    assert warning["ticker"] == "STUB"
    assert result["correlation"]["matrix"] == {
        "JPM|KO": 0.133,
        "JPM|STUB": None,
        "KO|STUB": None,
    }
    # Weighted like any other name, and its sector still counted.
    assert [b["weight"] for b in result["basket"]] == [1 / 3] * 3
    groups = {g["sic2"]: g for g in result["sectors"]["groups"]}
    assert groups["79"]["tickers"] == ["STUB"]


def test_provenance_marks_the_ipo_as_a_sector_only_lookup():
    sources = {
        entry["ticker"]: entry["source"]
        for entry in report("beverage-bank-ipo")["provenance"]["edgar_snapshots"]
    }
    assert sources == {"KO": "fetch", "JPM": "fetch", "STUB": "sector-only"}
