"""Unit tests for the portfolio layer (methodology v1, report contract v1).

Every number the report publishes is either pinned by those two tickets or is
arithmetic over synthetic series built here, so a rule change fails loudly
instead of drifting.
"""

import json
import math
from datetime import date, timedelta

import pytest

from whale_engine import portfolio
from whale_engine.portfolio import PortfolioError, build_report

END_WEEK = date(2026, 7, 27)  # a Monday: week keys are Mondays


def price_snapshot(ticker, closes, end_week=END_WEEK, fetched_at="2026-08-01"):
    """Synthetic price snapshot: `closes` oldest-first, ending in `end_week`.

    Bars are dated on the Friday of their week, as the vendor files them.
    """
    bars = []
    for i, close in enumerate(closes):
        week = end_week - timedelta(days=7 * (len(closes) - 1 - i))
        bars.append({"date": (week + timedelta(days=4)).isoformat(), "adjusted_close": close})
    return {
        "schema_version": 1,
        "ticker": ticker,
        "fetched_at": fetched_at,
        "vendor": "Alpha Vantage",
        "series": "TIME_SERIES_WEEKLY_ADJUSTED",
        "last_refreshed": (end_week + timedelta(days=4)).isoformat(),
        "last_complete_week": (end_week + timedelta(days=4)).isoformat(),
        "last_complete_week_start": end_week.isoformat(),
        "partial_bars_dropped": [],
        "observations": len(bars),
        "weekly_adjusted_close": bars,
    }


def edgar_snapshot(ticker, sic="7372", desc="Prepackaged Software"):
    return {
        "ticker": ticker,
        "fetched_at": "2026-07-27",
        "sic": sic,
        "sic_description": desc,
    }


def geometric(start, step, n):
    """n closes compounding by `step` per week — a clean log-return series."""
    return [start * (step ** i) for i in range(n)]


def wiggle(n, amplitude=0.05, phase=0.0, base=100.0):
    """Deterministic oscillating close series (no randomness anywhere)."""
    return [base * math.exp(amplitude * math.sin(i + phase)) for i in range(n)]


def report(price_map, edgar_map=None, tickers=None):
    tickers = tickers or list(price_map)
    edgar_map = edgar_map or {t: edgar_snapshot(t) for t in tickers}
    return build_report(tickers, price_map, edgar_map)


# --- basket rules (methodology v1 §5) ---------------------------------------------------


@pytest.mark.parametrize("tickers", [["V"], list("ABCDEFGHIJKLMNOP")])
def test_basket_size_outside_2_to_15_hard_fails(tickers):
    with pytest.raises(PortfolioError, match="2-15"):
        portfolio.normalize_basket(tickers)


def test_duplicate_ticker_hard_fails_instead_of_double_weighting():
    with pytest.raises(PortfolioError, match="repeats V"):
        portfolio.normalize_basket(["V", "MA", "v"])


def test_basket_is_uppercased_and_keeps_client_order():
    assert portfolio.normalize_basket(["ma", " v ", "JPM"]) == ["MA", "V", "JPM"]


def test_equal_weights_are_exactly_one_over_n():
    result = report({t: price_snapshot(t, wiggle(200, phase=i)) for i, t in enumerate("ABCD")})
    assert [b["weight"] for b in result["basket"]] == [0.25] * 4
    assert sum(b["weight"] for b in result["basket"]) == 1.0


# --- correlation (methodology v1 §1-2, report contract v1 §1) -----------------


def test_identical_return_series_correlate_at_one_and_flag_as_the_same_bet():
    closes = wiggle(200)
    result = report({"AAA": price_snapshot("AAA", closes), "BBB": price_snapshot("BBB", closes)})
    assert result["correlation"]["matrix"]["AAA|BBB"] == 1.0
    assert result["correlation"]["flagged_pairs"] == [{"pair": ["AAA", "BBB"], "rho": 1.0}]


def test_mirror_image_series_correlate_at_minus_one_and_never_flag():
    closes = wiggle(200)
    inverse = [100.0 * 100.0 / c for c in closes]
    result = report({"AAA": price_snapshot("AAA", closes), "BBB": price_snapshot("BBB", inverse)})
    assert result["correlation"]["matrix"]["AAA|BBB"] == -1.0
    assert result["correlation"]["flagged_pairs"] == []


def test_correlation_matches_the_pearson_of_the_weekly_log_returns():
    a, b = wiggle(200), wiggle(200, amplitude=0.03, phase=1.7)
    ra = [math.log(a[i] / a[i - 1]) for i in range(1, len(a))][-portfolio.LOOKBACK_WEEKS:]
    rb = [math.log(b[i] / b[i - 1]) for i in range(1, len(b))][-portfolio.LOOKBACK_WEEKS:]
    expected = round(portfolio._pearson(ra, rb), portfolio.RHO_DECIMALS)
    result = report({"AAA": price_snapshot("AAA", a), "BBB": price_snapshot("BBB", b)})
    assert result["correlation"]["matrix"]["AAA|BBB"] == expected


def test_flag_fires_exactly_at_the_locked_080_threshold():
    assert portfolio.SAME_BET_THRESHOLD == 0.80


def test_window_is_three_years_of_weeks_and_never_longer():
    # 400 bars available, only the 156-week window may be used.
    result = report({t: price_snapshot(t, wiggle(400, phase=i)) for i, t in enumerate("AB")})
    window = result["correlation"]["window"]
    assert window["end"] == END_WEEK.isoformat()
    assert window["start"] == (END_WEEK - timedelta(days=7 * portfolio.LOOKBACK_WEEKS)).isoformat()
    assert window["observations"] == portfolio.LOOKBACK_WEEKS
    assert result["correlation"]["observations"]["A|B"] == portfolio.LOOKBACK_WEEKS


def test_window_ends_at_the_newest_week_every_snapshot_reaches():
    """A basket priced across two fetch days still compares like with like."""
    older = END_WEEK - timedelta(days=7 * 3)
    result = report(
        {
            "AAA": price_snapshot("AAA", wiggle(200)),
            "BBB": price_snapshot("BBB", wiggle(200, phase=0.4), end_week=older),
        }
    )
    assert result["correlation"]["window"]["end"] == older.isoformat()


def test_a_gap_in_the_series_drops_one_observation_rather_than_spanning_it():
    closes = wiggle(200)
    snap = price_snapshot("AAA", closes)
    del snap["weekly_adjusted_close"][100]  # one missing week
    result = report({"AAA": snap, "BBB": price_snapshot("BBB", wiggle(200, phase=0.9))})
    # the missing bar kills its own return and the following week's
    assert result["correlation"]["observations"]["AAA|BBB"] == portfolio.LOOKBACK_WEEKS - 2


def test_full_matrix_is_emitted_for_every_pair_not_just_flagged_ones():
    result = report({t: price_snapshot(t, wiggle(200, phase=i)) for i, t in enumerate("ABC")})
    assert sorted(result["correlation"]["matrix"]) == ["A|B", "A|C", "B|C"]


def test_zero_variance_series_reports_null_with_a_warning_never_a_crash():
    flat = [100.0] * 200
    result = report({"AAA": price_snapshot("AAA", flat), "BBB": price_snapshot("BBB", wiggle(200))})
    assert result["correlation"]["matrix"]["AAA|BBB"] is None
    assert [w["code"] for w in result["warnings"]] == ["zero_variance"]


# --- short history (methodology v1 §4, report contract v1 §4) -----------------


def test_short_history_name_is_weighted_normally_with_null_pairs_and_a_warning():
    result = report(
        {
            "AAA": price_snapshot("AAA", wiggle(200)),
            "BBB": price_snapshot("BBB", wiggle(200, phase=0.4)),
            "NEW": price_snapshot("NEW", wiggle(30, phase=1.1)),
        }
    )
    assert [b["weight"] for b in result["basket"]] == [1 / 3] * 3
    assert result["correlation"]["matrix"]["AAA|NEW"] is None
    assert result["correlation"]["matrix"]["BBB|NEW"] is None
    assert result["correlation"]["matrix"]["AAA|BBB"] is not None
    warning = next(w for w in result["warnings"] if w["code"] == "insufficient_history")
    assert warning["ticker"] == "NEW"
    assert "29" in warning["message"] and "52-week floor" in warning["message"]


def test_the_floor_is_52_completed_weekly_returns():
    """53 closes -> 52 returns: exactly at the floor, so the pair is measured."""
    result = report(
        {
            "AAA": price_snapshot("AAA", wiggle(200)),
            "NEW": price_snapshot("NEW", wiggle(53, phase=0.4)),
        }
    )
    assert result["correlation"]["matrix"]["AAA|NEW"] is not None
    assert result["correlation"]["observations"]["AAA|NEW"] == 52
    assert result["warnings"] == []


def test_one_week_below_the_floor_is_null():
    result = report(
        {
            "AAA": price_snapshot("AAA", wiggle(200)),
            "NEW": price_snapshot("NEW", wiggle(52, phase=0.4)),
        }
    )
    assert result["correlation"]["matrix"]["AAA|NEW"] is None


def test_window_observations_count_only_weeks_every_measured_name_has():
    result = report(
        {
            "AAA": price_snapshot("AAA", wiggle(200)),
            "MID": price_snapshot("MID", wiggle(80, phase=0.4)),
        }
    )
    assert result["correlation"]["window"]["observations"] == 79


# --- sectors (methodology v1 §3, report contract v1 §5) -----------------------


def test_sector_groups_use_the_two_digit_major_group_with_its_published_title():
    prices = {t: price_snapshot(t, wiggle(200, phase=i)) for i, t in enumerate(["V", "JPM"])}
    result = report(
        prices,
        {
            "V": edgar_snapshot("V", "7389", "Services"),
            "JPM": edgar_snapshot("JPM", "6022", "Banks"),
        },
    )
    groups = {g["sic2"]: g for g in result["sectors"]["groups"]}
    assert groups["73"]["desc"] == "Business Services"
    assert groups["60"]["desc"] == "Depository Institutions"
    assert groups["73"]["tickers"] == ["V"] and groups["73"]["share"] == 0.5


def test_group_above_40_percent_of_names_is_flagged_and_at_40_is_not():
    tickers = ["A", "B", "C", "D", "E"]
    prices = {t: price_snapshot(t, wiggle(200, phase=i)) for i, t in enumerate(tickers)}
    sic = {"A": "7372", "B": "7372", "C": "7372", "D": "6022", "E": "6022"}
    result = report(prices, {t: edgar_snapshot(t, sic[t]) for t in tickers})
    groups = {g["sic2"]: g for g in result["sectors"]["groups"]}
    assert groups["73"]["share"] == 0.6 and groups["73"]["flagged"] is True
    assert groups["60"]["share"] == 0.4 and groups["60"]["flagged"] is False
    assert result["sectors"]["flagged_groups"] == ["73"]


def test_missing_sic_is_a_warned_gap_that_never_counts_as_concentration():
    tickers = ["A", "B", "C"]
    prices = {t: price_snapshot(t, wiggle(200, phase=i)) for i, t in enumerate(tickers)}
    edgar = {t: edgar_snapshot(t, None, None) for t in tickers}
    edgar["A"] = edgar_snapshot("A", "7372")
    result = report(prices, edgar)
    unknown = next(g for g in result["sectors"]["groups"] if g["sic2"] is None)
    assert unknown["share"] == pytest.approx(0.6667) and unknown["flagged"] is False
    assert result["sectors"]["flagged_groups"] == []
    unavailable = {w["ticker"] for w in result["warnings"] if w["code"] == "sector_unavailable"}
    assert unavailable == {"B", "C"}


def test_pre_sic_snapshot_is_told_apart_from_edgar_having_no_sic():
    tickers = ["A", "B"]
    prices = {t: price_snapshot(t, wiggle(200, phase=i)) for i, t in enumerate(tickers)}
    old = {"ticker": "B", "fetched_at": "2026-07-01"}  # pre-SIC fields: keys absent entirely
    result = report(prices, {"A": edgar_snapshot("A"), "B": old})
    codes = {w["code"] for w in result["warnings"]}
    assert codes == {"sic_field_absent"}
    assert "refetch" in next(w for w in result["warnings"])["message"]


# --- contract shape, provenance, caveat (report contract v1 §3, §6) -------------------------


def test_report_carries_the_methodology_version_and_the_verbatim_caveat():
    result = report({t: price_snapshot(t, wiggle(200, phase=i)) for i, t in enumerate("AB")})
    assert result["portfolio_methodology_version"] == portfolio.METHODOLOGY_VERSION
    assert result["caveats"] == [portfolio.RESIDUAL_RISK_CAVEAT]
    assert "do not remove market risk" in result["caveats"][0]


def test_provenance_names_vendor_series_and_every_snapshot_vintage():
    result = report({t: price_snapshot(t, wiggle(200, phase=i)) for i, t in enumerate("AB")})
    provenance = result["provenance"]
    assert provenance["vendor"] == "Alpha Vantage"
    assert provenance["series"] == "TIME_SERIES_WEEKLY_ADJUSTED"
    assert [s["ticker"] for s in provenance["snapshots"]] == ["A", "B"]
    assert all(s["snapshot_date"] == "2026-08-01" for s in provenance["snapshots"])
    assert [s["ticker"] for s in provenance["edgar_snapshots"]] == ["A", "B"]


def test_report_is_byte_identical_across_runs():
    prices = {t: price_snapshot(t, wiggle(200, phase=i)) for i, t in enumerate("ABC")}
    first = json.dumps(report(prices), indent=2, sort_keys=True)
    second = json.dumps(report(prices), indent=2, sort_keys=True)
    assert first == second


# --- hard failures -----------------------------------------------------------


def test_missing_price_history_hard_fails_with_the_command_that_fixes_it():
    with pytest.raises(PortfolioError, match="whale prices BBB"):
        build_report(
            ["AAA", "BBB"],
            {"AAA": price_snapshot("AAA", wiggle(200))},
            {t: edgar_snapshot(t) for t in ("AAA", "BBB")},
        )


def test_missing_edgar_snapshot_hard_fails():
    with pytest.raises(PortfolioError, match="no EDGAR sector source"):
        build_report(
            ["AAA", "BBB"],
            {t: price_snapshot(t, wiggle(200)) for t in ("AAA", "BBB")},
            {"AAA": edgar_snapshot("AAA")},
        )


def test_unusable_price_bar_hard_fails_instead_of_scoring_around_it():
    snap = price_snapshot("AAA", wiggle(200))
    snap["weekly_adjusted_close"][10]["adjusted_close"] = -1.0
    with pytest.raises(PortfolioError, match="non-positive"):
        report({"AAA": snap, "BBB": price_snapshot("BBB", wiggle(200, phase=0.3))})


def test_empty_price_series_hard_fails():
    snap = price_snapshot("AAA", wiggle(200))
    snap["weekly_adjusted_close"] = []
    with pytest.raises(PortfolioError, match="no weekly bars"):
        report({"AAA": snap, "BBB": price_snapshot("BBB", wiggle(200))})
