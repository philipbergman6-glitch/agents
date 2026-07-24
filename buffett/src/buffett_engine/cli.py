"""Two-phase CLI.

  buffett fetch TICKER      networked: EDGAR + yfinance -> snapshots/TICKER-DATE.json
  buffett diagnose TICKER   offline: latest (or --snapshot) snapshot -> diagnostic JSON

Snapshots directory: --snapshots-dir, else $BUFFETT_SNAPSHOTS, else ./snapshots.
Diagnose is a pure function of the snapshot file; byte-identical output for the
same snapshot. All errors exit non-zero with a message on stderr — no silent
fallbacks.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _snapshots_dir(arg: str | None) -> Path:
    return Path(arg or os.environ.get("BUFFETT_SNAPSHOTS") or "snapshots")


def _dump(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)


def cmd_fetch(args) -> int:
    from .fetch import fetch_snapshot

    snapshot = fetch_snapshot(args.ticker)
    out_dir = _snapshots_dir(args.snapshots_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{snapshot['ticker']}-{snapshot['fetched_at']}.json"
    path.write_text(_dump(snapshot) + "\n", encoding="utf-8")
    print(str(path))
    return 0


def cmd_diagnose(args) -> int:
    from .score import diagnose

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
                f"— run `buffett fetch {ticker}` first",
                file=sys.stderr,
            )
            return 2
        path = candidates[-1]  # ISO dates in names sort chronologically

    snapshot = json.loads(path.read_text(encoding="utf-8"))
    result = diagnose(snapshot)
    result["provenance"]["snapshot"] = str(path)
    print(_dump(result))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="buffett", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="fetch EDGAR + market data into a snapshot (networked)")
    p_fetch.add_argument("ticker")
    p_fetch.add_argument("--snapshots-dir")
    p_fetch.set_defaults(func=cmd_fetch)

    p_diag = sub.add_parser("diagnose", help="score a snapshot (offline, deterministic)")
    p_diag.add_argument("ticker")
    p_diag.add_argument("--snapshot", help="explicit snapshot file (default: latest for ticker)")
    p_diag.add_argument("--snapshots-dir")
    p_diag.set_defaults(func=cmd_diagnose)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as e:
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
