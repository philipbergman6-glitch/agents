"""13F-HR portfolio fetch + format (networked fetch, deterministic format).

Standalone module — deliberately independent of the fundamentals fetch/snapshot
pipeline so it can evolve separately. Parameterized by CIK so the full
16-fund whale-holdings module can reuse it verbatim:

    uv run python -m whale_engine.thirteenf --cik 1067983 \
        --name "Berkshire Hathaway" --out ../portfolios/berkshire-13f.md

Design decisions (all pinned by research/13f-whale-holdings.md):
- Amendment-aware: 13F-HR/A restatements exist (Berkshire files them
  regularly); for each report period the latest-filed accession wins.
- Aggregation: one issuer spans multiple rows (share classes, sub-managers);
  aggregate by CUSIP after excluding rows with PutCall set (options are not
  share ownership); options are surfaced as a count, never mixed into weights.
- Values are whole dollars (13F rule change effective Q2 2022 periods).
- Every number in the output comes from the filing infotable — nothing is
  estimated, priced, or adjusted.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field


class ThirteenFError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Data model (plain dataclasses so formatting/diffing is testable offline)
# ---------------------------------------------------------------------------


@dataclass
class Position:
    cusip: str
    issuer: str
    ticker: str  # may be "" when EDGAR's CUSIP->ticker map has no entry
    share_classes: list[str]
    shares: int  # SharesPrnAmount summed across rows (SH rows only)
    value: int  # whole USD as reported in the filing


@dataclass
class PortfolioSnapshot:
    cik: int
    form: str
    filing_date: str  # YYYY-MM-DD
    report_period: str  # YYYY-MM-DD (quarter end)
    accession_no: str
    positions: dict[str, Position] = field(default_factory=dict)  # by CUSIP
    option_rows: int = 0  # PutCall rows excluded from positions

    @property
    def total_value(self) -> int:
        return sum(p.value for p in self.positions.values())


# ---------------------------------------------------------------------------
# Snapshot (de)serialization — pinned JSON files, whale-agnostic raw data
# ---------------------------------------------------------------------------

SNAPSHOT_SCHEMA = "13f-snapshot/v1"


def snapshot_to_dict(snap: PortfolioSnapshot) -> dict:
    return {
        "schema": SNAPSHOT_SCHEMA,
        "cik": snap.cik,
        "form": snap.form,
        "filing_date": snap.filing_date,
        "report_period": snap.report_period,
        "accession_no": snap.accession_no,
        "option_rows": snap.option_rows,
        "positions": [
            {
                "cusip": p.cusip,
                "issuer": p.issuer,
                "ticker": p.ticker,
                "share_classes": p.share_classes,
                "shares": p.shares,
                "value": p.value,
            }
            for p in sorted(snap.positions.values(), key=lambda p: p.cusip)
        ],
    }


def snapshot_from_dict(data: dict) -> PortfolioSnapshot:
    if not isinstance(data, dict) or data.get("schema") != SNAPSHOT_SCHEMA:
        raise ThirteenFError(
            f"not a {SNAPSHOT_SCHEMA} snapshot (schema={data.get('schema')!r})"
            if isinstance(data, dict) else "snapshot is not a JSON object"
        )
    required = {"cik", "form", "filing_date", "report_period", "accession_no",
                "option_rows", "positions"}
    missing = required - set(data)
    if missing:
        raise ThirteenFError(f"snapshot missing keys {sorted(missing)}")
    snap = PortfolioSnapshot(
        cik=int(data["cik"]),
        form=str(data["form"]),
        filing_date=str(data["filing_date"]),
        report_period=str(data["report_period"]),
        accession_no=str(data["accession_no"]),
        option_rows=int(data["option_rows"]),
    )
    for p in data["positions"]:
        cusip = str(p["cusip"])
        if cusip in snap.positions:
            raise ThirteenFError(f"duplicate CUSIP {cusip} in snapshot CIK {snap.cik}")
        snap.positions[cusip] = Position(
            cusip=cusip,
            issuer=str(p["issuer"]),
            ticker=str(p["ticker"]),
            share_classes=list(p["share_classes"]),
            shares=int(p["shares"]),
            value=int(p["value"]),
        )
    if not snap.positions:
        raise ThirteenFError(f"snapshot for CIK {snap.cik} has no positions")
    return snap


# ---------------------------------------------------------------------------
# Parse / aggregate (pure: DataFrame -> PortfolioSnapshot)
# ---------------------------------------------------------------------------


def aggregate_infotable(
    infotable, *, cik: int, form: str, filing_date: str, report_period: str, accession_no: str
) -> PortfolioSnapshot:
    """Aggregate a 13F infotable DataFrame into per-CUSIP positions.

    Excludes PutCall rows (options); hard-fails on empty/malformed input.
    """
    if infotable is None or len(infotable) == 0:
        raise ThirteenFError(f"empty infotable for CIK {cik} period {report_period}")
    required = {"Issuer", "Class", "Cusip", "Value", "PutCall", "SharesPrnAmount"}
    missing = required - set(infotable.columns)
    if missing:
        raise ThirteenFError(f"infotable missing columns {sorted(missing)} for CIK {cik}")

    snap = PortfolioSnapshot(
        cik=cik,
        form=form,
        filing_date=filing_date,
        report_period=report_period,
        accession_no=accession_no,
    )
    for row in infotable.to_dict("records"):
        putcall = str(row.get("PutCall") or "").strip()
        if putcall:
            snap.option_rows += 1
            continue
        cusip = str(row["Cusip"]).strip()
        if not cusip:
            raise ThirteenFError(f"row with blank CUSIP in CIK {cik} {report_period}: {row}")
        value = int(row["Value"])
        shares = int(row["SharesPrnAmount"])
        if value < 0 or shares < 0:
            raise ThirteenFError(f"negative value/shares in CIK {cik} {report_period}: {row}")
        ticker = str(row.get("Ticker") or "").strip()
        cls = str(row.get("Class") or "").strip()
        pos = snap.positions.get(cusip)
        if pos is None:
            snap.positions[cusip] = Position(
                cusip=cusip,
                issuer=str(row["Issuer"]).strip(),
                ticker=ticker,
                share_classes=[cls] if cls else [],
                shares=shares,
                value=value,
            )
        else:
            pos.shares += shares
            pos.value += value
            if cls and cls not in pos.share_classes:
                pos.share_classes.append(cls)
            if not pos.ticker and ticker:
                pos.ticker = ticker
    if not snap.positions:
        raise ThirteenFError(f"no non-option positions for CIK {cik} period {report_period}")
    return snap


# ---------------------------------------------------------------------------
# Quarter-over-quarter diff (pure)
# ---------------------------------------------------------------------------


@dataclass
class Change:
    kind: str  # opened | exited | added | trimmed | unchanged
    cusip: str
    label: str
    shares_now: int
    shares_prev: int


def diff_snapshots(current: PortfolioSnapshot, prior: PortfolioSnapshot) -> list[Change]:
    """Classify every CUSIP across two snapshots. Share counts only — value
    moves with price and is not a trading signal."""
    changes: list[Change] = []
    cusips = set(current.positions) | set(prior.positions)
    for cusip in sorted(cusips):
        cur, prev = current.positions.get(cusip), prior.positions.get(cusip)
        ref = cur or prev
        assert ref is not None  # every cusip came from one of the two snapshots
        label = f"{ref.issuer}" + (f" ({ref.ticker})" if ref.ticker else "")
        if cur is not None and prev is None:
            changes.append(Change("opened", cusip, label, cur.shares, 0))
        elif prev is not None and cur is None:
            changes.append(Change("exited", cusip, label, 0, prev.shares))
        elif cur is None or prev is None:  # unreachable: the cusip set is the union
            raise AssertionError(cusip)
        elif cur.shares > prev.shares:
            changes.append(Change("added", cusip, label, cur.shares, prev.shares))
        elif cur.shares < prev.shares:
            changes.append(Change("trimmed", cusip, label, cur.shares, prev.shares))
        else:
            changes.append(Change("unchanged", cusip, label, cur.shares, prev.shares))
    return changes


# ---------------------------------------------------------------------------
# Markdown formatting (pure, deterministic)
# ---------------------------------------------------------------------------


def _quarter_label(period: str) -> str:
    year, month, _ = period.split("-")
    return f"Q{(int(month) - 1) // 3 + 1} {year}"


def _pct_delta(now: int, prev: int) -> str:
    if prev == 0:
        return "new"
    return f"{(now - prev) / prev:+.1%}"


def format_portfolio_markdown(
    fund_name: str,
    current: PortfolioSnapshot,
    prior: PortfolioSnapshot | None,
    *,
    extra_notes: list[str] | None = None,
) -> str:
    """Render a client-browsable portfolio file. Every number comes from the
    filing(s); weights are value / total reported long value."""
    quarter = _quarter_label(current.report_period)
    total = current.total_value
    if total <= 0:
        raise ThirteenFError("total portfolio value is not positive")

    change_by_cusip: dict[str, Change] = {}
    if prior is not None:
        change_by_cusip = {c.cusip: c for c in diff_snapshots(current, prior)}

    lines: list[str] = []
    lines.append(f"# {fund_name} — 13F portfolio ({quarter})")
    lines.append("")
    lines.append(f"**Reporting quarter: {quarter} (holdings as of {current.report_period})** — "
                 f"from SEC Form {current.form} filed {current.filing_date} "
                 f"(CIK {current.cik}, accession {current.accession_no}).")
    lines.append("")
    lines.append("> **Caveats — read before drawing conclusions**")
    lines.append("> - **45-day filing lag:** 13F filings are due up to 45 days after quarter end, "
                 "so these positions are a snapshot from the quarter-end date above and may have "
                 "changed since.")
    lines.append("> - 13Fs cover **US-listed long positions only** — no shorts, no cash, "
                 "no non-US-listed holdings; this is not the fund's complete book.")
    lines.append("> - Values are as reported in the filing (position value at quarter end, whole "
                 "USD). Weights = position value / total reported 13F value. Nothing here is "
                 "estimated.")
    if current.option_rows:
        lines.append(f"> - {current.option_rows} option (put/call) rows in the filing were "
                     "excluded from the table; only share positions are shown.")
    for note in extra_notes or []:
        lines.append(f"> - {note}")
    lines.append("")
    lines.append(f"Total reported value: **${total:,}** across "
                 f"**{len(current.positions)}** positions.")
    lines.append("")

    lines.append("## Holdings by weight")
    lines.append("")
    header = "| # | Issuer | Ticker | Class | Shares | Value ($) | Weight |"
    sep = "|---|---|---|---|---:|---:|---:|"
    if prior is not None:
        header += " QoQ (shares) |"
        sep += "---|"
    lines.append(header)
    lines.append(sep)
    ranked = sorted(current.positions.values(), key=lambda p: (-p.value, p.cusip))
    for i, p in enumerate(ranked, 1):
        row = (f"| {i} | {p.issuer} | {p.ticker or '—'} | {'/'.join(p.share_classes) or '—'} "
               f"| {p.shares:,} | {p.value:,} | {p.value / total:.2%} |")
        if prior is not None:
            ch = change_by_cusip.get(p.cusip)
            if ch is None or ch.kind == "unchanged":
                row += " — |"
            elif ch.kind == "opened":
                row += " **new** |"
            else:
                row += f" {ch.kind} {_pct_delta(ch.shares_now, ch.shares_prev)} |"
        lines.append(row)
    lines.append("")

    if prior is not None:
        prior_q = _quarter_label(prior.report_period)
        lines.append(f"## Changes vs {prior_q} "
                     f"(prior {prior.form} filed {prior.filing_date})")
        lines.append("")
        buckets: dict[str, list[Change]] = {"opened": [], "added": [], "trimmed": [], "exited": []}
        for ch in change_by_cusip.values():
            if ch.kind in buckets:
                buckets[ch.kind].append(ch)
        titles = {
            "opened": "New positions",
            "added": "Added",
            "trimmed": "Trimmed",
            "exited": "Exited",
        }
        for kind in ("opened", "added", "trimmed", "exited"):
            lines.append(f"**{titles[kind]}:**")
            entries = sorted(buckets[kind], key=lambda c: c.label)
            if not entries:
                lines.append("- none")
            else:
                for ch in entries:
                    if ch.kind == "opened":
                        lines.append(f"- {ch.label} — {ch.shares_now:,} shares")
                    elif ch.kind == "exited":
                        lines.append(f"- {ch.label} — was {ch.shares_prev:,} shares")
                    else:
                        lines.append(f"- {ch.label} — {ch.shares_prev:,} → {ch.shares_now:,} "
                                     f"shares ({_pct_delta(ch.shares_now, ch.shares_prev)})")
            lines.append("")

    lines.append("---")
    lines.append(f"Source: SEC EDGAR, {current.form} accession {current.accession_no} "
                 f"(and {prior.accession_no} for the prior quarter). "
                 f"Generated by `whale_engine.thirteenf`; regenerate with "
                 f"`uv run python -m whale_engine.thirteenf --cik {current.cik}`."
                 if prior is not None else
                 f"Source: SEC EDGAR, {current.form} accession {current.accession_no}. "
                 f"Generated by `whale_engine.thirteenf`.")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Networked fetch (edgartools)
# ---------------------------------------------------------------------------


def fetch_latest_snapshots(cik: int, *, periods: int = 2) -> list[PortfolioSnapshot]:
    """Fetch the latest `periods` distinct 13F report periods for a CIK,
    amendment-aware (latest-filed accession wins per period). Newest first."""
    identity = os.environ.get("EDGAR_IDENTITY", "").strip()
    if not identity:
        raise ThirteenFError(
            "EDGAR_IDENTITY is not set. SEC EDGAR requires a declared identity, "
            'e.g. export EDGAR_IDENTITY="Jane Doe jane@example.com"'
        )
    import edgar

    edgar.set_identity(identity)
    company = edgar.Company(cik)
    filings = list(company.get_filings(form=["13F-HR", "13F-HR/A"]))
    if not filings:
        raise ThirteenFError(f"no 13F-HR filings found for CIK {cik}")

    # Newest-filed first from EDGAR; keep the first (latest-filed) filing seen
    # per report period — that is the amendment when one exists.
    by_period: dict[str, PortfolioSnapshot] = {}
    for filing in filings:
        if len(by_period) >= periods + 1:  # small buffer, then stop paging objs
            break
        tf = filing.obj()
        period = str(tf.report_period)
        if period in by_period:
            continue
        by_period[period] = aggregate_infotable(
            tf.infotable,
            cik=cik,
            form=str(filing.form),
            filing_date=str(filing.filing_date),
            report_period=period,
            accession_no=str(filing.accession_no),
        )
    newest_first = [by_period[p] for p in sorted(by_period, reverse=True)]
    return newest_first[:periods]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m whale_engine.thirteenf",
        description="Fetch a filer's latest 13F-HR and emit a client-browsable markdown portfolio.",
    )
    parser.add_argument("--cik", type=int, required=True, help="EDGAR CIK of the 13F filer")
    parser.add_argument("--name", required=True, help="Display name for the fund")
    parser.add_argument("--out", help="Output markdown path (default: stdout)")
    parser.add_argument("--no-diff", action="store_true",
                        help="Skip the prior-quarter fetch/diff")
    parser.add_argument("--note", action="append", default=[],
                        help="Extra caveat line(s) to include (repeatable)")
    args = parser.parse_args(argv)

    snaps = fetch_latest_snapshots(args.cik, periods=1 if args.no_diff else 2)
    current = snaps[0]
    prior = snaps[1] if len(snaps) > 1 else None
    text = format_portfolio_markdown(args.name, current, prior, extra_notes=args.note)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text)
        print(f"wrote {args.out} ({_quarter_label(current.report_period)}, "
              f"{len(current.positions)} positions)")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
