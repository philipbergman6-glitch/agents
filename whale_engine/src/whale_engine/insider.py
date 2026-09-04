"""Form 4 insider buy-cluster detection.

Networked part: fetch Form 4 non-derivative open-market purchases (transaction
code P, acquired) via edgartools, looking back 12 months from the snapshot
date. Buys only — sell clusters are excluded entirely (weakly informative:
taxes, diversification, comp).

Deterministic part: a buy cluster is >= 3 distinct code-P purchases by >= 3
distinct insiders within ANY rolling 90-day window inside the lookback
(academic cluster definition, Cohen et al. line; no size floor). Two purchases
share a 90-day window iff their dates are strictly less than 90 days apart
(days 0..89 inclusive — a 90-calendar-day span).

The result is written into the snapshot as a whale-agnostic
``insider_activity`` section: verdict + supporting transactions (insider name,
role, date, shares, value, accession number for provenance). This is unscored
context — no rubric touches it; the subagent must cite it, never recompute it.

Form 4 fetch failure is a WARN appended to the snapshot's ``validation`` list
({severity, code, message}) — never a failed fetch. On failure the
``insider_activity`` section is omitted entirely, so "no cluster" (section
present, verdict no_cluster) stays distinguishable from "not checked"
(section absent + WARN).

Determinism contract for detect_cluster/build_insider_activity: pure functions
of their inputs — no I/O, no clocks, no randomness.
"""

from __future__ import annotations

from datetime import date, timedelta

LOOKBACK_DAYS = 365
WINDOW_DAYS = 90
MIN_DISTINCT_INSIDERS = 3
MIN_PURCHASES = 3
# A liquid mega-cap can have hundreds of Form 4s in a year (mostly grants and
# sells); the filing-date walk stops at the lookback floor, this cap is a
# safety valve against pathological filers.
MAX_FORM4_FILINGS = 400

WARN_CODE_FETCH_FAILED = "form4_fetch_failed"


def _to_date(v) -> date | None:
    if v is None:
        return None
    if isinstance(v, date) and not hasattr(v, "date"):
        return v
    if hasattr(v, "date"):  # pandas Timestamp / datetime
        return v.date()
    s = str(v)[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# deterministic core


def detect_cluster(transactions: list[dict]) -> dict | None:
    """First (earliest-anchored) qualifying 90-day buy cluster, or None.

    ``transactions`` are code-P buys, each a dict with at least ``insider``
    and ``date`` (ISO string). Qualifies when a window anchored at some
    purchase date contains >= MIN_PURCHASES purchases by
    >= MIN_DISTINCT_INSIDERS distinct insiders (same insider buying
    repeatedly counts as one insider, however many purchases).
    """
    dated = sorted(
        (t for t in transactions if _to_date(t.get("date")) is not None),
        key=lambda t: (str(t["date"]), str(t.get("insider", "")), str(t.get("accession_number", ""))),
    )
    for i, anchor in enumerate(dated):
        start = _to_date(anchor["date"])
        in_window = [
            t for t in dated[i:] if (_to_date(t["date"]) - start).days < WINDOW_DAYS
        ]
        insiders = sorted({str(t.get("insider", "")) for t in in_window})
        if len(in_window) >= MIN_PURCHASES and len(insiders) >= MIN_DISTINCT_INSIDERS:
            values = [t.get("value") for t in in_window if t.get("value") is not None]
            return {
                "window_start": str(anchor["date"]),
                "window_end": str(in_window[-1]["date"]),
                "purchases": len(in_window),
                "distinct_insiders": len(insiders),
                "insiders": insiders,
                "total_value": sum(values) if values else None,
            }
    return None


def build_insider_activity(transactions: list[dict], snapshot_date: date) -> dict:
    """Assemble the whale-agnostic ``insider_activity`` snapshot section.

    Filters to the 12-month lookback ending at snapshot_date, then runs
    cluster detection. Pure function: same inputs -> identical dict.
    """
    lookback_start = snapshot_date - timedelta(days=LOOKBACK_DAYS)
    in_lookback = sorted(
        (
            t
            for t in transactions
            if _to_date(t.get("date")) is not None
            and lookback_start <= _to_date(t["date"]) <= snapshot_date
        ),
        key=lambda t: (str(t["date"]), str(t.get("insider", "")), str(t.get("accession_number", ""))),
    )
    cluster = detect_cluster(in_lookback)
    return {
        "source": "SEC Form 4 non-derivative open-market purchases (code P), via edgartools",
        "lookback_start": lookback_start.isoformat(),
        "lookback_end": snapshot_date.isoformat(),
        "cluster_rule": (
            f">={MIN_PURCHASES} code-P purchases by >={MIN_DISTINCT_INSIDERS} distinct "
            f"insiders within any rolling {WINDOW_DAYS}-day window"
        ),
        "verdict": "cluster" if cluster is not None else "no_cluster",
        "cluster": cluster,
        "transactions": in_lookback,
    }


# ---------------------------------------------------------------------------
# networked fetch (edgartools)


def _txn_value(shares, price) -> float | None:
    if shares is None or price is None:
        return None
    try:
        import math

        s, p = float(shares), float(price)
        if math.isnan(s) or math.isnan(p):
            return None
        return s * p
    except (TypeError, ValueError):
        return None


def _num(v) -> float | None:
    """Best-effort numeric parse; Form 4 XML occasionally carries strings."""
    if v is None:
        return None
    try:
        import math

        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def fetch_form4_purchases(company, snapshot_date: date) -> list[dict]:
    """All code-P non-derivative open-market buys in the 12-month lookback.

    Walks the company's Form 4 filings newest-first, stopping once
    filing dates fall past the lookback floor (a Form 4 is filed within
    2 business days of the transaction, so no in-window transaction can
    hide in an older filing beyond a small margin we cover by walking to
    the floor itself).
    """
    lookback_start = snapshot_date - timedelta(days=LOOKBACK_DAYS)
    transactions: list[dict] = []

    filings = company.get_filings(form="4")
    if filings is None:
        return transactions

    for n, filing in enumerate(filings):
        if n >= MAX_FORM4_FILINGS:
            break
        filing_date = _to_date(getattr(filing, "filing_date", None))
        if filing_date is not None and filing_date < lookback_start:
            break  # newest-first: everything further back predates the window
        try:
            form4 = filing.obj()
        except Exception:
            continue  # unparseable single filing: skip, not fatal
        table = getattr(form4, "non_derivative_table", None)
        if table is None or not getattr(table, "has_transactions", False):
            continue
        df = table.market_trades
        if df is None or df.empty:
            continue
        buys = df[(df["Code"] == "P") & (df["AcquiredDisposed"] == "A")]
        if buys.empty:
            continue

        owners = getattr(form4, "reporting_owners", None)
        owner_list = list(getattr(owners, "owners", []) or [])
        # A multi-owner Form 4 (e.g. a trust) is one filer: one insider key.
        insider = " & ".join(o.name for o in owner_list) or str(
            getattr(form4, "insider_name", "") or ""
        )
        role = "; ".join(filter(None, (o.position for o in owner_list)))
        accession = str(
            getattr(filing, "accession_no", None)
            or getattr(filing, "accession_number", "")
            or ""
        )

        for row in buys.itertuples():
            shares = _num(getattr(row, "Shares", None))
            price = _num(getattr(row, "Price", None))
            txn_date = _to_date(getattr(row, "Date", None))
            if txn_date is None:
                continue
            transactions.append(
                {
                    "insider": insider,
                    "role": role,
                    "date": txn_date.isoformat(),
                    "shares": shares,
                    "value": _txn_value(shares, price),
                    "accession_number": accession,
                }
            )
    return transactions


def collect_insider_activity(
    company, snapshot_date: date
) -> tuple[dict | None, dict | None]:
    """(insider_activity section, WARN finding) — exactly one is non-None.

    Any failure in the Form 4 path degrades to a WARN {severity, code,
    message} for the snapshot's ``validation`` list; it never fails the fetch.
    """
    try:
        transactions = fetch_form4_purchases(company, snapshot_date)
        return build_insider_activity(transactions, snapshot_date), None
    except Exception as e:
        return None, {
            "severity": "WARN",
            "code": WARN_CODE_FETCH_FAILED,
            "message": (
                f"Form 4 insider-activity fetch failed ({type(e).__name__}: {e}); "
                "insider_activity omitted from this snapshot — insider signal "
                "not checked, which is distinct from 'no cluster'."
            ),
        }
