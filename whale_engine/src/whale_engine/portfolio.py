"""Offline portfolio layer: pinned snapshots -> one deterministic basket report.

Implements methodology v1 and report contract v1.

What this layer is, and is not: the whales say which companies are worth
owning; this layer says whether a basket the *client* chose actually spreads
risk, and how much of each name to hold. Equal weight, no optimizer, no
expected-return estimates (DeMiguel/Garlappi/Uppal 2009). It never picks
or rejects a ticker, and the whales endorse neither the method nor the mix.

Determinism contract, same as every scorer: pure function of the pinned
snapshots handed in — no network, no clock, no randomness. `whale prices` owns
freshness (the weekly gate, report contract v1 §7); this module owns arithmetic. A report
therefore always says which snapshot vintages it read, and re-running it
against those same files reproduces the bytes forever, whatever day it is.

Locked numbers (methodology v1 — changing any of them requires an owner-signed
review, the rubric-v2 precedent, and a version bump):

- weekly log returns from `5. adjusted close`, 3-year lookback (methodology v1 §1)
- Pearson correlation, "same bet" flag at >= 0.80 (methodology v1 §2)
- EDGAR SIC 2-digit major groups, concentration flag above 40% of names (methodology v1 §3)
- 52-week floor; below it a name is weighted normally, its pairs are null, and
  a first-class warning names it (methodology v1 §4, report contract v1 §4)
- basket of 2-15 tickers inclusive; outside that, hard fail (methodology v1 §5)

Sector source per name: the full EDGAR snapshot when one exists, else
the sector-only snapshot in `snapshots/sectors/` — the same SIC field, fetched
alone, for a name too young for the fundamentals depth `whale fetch` demands.
`provenance.edgar_snapshots[].source` records which. Without that route a
recent IPO killed the whole report, and the insufficient-history path below
could not fire on any real name.

Dates in `correlation.window` are **week-start Mondays**, the keys weeks are
compared by — a bar filed on Friday 2026-07-31 belongs to the week starting
2026-07-27. Bar dates themselves are always read from the vendor, never
derived: holiday weeks close on a Thursday. Narration should therefore say
"week of <date>", never "as of <date>".
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path

from .fetch import SECTOR_SCHEMA_VERSION, SECTOR_SNAPSHOT_KIND
from .prices import SERIES, VENDOR, load_price_snapshot
from .sic_groups import major_group_title

METHODOLOGY_VERSION = "1.0"

MIN_BASKET = 2
MAX_BASKET = 15
LOOKBACK_WEEKS = 156
MIN_HISTORY_WEEKS = 52
SAME_BET_THRESHOLD = 0.80
SECTOR_CONCENTRATION_THRESHOLD = 0.40

# Correlations are rounded before the flag test, so the published figure and
# the flag can never disagree (a printed 0.80 that did not flag would look
# like a bug and read as one).
RHO_DECIMALS = 4
SHARE_DECIMALS = 4

# The honesty mandate, pinned verbatim (report contract v1 §3): the skill reproduces this
# string word for word and may not soften, shorten or paraphrase it. Wording
# versions with the methodology; owner review covers the wording.
RESIDUAL_RISK_CAVEAT = (
    "Equal weighting and low pairwise correlation spread company-specific risk. "
    "They do not remove market risk: in a broad decline these positions can fall "
    "together regardless of anything in this report. Correlations are measured on "
    "past weekly returns and change without warning — they describe what has "
    "happened, not what will. This report sizes a basket you chose and is not "
    "investment advice; the whales whose verdicts picked these names endorse "
    "neither this method nor the resulting mix."
)


class PortfolioError(ValueError):
    """The basket or its pinned inputs cannot produce a trustworthy report."""


# --- basket -----------------------------------------------------------------


def normalize_basket(tickers: list[str]) -> list[str]:
    """Uppercased basket, order preserved. Hard-fails on size and duplicates."""
    basket = [t.strip().upper() for t in tickers]
    if any(not t for t in basket):
        raise PortfolioError("basket contains an empty ticker.")

    seen: set[str] = set()
    duplicates = sorted({t for t in basket if t in seen or seen.add(t)})
    if duplicates:
        raise PortfolioError(
            f"basket repeats {', '.join(duplicates)} — equal weighting a name "
            f"twice silently doubles it; list each ticker once."
        )
    if not MIN_BASKET <= len(basket) <= MAX_BASKET:
        raise PortfolioError(
            f"basket has {len(basket)} ticker(s); methodology v1 allows "
            f"{MIN_BASKET}-{MAX_BASKET} inclusive. One name is not a portfolio, "
            f"and more than {MAX_BASKET} cannot be priced inside the vendor's "
            f"free 25-requests/day cap."
        )
    return basket


# --- returns ----------------------------------------------------------------


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _weekly_closes(snapshot: dict) -> dict[date, float]:
    """Snapshot bars keyed by the Monday of their week.

    Bar dates are read verbatim — a holiday week closes on Thursday — and the
    Monday key is what makes two tickers' weeks comparable.
    """
    bars = snapshot.get("weekly_adjusted_close")
    if not isinstance(bars, list) or not bars:
        raise PortfolioError(
            f"{snapshot.get('ticker')}: price snapshot carries no weekly bars."
        )
    closes: dict[date, float] = {}
    for bar in bars:
        try:
            bar_date = date.fromisoformat(str(bar["date"]))
            close = float(bar["adjusted_close"])
        except (KeyError, TypeError, ValueError):
            raise PortfolioError(
                f"{snapshot.get('ticker')}: unusable price bar {bar!r}."
            ) from None
        if not close > 0:
            raise PortfolioError(
                f"{snapshot.get('ticker')}: non-positive adjusted close in bar {bar!r}."
            )
        closes[_week_start(bar_date)] = close
    return closes


def _log_returns(closes: dict[date, float], window: list[date]) -> dict[date, float]:
    """Weekly log returns inside `window`, keyed by the week they land in.

    A return exists only where the immediately preceding calendar week also has
    a bar. A gap in the vendor series therefore drops one observation instead of
    fabricating a two-week move labelled as a weekly one.
    """
    returns: dict[date, float] = {}
    for week in window:
        previous = week - timedelta(days=7)
        if week in closes and previous in closes:
            returns[week] = math.log(closes[week] / closes[previous])
    return returns


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation, or None when either series cannot vary."""
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    dx = [x - mean_x for x in xs]
    dy = [y - mean_y for y in ys]
    var_x = sum(d * d for d in dx)
    var_y = sum(d * d for d in dy)
    if var_x <= 0 or var_y <= 0:
        return None
    return sum(a * b for a, b in zip(dx, dy)) / math.sqrt(var_x * var_y)


def _pair_key(a: str, b: str) -> str:
    left, right = sorted((a, b))
    return f"{left}|{right}"


# --- report -----------------------------------------------------------------


def _correlation_block(
    basket: list[str], price_snapshots: dict[str, dict], warnings: list[dict]
) -> dict:
    closes = {ticker: _weekly_closes(price_snapshots[ticker]) for ticker in basket}

    # One window for the whole report (report contract v1 §4: same window, or null — never a
    # per-name shortening). It ends at the newest week *every* snapshot reaches,
    # so a basket priced across two fetch days still compares like with like.
    end_week = min(max(weeks) for weeks in closes.values())
    start_week = end_week - timedelta(days=7 * LOOKBACK_WEEKS)
    # 157 weekly closes span 156 weekly returns: the window's first week
    # supplies the base price, not an observation of its own.
    window = [start_week + timedelta(days=7 * i) for i in range(1, LOOKBACK_WEEKS + 1)]

    returns = {ticker: _log_returns(closes[ticker], window) for ticker in basket}

    sufficient: list[str] = []
    for ticker in basket:
        count = len(returns[ticker])
        if count >= MIN_HISTORY_WEEKS:
            sufficient.append(ticker)
            continue
        warnings.append(
            {
                "ticker": ticker,
                "code": "insufficient_history",
                "message": (
                    f"{ticker} has {count} weekly return(s) inside the "
                    f"{LOOKBACK_WEEKS}-week window, below the "
                    f"{MIN_HISTORY_WEEKS}-week floor. It is weighted normally, "
                    f"but every correlation involving it is reported as null "
                    f"rather than measured over a shortened window."
                ),
            }
        )

    matrix: dict[str, float | None] = {}
    observations: dict[str, int] = {}
    flagged_pairs: list[dict] = []
    for i, a in enumerate(basket):
        for b in basket[i + 1 :]:
            key = _pair_key(a, b)
            if a not in sufficient or b not in sufficient:
                matrix[key] = None
                observations[key] = 0
                continue
            weeks = sorted(set(returns[a]) & set(returns[b]))
            observations[key] = len(weeks)
            if len(weeks) < MIN_HISTORY_WEEKS:
                matrix[key] = None
                warnings.append(
                    {
                        "pair": sorted((a, b)),
                        "code": "insufficient_overlap",
                        "message": (
                            f"{a} and {b} share only {len(weeks)} weekly return(s) "
                            f"in the window, below the {MIN_HISTORY_WEEKS}-week "
                            f"floor; their correlation is unknown."
                        ),
                    }
                )
                continue
            rho = _pearson([returns[a][w] for w in weeks], [returns[b][w] for w in weeks])
            if rho is None:
                matrix[key] = None
                warnings.append(
                    {
                        "pair": sorted((a, b)),
                        "code": "zero_variance",
                        "message": (
                            f"{a} or {b} never moved across the window, so no "
                            f"correlation is defined for the pair."
                        ),
                    }
                )
                continue
            rho = round(rho, RHO_DECIMALS)
            matrix[key] = rho
            if rho >= SAME_BET_THRESHOLD:
                flagged_pairs.append({"pair": sorted((a, b)), "rho": rho})

    flagged_pairs.sort(key=lambda entry: (-entry["rho"], entry["pair"]))

    # The window the full-history pairs actually used: weeks with a return for
    # every name that cleared the floor.
    if sufficient:
        common = set.intersection(*(set(returns[t]) for t in sufficient))
    else:
        common = set()

    return {
        "matrix": dict(sorted(matrix.items())),
        "observations": dict(sorted(observations.items())),
        "flagged_pairs": flagged_pairs,
        "window": {
            "start": start_week.isoformat(),
            "end": end_week.isoformat(),
            "observations": len(common),
        },
    }


def _sector_block(
    basket: list[str], edgar_snapshots: dict[str, dict], warnings: list[dict]
) -> dict:
    members: dict[str | None, list[str]] = {}
    for ticker in basket:
        snapshot = edgar_snapshots[ticker]
        sic = snapshot.get("sic")
        if "sic" not in snapshot:
            warnings.append(
                {
                    "ticker": ticker,
                    "code": "sic_field_absent",
                    "message": (
                        f"{ticker}'s EDGAR snapshot predates the SIC fields — "
                        f"refetch it (`whale fetch {ticker}`) to place the name "
                        f"in a sector group."
                    ),
                }
            )
            sic = None
        elif not sic:
            warnings.append(
                {
                    "ticker": ticker,
                    "code": "sector_unavailable",
                    "message": (
                        f"EDGAR publishes no SIC code for {ticker}; it is weighted "
                        f"normally but belongs to no sector group, so sector "
                        f"concentration is measured without it."
                    ),
                }
            )
            sic = None
        members.setdefault(str(sic)[:2] if sic else None, []).append(ticker)

    total = len(basket)
    groups: list[dict] = []
    flagged_groups: list[str] = []
    for sic2, tickers in members.items():
        share = round(len(tickers) / total, SHARE_DECIMALS)
        # An unknown sector is not a concentration: it is a gap, already
        # warned about above, and flagging it would invent a sector bet.
        flagged = sic2 is not None and share > SECTOR_CONCENTRATION_THRESHOLD
        groups.append(
            {
                "sic2": sic2,
                "desc": major_group_title(sic2) if sic2 else None,
                "tickers": sorted(tickers),
                "share": share,
                "flagged": flagged,
            }
        )
        if flagged:
            flagged_groups.append(sic2)

    groups.sort(key=lambda g: (-g["share"], g["sic2"] or "~"))
    return {"groups": groups, "flagged_groups": sorted(flagged_groups)}


def build_report(
    tickers: list[str],
    price_snapshots: dict[str, dict],
    edgar_snapshots: dict[str, dict],
) -> dict:
    """Pinned snapshots -> the portfolio report of contract v1.

    `price_snapshots` and `edgar_snapshots` must cover every basket ticker; a
    missing one is the caller's hard failure, not a degraded report.
    """
    basket = normalize_basket(tickers)

    missing_prices = [t for t in basket if t not in price_snapshots]
    if missing_prices:
        raise PortfolioError(
            f"no pinned price history for {', '.join(missing_prices)} — run "
            f"`whale prices {' '.join(missing_prices)}` first."
        )
    missing_edgar = [t for t in basket if t not in edgar_snapshots]
    if missing_edgar:
        raise PortfolioError(
            f"no EDGAR sector source for {', '.join(missing_edgar)} — run "
            f"`whale fetch TICKER`, or `whale fetch TICKER --sector-only` for a "
            f"name too young for a full fundamentals snapshot; the sector check "
            f"reads its SIC code."
        )

    weight = 1 / len(basket)
    warnings: list[dict] = []
    correlation = _correlation_block(basket, price_snapshots, warnings)
    sectors = _sector_block(basket, edgar_snapshots, warnings)

    return {
        "portfolio_methodology_version": METHODOLOGY_VERSION,
        "basket": [{"ticker": t, "weight": weight} for t in basket],
        "correlation": correlation,
        "sectors": sectors,
        "warnings": warnings,
        "caveats": [RESIDUAL_RISK_CAVEAT],
        "provenance": {
            "vendor": VENDOR,
            "series": SERIES,
            "snapshots": [
                {
                    "ticker": t,
                    "snapshot_date": price_snapshots[t]["fetched_at"],
                    "last_complete_week": price_snapshots[t]["last_complete_week"],
                }
                for t in basket
            ],
            # `source` says which artifact the SIC came from: a full
            # `whale fetch` snapshot, or the sector-only lookup a name too
            # young for one gets. The code itself is the same EDGAR
            # submissions field either way — the field records that a
            # sector-only name has no pinned fundamentals behind it.
            "edgar_snapshots": [
                {
                    "ticker": t,
                    "snapshot_date": edgar_snapshots[t].get("fetched_at"),
                    "source": (
                        SECTOR_SNAPSHOT_KIND
                        if edgar_snapshots[t].get("kind") == SECTOR_SNAPSHOT_KIND
                        else "fetch"
                    ),
                }
                for t in basket
            ],
        },
    }


# --- snapshot loading -------------------------------------------------------


def latest_edgar_snapshot_path(ticker: str, snapshots_dir: Path) -> Path | None:
    """Newest EDGAR snapshot for `ticker`, or None. ISO names sort by date."""
    candidates = sorted(Path(snapshots_dir).glob(f"{ticker.upper()}-*.json"))
    return candidates[-1] if candidates else None


def latest_sector_snapshot_path(ticker: str, sectors_dir: Path) -> Path | None:
    """Newest sector-only snapshot for `ticker`, or None."""
    candidates = sorted(Path(sectors_dir).glob(f"{ticker.upper()}-*.json"))
    return candidates[-1] if candidates else None


def load_sector_snapshot(path: Path) -> dict:
    """Read a sector-only snapshot, hard-failing on anything else.

    The checks exist because this file sits one directory away from the real
    snapshots: a stray copy in either direction must say so, not be scored or
    read as a sector source by accident.
    """
    import json

    path = Path(path)
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    if snapshot.get("kind") != SECTOR_SNAPSHOT_KIND:
        raise PortfolioError(
            f"{path}: not a sector-only snapshot (kind={snapshot.get('kind')!r}) — "
            f"sectors/ holds only `whale fetch --sector-only` output."
        )
    version = snapshot.get("schema_version")
    if version != SECTOR_SCHEMA_VERSION:
        raise PortfolioError(
            f"{path}: sector snapshot schema_version {version!r}, expected "
            f"{SECTOR_SCHEMA_VERSION} — refetch with `whale fetch "
            f"{snapshot.get('ticker', 'TICKER')} --sector-only`."
        )
    return snapshot


def load_basket_snapshots(
    basket: list[str], snapshots_dir: Path
) -> tuple[dict[str, dict], dict[str, dict]]:
    """Load the pinned price and EDGAR snapshots a basket needs, or hard-fail.

    Sector source per ticker: the full snapshot when one exists, else the
    sector-only snapshot. Full always wins — it is the same SIC field
    plus everything else, so a name that has been properly fetched never
    silently reads from the lightweight file.
    """
    snapshots_dir = Path(snapshots_dir)
    prices_dir = snapshots_dir / "prices"
    sectors_dir = snapshots_dir / "sectors"

    from .prices import latest_price_snapshot_path

    price_snapshots: dict[str, dict] = {}
    edgar_snapshots: dict[str, dict] = {}
    missing_prices: list[str] = []
    missing_edgar: list[str] = []
    for ticker in basket:
        price_path = latest_price_snapshot_path(ticker, prices_dir)
        if price_path is None:
            missing_prices.append(ticker)
        else:
            price_snapshots[ticker] = load_price_snapshot(price_path)

        edgar_path = latest_edgar_snapshot_path(ticker, snapshots_dir)
        if edgar_path is not None:
            import json

            snapshot = json.loads(edgar_path.read_text(encoding="utf-8"))
            if snapshot.get("kind") == SECTOR_SNAPSHOT_KIND:
                raise PortfolioError(
                    f"{edgar_path}: a sector-only snapshot is sitting in "
                    f"{snapshots_dir}/, where scorers look for fundamentals. "
                    f"Move it to {sectors_dir}/."
                )
            edgar_snapshots[ticker] = snapshot
            continue

        sector_path = latest_sector_snapshot_path(ticker, sectors_dir)
        if sector_path is None:
            missing_edgar.append(ticker)
        else:
            edgar_snapshots[ticker] = load_sector_snapshot(sector_path)

    if missing_prices:
        raise PortfolioError(
            f"no pinned price history in {prices_dir}/ for "
            f"{', '.join(missing_prices)} — run `whale prices "
            f"{' '.join(missing_prices)}` first."
        )
    if missing_edgar:
        raise PortfolioError(
            f"no EDGAR sector source in {snapshots_dir}/ or {sectors_dir}/ for "
            f"{', '.join(missing_edgar)} — run `whale fetch TICKER` for each, or "
            f"`whale fetch TICKER --sector-only` for a name too young to have "
            f"the fundamentals depth a full snapshot needs; the sector check "
            f"reads only its SIC code."
        )
    return price_snapshots, edgar_snapshots
