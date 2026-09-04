"""Price-history fetch + pinned snapshot module.

Offline: the Alpha Vantage network seam (prices._av_get_json) is monkeypatched
with the real response shape captured live from the vendor's public `demo` key
(tests/fixtures/av_weekly_adjusted_IBM.json — 200 weekly bars, 2022-10-14 →
2026-08-03, trailing bar the in-progress week).
"""

import json
from datetime import date
from pathlib import Path

import pytest

import whale_engine.prices as prices
from whale_engine.prices import PriceFetchError

FIXTURES = Path(__file__).parent / "fixtures"

# The fixture's newest bar (2026-08-03, a Monday) is the in-progress week of
# the week starting 2026-08-03; the newest completed bar is Friday 2026-07-31.
TODAY = date(2026, 8, 4)  # Tuesday
FAKE_KEY = "NOT-A-REAL-KEY-JUST-A-TEST"


def payload(**overrides) -> dict:
    data = json.loads((FIXTURES / "av_weekly_adjusted_IBM.json").read_text())
    data.update(overrides)
    return data


def payload_without_partial() -> dict:
    """Same fixture with the in-progress bar removed (a Friday-close fetch)."""
    data = payload()
    del data["Weekly Adjusted Time Series"]["2026-08-03"]
    data["Meta Data"]["3. Last Refreshed"] = "2026-07-31"
    return data


# --- week boundaries --------------------------------------------------------


@pytest.mark.parametrize(
    "day,expected",
    [
        (date(2026, 8, 3), date(2026, 8, 3)),  # Monday
        (date(2026, 8, 4), date(2026, 8, 3)),  # Tuesday
        (date(2026, 8, 7), date(2026, 8, 3)),  # Friday
        (date(2026, 8, 9), date(2026, 8, 3)),  # Sunday
    ],
)
def test_week_start_is_monday(day, expected):
    assert prices.week_start(day) == expected


@pytest.mark.parametrize(
    "day,expected",
    [
        (date(2026, 8, 3), date(2026, 7, 27)),  # Monday: this week is in progress
        (date(2026, 8, 4), date(2026, 7, 27)),  # Tuesday
        (date(2026, 8, 7), date(2026, 7, 27)),  # Friday: session may still be open
        (date(2026, 8, 8), date(2026, 8, 3)),  # Saturday: this week has closed
        (date(2026, 8, 9), date(2026, 8, 3)),  # Sunday
    ],
)
def test_last_completed_week_start(day, expected):
    assert prices.last_completed_week_start(day) == expected


def test_weekend_fetch_keeps_the_week_that_just_closed():
    # Saturday 2026-08-08: the 08-03 week's Friday bar is final, so a fetch
    # that day must pin it rather than discard it as in progress.
    body = payload()
    body["Weekly Adjusted Time Series"]["2026-08-07"] = dict(
        body["Weekly Adjusted Time Series"].pop("2026-08-03")
    )
    snap = prices.parse_weekly_adjusted(body, "IBM", date(2026, 8, 8))
    assert snap["last_complete_week"] == "2026-08-07"
    assert snap["partial_bars_dropped"] == []


# --- parser -----------------------------------------------------------------


def test_parse_drops_the_in_progress_bar():
    snap = prices.parse_weekly_adjusted(payload(), "IBM", TODAY)
    dates = [row["date"] for row in snap["weekly_adjusted_close"]]
    assert "2026-08-03" not in dates
    assert dates[-1] == "2026-07-31"
    assert snap["partial_bars_dropped"] == ["2026-08-03"]
    assert snap["observations"] == 199 == len(dates)


def test_parse_records_the_weekly_close_the_gate_compares_against():
    snap = prices.parse_weekly_adjusted(payload(), "IBM", TODAY)
    assert snap["last_complete_week"] == "2026-07-31"  # read, never derived
    assert snap["last_complete_week_start"] == "2026-07-27"


def test_parse_keeps_a_completed_trailing_bar():
    snap = prices.parse_weekly_adjusted(payload_without_partial(), "IBM", TODAY)
    assert snap["partial_bars_dropped"] == []
    assert snap["weekly_adjusted_close"][-1]["date"] == "2026-07-31"
    assert snap["observations"] == 199


def test_parse_is_ascending_and_uses_adjusted_close():
    snap = prices.parse_weekly_adjusted(payload(), "IBM", TODAY)
    rows = snap["weekly_adjusted_close"]
    assert rows[0]["date"] == "2022-10-14"
    assert [r["date"] for r in rows] == sorted(r["date"] for r in rows)
    # 2022-10-14 predates several IBM dividends, so adjusted close != close:
    # the parser must take "5. adjusted close", never "4. close".
    raw = payload()["Weekly Adjusted Time Series"]["2022-10-14"]
    assert raw["5. adjusted close"] != raw["4. close"]
    assert rows[0]["adjusted_close"] == float(raw["5. adjusted close"]) == 104.8835


def test_parse_carries_provenance():
    snap = prices.parse_weekly_adjusted(payload(), "IBM", TODAY)
    assert snap["vendor"] == "Alpha Vantage"
    assert snap["series"] == "TIME_SERIES_WEEKLY_ADJUSTED"
    assert snap["ticker"] == "IBM"
    assert snap["fetched_at"] == "2026-08-04"
    assert snap["schema_version"] == prices.PRICE_SCHEMA_VERSION


def test_holiday_dated_bars_are_kept_verbatim():
    # 2024-11-29 (Thanksgiving week) and 2025-04-17 (Good Friday week) are
    # Thursday-dated bars in the live fixture: dating is read, not derived.
    snap = prices.parse_weekly_adjusted(payload(), "IBM", TODAY)
    dates = {row["date"] for row in snap["weekly_adjusted_close"]}
    assert "2025-04-17" in dates
    assert date.fromisoformat("2025-04-17").weekday() == 3  # Thursday


# --- hard failures ----------------------------------------------------------


def test_information_body_hard_fails():
    body = {
        "Information": "Thank you for using Alpha Vantage! Our standard API "
        "rate limit is 25 requests per day."
    }
    with pytest.raises(PriceFetchError, match=r"25 requests per day"):
        prices.parse_weekly_adjusted(body, "IBM", TODAY)


def test_note_and_error_message_bodies_hard_fail():
    with pytest.raises(PriceFetchError, match=r"Invalid API call"):
        prices.parse_weekly_adjusted({"Error Message": "Invalid API call"}, "IBM", TODAY)
    with pytest.raises(PriceFetchError, match=r"call frequency"):
        prices.parse_weekly_adjusted({"Note": "call frequency"}, "IBM", TODAY)


def test_missing_time_series_key_hard_fails_even_with_no_message():
    with pytest.raises(PriceFetchError, match=r"TIME_SERIES_WEEKLY_ADJUSTED"):
        prices.parse_weekly_adjusted({"Meta Data": {}}, "IBM", TODAY)


def test_symbol_mismatch_hard_fails():
    with pytest.raises(PriceFetchError, match=r"MSFT"):
        prices.parse_weekly_adjusted(payload(), "MSFT", TODAY)


def test_empty_series_hard_fails():
    body = payload()
    body["Weekly Adjusted Time Series"] = {}
    with pytest.raises(PriceFetchError, match=r"no weekly bars"):
        prices.parse_weekly_adjusted(body, "IBM", TODAY)


def test_only_partial_bars_hard_fails():
    body = payload()
    series = body["Weekly Adjusted Time Series"]
    body["Weekly Adjusted Time Series"] = {"2026-08-03": series["2026-08-03"]}
    with pytest.raises(PriceFetchError, match=r"no completed weekly bars"):
        prices.parse_weekly_adjusted(body, "IBM", TODAY)


@pytest.mark.parametrize("bad", ["", "n/a", "0.0000", "-1.0"])
def test_unusable_adjusted_close_hard_fails(bad):
    body = payload()
    body["Weekly Adjusted Time Series"]["2026-07-31"]["5. adjusted close"] = bad
    with pytest.raises(PriceFetchError, match=r"2026-07-31"):
        prices.parse_weekly_adjusted(body, "IBM", TODAY)


def test_missing_adjusted_close_field_hard_fails():
    body = payload()
    del body["Weekly Adjusted Time Series"]["2026-07-31"]["5. adjusted close"]
    with pytest.raises(PriceFetchError, match=r"5\. adjusted close"):
        prices.parse_weekly_adjusted(body, "IBM", TODAY)


def test_unparseable_bar_date_hard_fails():
    body = payload()
    row = body["Weekly Adjusted Time Series"].pop("2026-07-31")
    body["Weekly Adjusted Time Series"]["last week"] = row
    with pytest.raises(PriceFetchError, match=r"last week"):
        prices.parse_weekly_adjusted(body, "IBM", TODAY)


# --- key handling -----------------------------------------------------------


def test_missing_api_key_hard_fails(monkeypatch):
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    with pytest.raises(PriceFetchError, match=r"ALPHAVANTAGE_API_KEY"):
        prices._require_api_key()


def test_blank_api_key_hard_fails(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "   ")
    with pytest.raises(PriceFetchError, match=r"ALPHAVANTAGE_API_KEY"):
        prices._require_api_key()


def test_network_failure_never_echoes_the_key(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", FAKE_KEY)

    def boom(symbol, api_key):
        # urllib repeats the request URL in its error text, key and all.
        raise OSError(f"HTTP Error 500: apikey={FAKE_KEY}")

    monkeypatch.setattr(prices, "_av_get_json", boom)
    with pytest.raises(PriceFetchError) as excinfo:
        prices.fetch_price_snapshot("IBM", today=TODAY)
    assert FAKE_KEY not in str(excinfo.value)
    assert "IBM" in str(excinfo.value)


def test_information_body_error_never_echoes_the_key(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", FAKE_KEY)
    monkeypatch.setattr(
        prices,
        "_av_get_json",
        lambda symbol, api_key: {"Information": "premium endpoint"},
    )
    with pytest.raises(PriceFetchError) as excinfo:
        prices.fetch_price_snapshot("IBM", today=TODAY)
    assert FAKE_KEY not in str(excinfo.value)


# --- fetch ------------------------------------------------------------------


def test_fetch_price_snapshot_happy_path(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "K")
    monkeypatch.setattr(prices, "_av_get_json", lambda symbol, api_key: payload())
    snap = prices.fetch_price_snapshot("ibm", today=TODAY)
    assert snap["ticker"] == "IBM"
    assert snap["last_complete_week"] == "2026-07-31"


def test_fetch_rejects_a_vendor_series_missing_the_last_completed_week(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "K")
    body = payload()
    for stale in ("2026-08-03", "2026-07-31"):
        del body["Weekly Adjusted Time Series"][stale]
    monkeypatch.setattr(prices, "_av_get_json", lambda symbol, api_key: body)
    with pytest.raises(PriceFetchError, match=r"stale"):
        prices.fetch_price_snapshot("IBM", today=TODAY)


def test_allow_stale_accepts_a_lagging_vendor_series(monkeypatch):
    # Without the hatch a vendor that has not yet published the completed week
    # would leave a first-time ticker unpinnable and fail the whole basket.
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "K")
    body = payload()
    for lagging in ("2026-08-03", "2026-07-31"):
        del body["Weekly Adjusted Time Series"][lagging]
    monkeypatch.setattr(prices, "_av_get_json", lambda symbol, api_key: body)
    snap = prices.fetch_price_snapshot("IBM", today=TODAY, allow_stale=True)
    assert snap["last_complete_week"] == "2026-07-24"


def test_price_failures_are_catchable_as_fetch_failures():
    from whale_engine.errors import FetchError

    assert issubclass(PriceFetchError, FetchError)


# --- weekly freshness gate --------------------------------------------------


def test_snapshot_is_fresh_until_the_next_week_closes():
    snap = prices.parse_weekly_adjusted(payload(), "IBM", TODAY)
    # Fetched Tuesday; no new weekly close lands before Friday, so no refetch.
    assert prices.is_fresh(snap, date(2026, 8, 4))
    assert prices.is_fresh(snap, date(2026, 8, 7))


def test_snapshot_goes_stale_once_a_new_week_completes():
    snap = prices.parse_weekly_adjusted(payload(), "IBM", TODAY)
    # Saturday 2026-08-08 onward: the week of 08-03 has closed.
    assert not prices.is_fresh(snap, date(2026, 8, 8))
    assert not prices.is_fresh(snap, date(2026, 8, 10))


def test_freshness_ignores_the_fetch_timestamp():
    snap = prices.parse_weekly_adjusted(payload(), "IBM", TODAY)
    snap["fetched_at"] = "1999-01-01"  # gate reads the weekly close, not this
    assert prices.is_fresh(snap, date(2026, 8, 5))


# --- snapshot store ---------------------------------------------------------


def test_ensure_writes_then_reuses_a_fresh_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "K")
    calls = []

    def seam(symbol, api_key):
        calls.append(symbol)
        return payload()

    monkeypatch.setattr(prices, "_av_get_json", seam)

    path, snap, action = prices.ensure_price_snapshot("IBM", tmp_path, today=TODAY)
    assert action == "fetched"
    assert path == tmp_path / "IBM-2026-08-04.json"
    assert path.exists()

    # Same week, no second request.
    path2, snap2, action2 = prices.ensure_price_snapshot(
        "IBM", tmp_path, today=date(2026, 8, 7)
    )
    assert action2 == "reused"
    assert path2 == path
    assert snap2 == snap
    assert calls == ["IBM"]


def test_ensure_refetches_once_the_snapshot_predates_the_last_close(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "K")
    calls = []

    def seam(symbol, api_key):
        calls.append(symbol)
        return payload()

    monkeypatch.setattr(prices, "_av_get_json", seam)
    prices.ensure_price_snapshot("IBM", tmp_path, today=TODAY)

    # Next week the vendor has the 08-07 bar; the old snapshot is stale.
    later = payload()
    later["Weekly Adjusted Time Series"]["2026-08-07"] = dict(
        later["Weekly Adjusted Time Series"]["2026-07-31"]
    )
    later["Weekly Adjusted Time Series"]["2026-08-10"] = dict(
        later["Weekly Adjusted Time Series"]["2026-08-03"]
    )
    del later["Weekly Adjusted Time Series"]["2026-08-03"]
    monkeypatch.setattr(prices, "_av_get_json", lambda symbol, api_key: later)

    path, snap, action = prices.ensure_price_snapshot(
        "IBM", tmp_path, today=date(2026, 8, 11)
    )
    assert action == "fetched"
    assert snap["last_complete_week"] == "2026-08-07"
    assert path == tmp_path / "IBM-2026-08-11.json"
    assert calls == ["IBM"]


def test_allow_stale_reuses_without_a_request(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "K")
    monkeypatch.setattr(prices, "_av_get_json", lambda symbol, api_key: payload())
    prices.ensure_price_snapshot("IBM", tmp_path, today=TODAY)

    def boom(symbol, api_key):
        raise AssertionError("must not fetch under --stale-ok")

    monkeypatch.setattr(prices, "_av_get_json", boom)
    path, snap, action = prices.ensure_price_snapshot(
        "IBM", tmp_path, today=date(2026, 9, 1), allow_stale=True
    )
    assert action == "reused-stale"
    assert snap["last_complete_week"] == "2026-07-31"


def test_allow_stale_without_a_snapshot_still_hard_fails(tmp_path, monkeypatch):
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    with pytest.raises(PriceFetchError, match=r"ALPHAVANTAGE_API_KEY"):
        prices.ensure_price_snapshot("IBM", tmp_path, today=TODAY, allow_stale=True)


def test_force_refetches_a_fresh_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "K")
    calls = []

    def seam(symbol, api_key):
        calls.append(symbol)
        return payload()

    monkeypatch.setattr(prices, "_av_get_json", seam)
    prices.ensure_price_snapshot("IBM", tmp_path, today=TODAY)
    _, _, action = prices.ensure_price_snapshot("IBM", tmp_path, today=TODAY, force=True)
    assert action == "fetched"
    assert calls == ["IBM", "IBM"]


def test_written_snapshot_reads_back_byte_identical(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "K")
    monkeypatch.setattr(prices, "_av_get_json", lambda symbol, api_key: payload())
    path, snap, _ = prices.ensure_price_snapshot("IBM", tmp_path, today=TODAY)
    first = path.read_text()
    reloaded = prices.load_price_snapshot(path)
    assert reloaded == snap
    path.write_text(prices.dump_price_snapshot(reloaded))
    assert path.read_text() == first


def test_load_rejects_a_foreign_schema_version(tmp_path):
    bad = tmp_path / "IBM-2026-08-04.json"
    bad.write_text(json.dumps({"schema_version": 99, "ticker": "IBM"}))
    with pytest.raises(PriceFetchError, match=r"schema_version"):
        prices.load_price_snapshot(bad)


def test_latest_snapshot_picks_the_newest_by_date(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "K")
    monkeypatch.setattr(prices, "_av_get_json", lambda symbol, api_key: payload())
    prices.ensure_price_snapshot("IBM", tmp_path, today=TODAY)
    (tmp_path / "IBM-2026-07-28.json").write_text("{}")
    assert prices.latest_price_snapshot_path("IBM", tmp_path) == (
        tmp_path / "IBM-2026-08-04.json"
    )
    assert prices.latest_price_snapshot_path("MSFT", tmp_path) is None
