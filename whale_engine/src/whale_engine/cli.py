"""Two-phase CLI, one engine, many whales.

  <prog> fetch TICKER      networked: EDGAR + Cboe quote -> snapshots/TICKER-DATE.json
  <prog> diagnose TICKER   offline: latest (or --snapshot) snapshot -> diagnostic JSON
  <prog> prices TICKER...  networked: Alpha Vantage weekly adjusted closes ->
                           snapshots/prices/TICKER-DATE.json (weekly freshness gate)

Entry points:
  buffett ...              Buffett-only prog; behavior identical to the original CLI
  whale ... --whale NAME   generic prog; diagnose requires picking a whale scorer

Snapshots are whale-agnostic (raw filings data, no opinions): fetch once, then
any whale diagnoses from the same file. Snapshots directory: --snapshots-dir,
else $BUFFETT_SNAPSHOTS, else ./snapshots. Diagnose is a pure function of the
snapshot file; byte-identical output for the same snapshot. All errors exit
non-zero with a message on stderr — no silent fallbacks.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .scorers import WHALES, get_diagnose


def _snapshots_dir(arg: str | None) -> Path:
    return Path(arg or os.environ.get("BUFFETT_SNAPSHOTS") or "snapshots")


def _prices_dir(arg: str | None) -> Path:
    """Price snapshots live beside the EDGAR ones, in their own subdirectory."""
    return _snapshots_dir(arg) / "prices"


def _dump(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)


def cmd_fetch(args) -> int:
    from .fetch import fetch_snapshot
    from .filings_text import sidecar_filename

    snapshot = fetch_snapshot(args.ticker, market_cap_override=args.market_cap)
    out_dir = _snapshots_dir(args.snapshots_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Filings-text sidecar (ticket #49): written next to the snapshot; the
    # snapshot records only the filename, resolved relative to its own
    # directory so the pair stays portable as a unit.
    sidecar = snapshot.get("filings_sidecar")
    if sidecar is not None:
        markdown = sidecar.pop("markdown")
        name = sidecar_filename(snapshot["ticker"], snapshot["fetched_at"])
        (out_dir / name).write_text(markdown, encoding="utf-8")
        sidecar["path"] = name

    path = out_dir / f"{snapshot['ticker']}-{snapshot['fetched_at']}.json"
    path.write_text(_dump(snapshot) + "\n", encoding="utf-8")
    print(str(path))
    return 0


def cmd_diagnose(args) -> int:
    diagnose = get_diagnose(args.whale)

    if args.snapshot:
        path = Path(args.snapshot)
        if not path.exists():
            print(f"error: snapshot not found: {path}", file=sys.stderr)
            return 2
    else:
        ticker = args.ticker.upper()
        candidates = sorted(_snapshots_dir(args.snapshots_dir).glob(f"{ticker}-*.json"))
        if not candidates:
            print(
                f"error: no snapshot for {ticker} in {_snapshots_dir(args.snapshots_dir)}/ "
                f"— run `{args.prog} fetch {ticker}` first",
                file=sys.stderr,
            )
            return 2
        path = candidates[-1]  # ISO dates in names sort chronologically

    snapshot = json.loads(path.read_text(encoding="utf-8"))
    result = diagnose(snapshot)
    result["provenance"]["snapshot"] = str(path)
    print(_dump(result))
    return 0


def cmd_prices(args) -> int:
    """Pin weekly-adjusted price history for a basket (ticket #84).

    One vendor request per ticker that needs one: a snapshot already holding
    the most recently completed weekly bar is reused at zero request cost
    (weekly freshness gate, #83). Fails fast on the first bad ticker — a
    rate-cap `Information` body means the rest would fail too.
    """
    from .prices import ensure_price_snapshot

    out_dir = _prices_dir(args.snapshots_dir)
    for ticker in args.tickers:
        path, snapshot, action = ensure_price_snapshot(
            ticker,
            out_dir,
            force=args.force,
            allow_stale=args.stale_ok,
        )
        print(
            f"{snapshot['ticker']}\t{action}\tweek of "
            f"{snapshot['last_complete_week']}\t{snapshot['observations']} bars\t{path}"
        )
    return 0


def cmd_fetch_13f(args) -> int:
    from .holdings import fetch_roster

    out_dir = _snapshots_dir(args.snapshots_dir) / "13f"
    fetch_roster(out_dir, only=args.only)
    return 0


def cmd_holdings(args) -> int:
    from .holdings import format_holdings_markdown, scan_holdings

    snapshots_dir = _snapshots_dir(args.snapshots_dir) / "13f"
    holdings, absent, matched, label = scan_holdings(
        args.ticker, snapshots_dir, cusip=args.cusip
    )
    print(format_holdings_markdown(args.ticker, holdings, absent, matched, label))
    return 0


def main(argv: list[str] | None = None, *, prog: str = "whale", whale: str | None = None) -> int:
    parser = argparse.ArgumentParser(prog=prog, description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="fetch EDGAR + market data into a snapshot (networked)")
    p_fetch.add_argument("ticker")
    p_fetch.add_argument("--snapshots-dir")
    p_fetch.add_argument(
        "--market-cap",
        type=float,
        dest="market_cap",
        help="manual market-cap override in dollars (skips the Cboe quote; "
        "provenance 'manual:owner-supplied')",
    )
    p_fetch.set_defaults(func=cmd_fetch, prog=prog)

    p_diag = sub.add_parser("diagnose", help="score a snapshot (offline, deterministic)")
    p_diag.add_argument("ticker")
    p_diag.add_argument("--snapshot", help="explicit snapshot file (default: latest for ticker)")
    p_diag.add_argument("--snapshots-dir")
    if whale is None:
        p_diag.add_argument("--whale", required=True, choices=WHALES, help="scorer to apply")
    p_diag.set_defaults(func=cmd_diagnose, prog=prog, **({} if whale is None else {"whale": whale}))

    p_prices = sub.add_parser(
        "prices",
        help="pin weekly adjusted price history for one or more tickers "
        "(networked; needs ALPHAVANTAGE_API_KEY)",
    )
    p_prices.add_argument("tickers", nargs="+", metavar="TICKER")
    p_prices.add_argument("--snapshots-dir")
    p_prices.add_argument(
        "--force",
        action="store_true",
        help="refetch even when the pinned snapshot is still fresh",
    )
    p_prices.add_argument(
        "--stale-ok",
        action="store_true",
        dest="stale_ok",
        help="reuse a snapshot that predates the last weekly close instead of "
        "refetching (explicit staleness, as with EDGAR snapshots)",
    )
    p_prices.set_defaults(func=cmd_prices, prog=prog)

    p_f13 = sub.add_parser(
        "fetch-13f",
        help="fetch latest-two 13F periods for every roster whale (networked)",
    )
    p_f13.add_argument("--snapshots-dir")
    p_f13.add_argument("--only", help="fetch a single roster whale (exact name)")
    p_f13.set_defaults(func=cmd_fetch_13f, prog=prog)

    p_hold = sub.add_parser(
        "holdings",
        help="who on the whale roster holds a ticker, and what they did last quarter "
        "(offline, from fetch-13f snapshots)",
    )
    p_hold.add_argument("ticker", nargs="?", help="ticker (omit only with --cusip)")
    p_hold.add_argument("--cusip", help="match by CUSIP instead of ticker "
                        "(for positions EDGAR never resolved to a ticker)")
    p_hold.add_argument("--snapshots-dir")
    p_hold.set_defaults(func=cmd_holdings, prog=prog)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as e:
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


def buffett_main(argv: list[str] | None = None) -> int:
    return main(argv, prog="buffett", whale="buffett")


if __name__ == "__main__":
    sys.exit(main())
