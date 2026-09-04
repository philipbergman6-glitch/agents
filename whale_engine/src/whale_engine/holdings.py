"""13F whale-holdings module: roster-wide fetch + offline report.

Two-phase, matching the fundamentals pipeline:

  whale fetch-13f            networked: latest two 13F periods per roster CIK
                             -> snapshots/13f/13f-{cik}-{period}.json
  whale holdings TICKER      offline: who holds it, position size, and what
                             each fund did last quarter (opened/added/trimmed/
                             exited/unchanged) from the pinned snapshots

The roster lives in whales_13f.json next to this module — data, not code.
Snapshots are whale-agnostic raw filing data; every number in a report comes
from a filing infotable. Ticker matching strips '-'/'.' (edgartools reports
BRKB where quote vendors say BRK-B); positions whose CUSIP never resolved to
a ticker are reachable via --cusip.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .thirteenf import (
    PortfolioSnapshot,
    ThirteenFError,
    _quarter_label,
    fetch_latest_snapshots,
    snapshot_from_dict,
    snapshot_to_dict,
)

ROSTER_PATH = Path(__file__).parent / "whales_13f.json"

CAVEATS = [
    "**45-day filing lag:** 13F filings are due up to 45 days after quarter end, "
    "so every position below is a quarter-end snapshot and may have changed since.",
    "13Fs cover **US-listed long positions only** — no shorts, no cash, no "
    "non-US-listed holdings; this is not any fund's complete book.",
    "Filers lag unevenly: each fund is reported against its own latest filed "
    "quarter (labelled per row) — they are not all the same date.",
    "Values are as reported in the filings (position value at quarter end, whole "
    "USD). Weights = position value / that fund's total reported 13F value. "
    "Nothing here is estimated.",
]


# ---------------------------------------------------------------------------
# Roster
# ---------------------------------------------------------------------------


@dataclass
class Whale:
    name: str
    cik: int
    filer: str
    note: str = ""


def load_roster(path: Path = ROSTER_PATH) -> list[Whale]:
    """Load and validate the whale roster. Hard-fails on any malformation."""
    if not path.exists():
        raise ThirteenFError(f"roster file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("whales")
    if not isinstance(entries, list) or not entries:
        raise ThirteenFError(f"roster {path} has no 'whales' list")
    whales: list[Whale] = []
    seen_ciks: set[int] = set()
    seen_names: set[str] = set()
    for entry in entries:
        for key in ("name", "cik", "filer"):
            if key not in entry:
                raise ThirteenFError(f"roster entry missing '{key}': {entry}")
        cik = int(entry["cik"])
        name = str(entry["name"])
        if cik in seen_ciks:
            raise ThirteenFError(f"duplicate CIK {cik} in roster")
        if name in seen_names:
            raise ThirteenFError(f"duplicate name {name!r} in roster")
        for sib in entry.get("sibling_ciks", []):
            if int(sib["cik"]) in seen_ciks:
                raise ThirteenFError(
                    f"sibling CIK {sib['cik']} of {name!r} duplicates a roster CIK "
                    "— siblings are tracked to avoid double-counting, never fetched"
                )
        seen_ciks.add(cik)
        seen_names.add(name)
        whales.append(Whale(name=name, cik=cik, filer=str(entry["filer"]),
                            note=str(entry.get("note", ""))))
    return whales


# ---------------------------------------------------------------------------
# fetch-13f (networked)
# ---------------------------------------------------------------------------


def snapshot_filename(cik: int, report_period: str) -> str:
    return f"13f-{cik}-{report_period}.json"


def fetch_roster(out_dir: Path, *, only: str | None = None,
                 roster_path: Path = ROSTER_PATH) -> list[str]:
    """Fetch latest-two 13F periods for every roster whale (or one, via
    `only`, exact roster name). Writes one pinned JSON per CIK+period;
    re-fetch overwrites, so a late 13F-HR/A replaces its period's file.

    Failures don't abort the roster sweep (one dead filer must not cost the
    other fifteen fetches) but are never silent: every failure is collected
    and raised at the end.
    """
    whales = load_roster(roster_path)
    if only is not None:
        whales = [w for w in whales if w.name == only]
        if not whales:
            names = ", ".join(w.name for w in load_roster(roster_path))
            raise ThirteenFError(f"no roster whale named {only!r}; roster: {names}")
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    failures: list[str] = []
    for whale in whales:
        try:
            snaps = fetch_latest_snapshots(whale.cik, periods=2)
        except Exception as e:  # collected, re-raised below — never silent
            failures.append(f"{whale.name} (CIK {whale.cik}): {type(e).__name__}: {e}")
            continue
        for snap in snaps:
            path = out_dir / snapshot_filename(whale.cik, snap.report_period)
            path.write_text(
                json.dumps(snapshot_to_dict(snap), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            written.append(str(path))
            print(f"{whale.name}: {snap.form} {snap.report_period} "
                  f"({len(snap.positions)} positions) -> {path}")
    if failures:
        raise ThirteenFError(
            "fetch-13f completed with failures:\n  " + "\n  ".join(failures)
        )
    return written


# ---------------------------------------------------------------------------
# holdings TICKER (offline)
# ---------------------------------------------------------------------------


def _norm_ticker(ticker: str) -> str:
    return ticker.upper().replace("-", "").replace(".", "").strip()


def load_fund_snapshots(cik: int, snapshots_dir: Path) -> list[PortfolioSnapshot]:
    """Latest-two pinned snapshots for a CIK, newest first (may be 0/1/2)."""
    paths = sorted(snapshots_dir.glob(f"13f-{cik}-*.json"), reverse=True)
    snaps = []
    for path in paths[:2]:  # ISO periods in names sort chronologically
        snap = snapshot_from_dict(json.loads(path.read_text(encoding="utf-8")))
        if snap.cik != cik:
            raise ThirteenFError(f"snapshot {path} claims CIK {snap.cik}, expected {cik}")
        snaps.append(snap)
    return snaps


@dataclass
class FundHolding:
    whale: Whale
    period: str  # fund's latest report period
    prior_period: str | None  # None when only one snapshot is on disk
    shares: int  # 0 when exited
    value: int
    weight: float  # value / fund total reported value (0 when exited)
    action: str  # opened | added | trimmed | exited | unchanged | held (no prior)


def _match_cusips(snaps: list[PortfolioSnapshot], *, ticker: str | None,
                  cusip: str | None) -> set[str]:
    matched: set[str] = set()
    for snap in snaps:
        for pos in snap.positions.values():
            if cusip is not None:
                if pos.cusip == cusip:
                    matched.add(pos.cusip)
            elif pos.ticker:
                if ticker is None:
                    raise ValueError("holdings scan needs a ticker or a CUSIP")
                if _norm_ticker(pos.ticker) == _norm_ticker(ticker):
                    matched.add(pos.cusip)
    return matched


def scan_holdings(
    ticker: str | None,
    snapshots_dir: Path,
    *,
    cusip: str | None = None,
    roster_path: Path = ROSTER_PATH,
) -> tuple[list[FundHolding], list[Whale], set[str], str]:
    """Cross-fund scan. Returns (holdings, funds-with-no-position,
    matched CUSIPs, display label for the security)."""
    if ticker is None and cusip is None:
        raise ThirteenFError("need a ticker or --cusip")
    whales = load_roster(roster_path)
    if not snapshots_dir.exists() or not any(snapshots_dir.glob("13f-*.json")):
        raise ThirteenFError(
            f"no 13F snapshots in {snapshots_dir}/ — run `whale fetch-13f` first"
        )
    per_fund = {w.cik: load_fund_snapshots(w.cik, snapshots_dir) for w in whales}
    all_snaps = [s for snaps in per_fund.values() for s in snaps]
    matched = _match_cusips(all_snaps, ticker=ticker, cusip=cusip)
    if not matched:
        wanted = cusip if cusip is not None else ticker
        raise ThirteenFError(
            f"{wanted!r} not found in any whale's latest-two 13F snapshots. "
            "Either no roster fund reported it, or its CUSIP never resolved to a "
            "ticker — try `--cusip` if you know it."
        )
    # Display label from any matched position (deterministic: lowest CUSIP,
    # newest snapshot first).
    label = ""
    for c in sorted(matched):
        for snap in sorted(all_snaps, key=lambda s: s.report_period, reverse=True):
            if c in snap.positions:
                pos = snap.positions[c]
                label = pos.issuer + (f" ({pos.ticker})" if pos.ticker else "")
                break
        if label:
            break

    holdings: list[FundHolding] = []
    absent: list[Whale] = []
    for whale in whales:
        snaps = per_fund[whale.cik]
        if not snaps:
            absent.append(whale)
            continue
        current, prior = snaps[0], (snaps[1] if len(snaps) > 1 else None)
        cur_shares = sum(p.shares for c, p in current.positions.items() if c in matched)
        cur_value = sum(p.value for c, p in current.positions.items() if c in matched)
        prev_shares = (
            sum(p.shares for c, p in prior.positions.items() if c in matched)
            if prior is not None else 0
        )
        if cur_shares == 0 and prev_shares == 0:
            absent.append(whale)
            continue
        if prior is None:
            action = "held"
        elif prev_shares == 0:
            action = "opened"
        elif cur_shares == 0:
            action = "exited"
        elif cur_shares > prev_shares:
            action = "added"
        elif cur_shares < prev_shares:
            action = "trimmed"
        else:
            action = "unchanged"
        total = current.total_value
        if total <= 0:
            raise ThirteenFError(f"non-positive total value in snapshot CIK {whale.cik}")
        holdings.append(FundHolding(
            whale=whale,
            period=current.report_period,
            prior_period=prior.report_period if prior is not None else None,
            shares=cur_shares,
            value=cur_value,
            weight=cur_value / total,
            action=action,
        ))
    holdings.sort(key=lambda h: (-h.value, h.whale.name))
    return holdings, absent, matched, label


def format_holdings_markdown(ticker: str | None, holdings: list[FundHolding],
                             absent: list[Whale], matched: set[str],
                             label: str) -> str:
    """Deterministic markdown report — pure function of scan results."""
    lines: list[str] = []
    title = label or ticker or "/".join(sorted(matched))
    lines.append(f"# Whale 13F holdings — {title}")
    lines.append("")
    lines.append(f"Matched CUSIP(s): {', '.join(sorted(matched))}")
    lines.append("")
    lines.append("> **Caveats — read before drawing conclusions**")
    for caveat in CAVEATS:
        lines.append(f"> - {caveat}")
    lines.append("")
    if holdings:
        lines.append("| Fund | Quarter | Action (QoQ shares) | Shares | Value ($) | Weight |")
        lines.append("|---|---|---|---:|---:|---:|")
        for h in holdings:
            quarter = _quarter_label(h.period)
            if h.action == "held":
                action = "held (no prior period fetched)"
            elif h.action == "unchanged":
                action = "unchanged"
            elif h.prior_period is not None:
                action = f"{h.action} (vs {_quarter_label(h.prior_period)})"
            else:
                action = h.action
            lines.append(
                f"| {h.whale.name} | {quarter} | {action} "
                f"| {h.shares:,} | {h.value:,} | {h.weight:.2%} |"
            )
        lines.append("")
        holders = [h for h in holdings if h.shares > 0]
        exited = [h for h in holdings if h.action == "exited"]
        roster_size = len(holdings) + len(absent)
        verb = "holds" if len(holders) == 1 else "hold"
        summary = f"**{len(holders)}** of {roster_size} roster funds {verb} it"
        if exited:
            summary += f"; {len(exited)} exited last quarter"
        lines.append(summary + ".")
    else:
        lines.append("No roster fund reported a position in its latest-two filings.")
    lines.append("")
    if absent:
        lines.append("Funds with no reported position: "
                     + ", ".join(w.name for w in absent) + ".")
        lines.append("")
    lines.append("---")
    lines.append("Source: pinned SEC EDGAR 13F snapshots (`whale fetch-13f`); every "
                 "number is as reported in a filing infotable. Options (put/call) "
                 "rows were excluded at fetch time.")
    lines.append("")
    return "\n".join(lines)
