"""Networked phase 2: Alpha Vantage weekly-adjusted price history -> pinned snapshots.

Vendor pinned by the price-history vendor research (vendor research,
`research/price-history-vendor-2026.md`): Alpha Vantage free tier,
`TIME_SERIES_WEEKLY_ADJUSTED` — one request per ticker returns the full
history (IBM: 1396 weekly bars back to 1999). Methodology v1 consumes
weekly *adjusted* closes; `4. close` is unadjusted and would fabricate
correlation across a split.

Three rules this module exists to enforce:

1. **Hard-fail on the 200-with-`Information` body.** A free key hitting a
   premium endpoint, or any key over the 25-requests/day cap, gets HTTP 200
   with an `Information` (or `Note`/`Error Message`) JSON body and no time
   series. Any response lacking the time-series key is a hard failure, never
   empty data.

2. **Drop the in-progress week.** Weekly bars are dated on the *last trading
   day of the week* — Friday usually, Thursday in holiday weeks, and the
   newest bar is dated on whatever day the current, incomplete week has
   reached so far. Including it makes correlations non-deterministic: the bar
   keeps moving until the week closes. Only completed weeks are stored, and a
   bar's date is always read, never derived arithmetically.

3. **Weekly freshness gate, not same-day.** The EDGAR same-day gate
   (same-day fetch rule) does not transfer: a weekly series only changes weekly, and the free
   tier is 25 requests/day at one request per ticker, so a same-day gate would
   burn 15 of 25 on every re-run of a 15-name basket. A snapshot is fresh iff
   it already contains the most recently completed weekly bar; the snapshot
   records `last_complete_week_start`, the weekly close the gate compares
   against. `allow_stale` is the explicit-user-say-so escape hatch.

The API key comes from $ALPHAVANTAGE_API_KEY (same client-config pattern as
EDGAR_IDENTITY) and is never echoed — not in URLs, not in error messages.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

from .errors import FetchError

VENDOR = "Alpha Vantage"
SERIES = "TIME_SERIES_WEEKLY_ADJUSTED"
API_URL = "https://www.alphavantage.co/query"
API_KEY_ENV = "ALPHAVANTAGE_API_KEY"
TIME_SERIES_KEY = "Weekly Adjusted Time Series"
ADJUSTED_CLOSE_FIELD = "5. adjusted close"
PRICE_SCHEMA_VERSION = 1

# Free tier caps burst rate as well as daily volume ("1 request per second"):
# a basket fetched back-to-back fails on the second ticker. Paced with margin.
BURST_PAUSE_SECONDS = 2.0

# Vendor keys that carry a human-readable failure reason on a 200 response.
_MESSAGE_KEYS = ("Information", "Note", "Error Message")


class PriceFetchError(FetchError):
    """Alpha Vantage price history could not be fetched or trusted."""


def _require_api_key() -> str:
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise PriceFetchError(
            f"{API_KEY_ENV} is not set. Alpha Vantage price history needs a key "
            f"(free, instant signup at https://www.alphavantage.co/support/), "
            f'e.g. export {API_KEY_ENV}="YOUR_KEY"'
        )
    return key


# --- week boundaries --------------------------------------------------------


def _today() -> date:
    """Clock seam: pinned by tests so snapshot names stay deterministic."""
    return date.today()


def _pause(seconds: float) -> None:
    """Sleep seam: stubbed by tests so pacing costs no wall-clock time."""
    import time

    time.sleep(seconds)


def week_start(day: date) -> date:
    """Monday of the calendar week containing `day`."""
    return day - timedelta(days=day.weekday())


def last_completed_week_start(today: date) -> date:
    """Monday of the most recently *completed* trading week.

    A week has completed once its Friday has passed, so from Saturday onward
    the current calendar week counts as complete; Monday through Friday the
    most recent completed week is the previous one. (A Friday-evening fetch is
    therefore treated conservatively as still in progress: the engine has no
    way to know from a date alone whether the session has closed, and pinning
    a bar that can still move would break determinism.)

    Calendar arithmetic on week boundaries only — never on bar dates, which
    are read verbatim (47 of IBM's 1396 bars are Thursdays, and a
    holiday-shortened week's final bar is simply dated earlier).
    """
    this_week = week_start(today)
    if today.weekday() >= 5:  # Saturday or Sunday: Friday has passed
        return this_week
    return this_week - timedelta(days=7)


# --- network seam -----------------------------------------------------------


def _av_get_json(symbol: str, api_key: str) -> dict:
    """One keyed GET against Alpha Vantage. Network seam for tests.

    The key rides in the query string, so nothing built here — URL included —
    may reach a log or an exception message.
    """
    import urllib.parse
    import urllib.request

    query = urllib.parse.urlencode(
        {"function": SERIES, "symbol": symbol, "apikey": api_key}
    )
    req = urllib.request.Request(
        f"{API_URL}?{query}", headers={"User-Agent": "whale-engine price fetch"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


# --- parser -----------------------------------------------------------------


def _vendor_message(payload: dict) -> str | None:
    for key in _MESSAGE_KEYS:
        value = payload.get(key)
        if value:
            return f"{key}: {value}"
    return None


def parse_weekly_adjusted(payload: dict, ticker: str, today: date) -> dict:
    """Vendor payload -> price snapshot dict. Hard-fails on anything unusable.

    Pure and offline: same payload + same `today` -> same snapshot.
    """
    ticker = ticker.upper()
    if not isinstance(payload, dict):
        raise PriceFetchError(
            f"{ticker}: {VENDOR} returned {type(payload).__name__}, expected a JSON object."
        )

    series = payload.get(TIME_SERIES_KEY)
    if not isinstance(series, dict):
        message = _vendor_message(payload)
        raise PriceFetchError(
            f"{ticker}: {VENDOR} response carries no '{TIME_SERIES_KEY}' "
            f"({SERIES}) — "
            + (
                f"vendor said [{message}]"
                if message
                else f"keys present: {sorted(payload)}"
            )
            + ". Treated as a hard failure, never as empty data."
        )
    if not series:
        raise PriceFetchError(f"{ticker}: {VENDOR} returned no weekly bars.")

    meta = payload.get("Meta Data") or {}
    symbol = str(meta.get("2. Symbol", "")).upper()
    if symbol and symbol != ticker:
        raise PriceFetchError(
            f"{ticker}: {VENDOR} answered with symbol {symbol!r} — refusing a "
            f"series that does not belong to {ticker}."
        )

    # Bars belonging to a week that has not finished yet are in progress: the
    # newest one keeps moving until its week closes, so it can never enter a
    # correlation.
    cutoff = last_completed_week_start(today)
    complete: list[dict] = []
    partial: list[str] = []
    for raw_date, row in series.items():
        try:
            bar_date = date.fromisoformat(str(raw_date))
        except ValueError:
            raise PriceFetchError(
                f"{ticker}: {VENDOR} bar has an unparseable date {raw_date!r}."
            ) from None
        if week_start(bar_date) > cutoff:
            partial.append(bar_date.isoformat())
            continue
        if not isinstance(row, dict) or ADJUSTED_CLOSE_FIELD not in row:
            raise PriceFetchError(
                f"{ticker}: {VENDOR} bar {bar_date.isoformat()} has no "
                f"'{ADJUSTED_CLOSE_FIELD}' field."
            )
        try:
            close = float(row[ADJUSTED_CLOSE_FIELD])
        except (TypeError, ValueError):
            raise PriceFetchError(
                f"{ticker}: {VENDOR} bar {bar_date.isoformat()} has a "
                f"non-numeric adjusted close {row[ADJUSTED_CLOSE_FIELD]!r}."
            ) from None
        if not close > 0:
            raise PriceFetchError(
                f"{ticker}: {VENDOR} bar {bar_date.isoformat()} has a "
                f"non-positive adjusted close {close!r}."
            )
        complete.append({"date": bar_date.isoformat(), "adjusted_close": close})

    if not complete:
        raise PriceFetchError(
            f"{ticker}: {VENDOR} returned no completed weekly bars "
            f"(all {len(partial)} bar(s) fall after the last completed week, "
            f"which starts {cutoff.isoformat()})."
        )

    complete.sort(key=lambda row: row["date"])
    last_bar = date.fromisoformat(complete[-1]["date"])

    return {
        "schema_version": PRICE_SCHEMA_VERSION,
        "ticker": ticker,
        "fetched_at": today.isoformat(),
        "vendor": VENDOR,
        "series": SERIES,
        "last_refreshed": meta.get("3. Last Refreshed"),
        # Read from the data, never derived: holiday weeks close on Thursday.
        "last_complete_week": last_bar.isoformat(),
        # What the weekly freshness gate compares against.
        "last_complete_week_start": week_start(last_bar).isoformat(),
        # In-progress bars, recorded so their exclusion is auditable.
        "partial_bars_dropped": sorted(partial),
        "observations": len(complete),
        "weekly_adjusted_close": complete,  # oldest first
    }


# --- fetch ------------------------------------------------------------------


def fetch_price_snapshot(
    ticker: str, today: date | None = None, *, allow_stale: bool = False, pace: bool = False
) -> dict:
    """One vendor request -> a validated price snapshot for `ticker`.

    `allow_stale` accepts a vendor series that has not yet published the most
    recently completed week (the same explicit-say-so hatch that reuses a
    stale snapshot) — otherwise a lagging vendor is a hard failure, because
    silently pinning last week's data would refetch on every later run and
    burn the 25-requests/day cap without ever saying why.

    `pace` waits out the free tier's ~1-request/second burst limit before the
    call: a basket fetched back-to-back otherwise gets an `Information` body
    ("spread out your free API requests more sparingly") on the second ticker
    and fails the whole run.
    """
    ticker = ticker.upper()
    today = today or _today()
    key = _require_api_key()

    if pace:
        _pause(BURST_PAUSE_SECONDS)

    try:
        payload = _av_get_json(ticker, key)
    except Exception as e:
        # Never surface the exception text: a urllib error repeats the URL,
        # and the URL carries the API key.
        raise PriceFetchError(
            f"{ticker}: {VENDOR} request failed ({type(e).__name__}). "
            f"Check the ticker symbol and network, then retry."
        ) from None

    snapshot = parse_weekly_adjusted(payload, ticker, today)

    expected = last_completed_week_start(today)
    actual = date.fromisoformat(snapshot["last_complete_week_start"])
    if actual < expected and not allow_stale:
        raise PriceFetchError(
            f"{ticker}: {VENDOR} series is stale — newest completed bar is "
            f"{snapshot['last_complete_week']} (week of {actual.isoformat()}), "
            f"but the week of {expected.isoformat()} has already closed."
        )
    return snapshot


# --- snapshot store ---------------------------------------------------------


def format_snapshot_line(snapshot: dict, path: Path, action: str) -> str:
    """One tab-separated CLI line per ticker (cf. holdings' markdown formatter):
    the display shape of a price snapshot belongs with the snapshot."""
    return (
        f"{snapshot['ticker']}\t{action}\tweek of {snapshot['last_complete_week']}"
        f"\t{snapshot['observations']} bars\t{path}"
    )


def dump_price_snapshot(snapshot: dict) -> str:
    return json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def snapshot_filename(ticker: str, fetched_at: str) -> str:
    return f"{ticker.upper()}-{fetched_at}.json"


def latest_price_snapshot_path(ticker: str, prices_dir: Path) -> Path | None:
    """Newest snapshot on disk for `ticker`, or None. ISO names sort by date."""
    candidates = sorted(Path(prices_dir).glob(f"{ticker.upper()}-*.json"))
    return candidates[-1] if candidates else None


def load_price_snapshot(path: Path) -> dict:
    snapshot = json.loads(Path(path).read_text(encoding="utf-8"))
    version = snapshot.get("schema_version")
    if version != PRICE_SCHEMA_VERSION:
        raise PriceFetchError(
            f"{path}: price snapshot schema_version {version!r}, expected "
            f"{PRICE_SCHEMA_VERSION} — refetch with `whale prices`."
        )
    return snapshot


def is_fresh(snapshot: dict, today: date) -> bool:
    """Fresh iff the snapshot already holds the most recently completed week.

    Deliberately ignores `fetched_at`: what matters is which weekly close the
    data reaches, not when it was downloaded.
    """
    return (
        date.fromisoformat(snapshot["last_complete_week_start"])
        >= last_completed_week_start(today)
    )


def ensure_price_snapshot(
    ticker: str,
    prices_dir: Path,
    today: date | None = None,
    *,
    force: bool = False,
    allow_stale: bool = False,
    pace: bool = False,
) -> tuple[Path, dict, str]:
    """Fresh snapshot for `ticker` on disk. Returns (path, snapshot, action).

    action is "reused" (fresh on disk, no request), "reused-stale" (explicit
    `allow_stale` over a stale snapshot), or "fetched".

    `pace` waits out the vendor's burst limit, but only if a request is
    actually needed: reusing a pinned snapshot stays instant.
    """
    ticker = ticker.upper()
    today = today or _today()
    prices_dir = Path(prices_dir)

    existing = latest_price_snapshot_path(ticker, prices_dir)
    if existing is not None and not force:
        snapshot = load_price_snapshot(existing)
        if is_fresh(snapshot, today):
            return existing, snapshot, "reused"
        if allow_stale:
            return existing, snapshot, "reused-stale"

    snapshot = fetch_price_snapshot(ticker, today, allow_stale=allow_stale, pace=pace)
    prices_dir.mkdir(parents=True, exist_ok=True)
    path = prices_dir / snapshot_filename(ticker, snapshot["fetched_at"])
    path.write_text(dump_price_snapshot(snapshot), encoding="utf-8")
    return path, snapshot, "fetched"
