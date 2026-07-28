"""Two-phase CLI, one engine, many whales.

  <prog> fetch TICKER      networked: EDGAR + Cboe quote -> snapshots/TICKER-DATE.json
  <prog> diagnose TICKER   offline: latest (or --snapshot) snapshot -> diagnostic JSON

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
