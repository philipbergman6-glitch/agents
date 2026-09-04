"""Snapshot validation layer.

Three severity tiers:
- ERROR: provably invalid or structurally inapplicable input. Scorers raise
  MissingDataError on any ERROR finding — hard-fail, never score around it.
- WARN:  usable but degraded. Diagnosis runs; findings surface in the
  diagnosis `data_quality` block and the subagent must narrate them.
- INFO:  provenance notes. Snapshot-level only (written into the snapshot's
  `validation` section at fetch time); not part of `data_quality`.

A finding is a plain dict — {"severity", "code", "message", "context"} — so
parallel features (market-cap source, scale-jump checks, ...) can append their
own findings to the same lists without depending on this module's internals.

Checks 1-6 are pure functions of the snapshot and run both at fetch time
(stored in snapshot["validation"]) and at diagnose time (recomputed, so
pre-validation snapshots are still covered). Check 7 (the 8-K Item 4.02
restatement guard) needs EDGAR filing metadata, so it runs at fetch time only
(see fetch._check_restatements); diagnose carries its stored findings forward.

Determinism contract: run_checks is a pure function of the snapshot dict.
"""

from __future__ import annotations

import re
from datetime import date

ERROR = "ERROR"
WARN = "WARN"
INFO = "INFO"

# --- market-cap bounds (check 2) -------------------------------------------
# Loose order-of-magnitude bounds on market_cap / outstanding_shares catch
# unit-scale corruption (cap reported in thousands, share-count basis
# mismatch, ...). Snapshots that pin a price_reference (Cboe close x filed
# shares) additionally get the tight cross-check:
# |market_cap / (shares * price) - 1| <= MARKET_CAP_RELATIVE_TOLERANCE.
IMPLIED_PRICE_MIN = 0.10  # USD per share
IMPLIED_PRICE_MAX = 1_000_000.0  # BRK.A trades ~$7e5; anything above is corrupt
MARKET_CAP_RELATIVE_TOLERANCE = 0.10
# Mirrors fetch.MARKET_CAP_MANUAL_SOURCE (fetch imports validation, not the
# reverse). A manual cap has no price_reference, so the ±10% cross-check above
# can never fire on it — the WARN keeps that bypass honest (truth-in-scoring).
_MANUAL_MARKET_CAP_SOURCE = "manual:owner-supplied"
# When a snapshot carries a market_cap_check (yfinance witness, recorded at
# fetch), a wide disagreement means the derived cap's share basis is corrupt —
# MA's 2010 pre-split dei fact produced a −86% deviation that was recorded but
# never gated. Cboe-vs-yfinance timing noise is low single digits; 25%
# only fires on structural corruption. Fetch imports this same constant to
# hard-fail at fetch time; witness *absence* stays WARN-only.
MARKET_CAP_WITNESS_TOLERANCE = 0.25

# --- stale TTM windows (truth-in-scoring/A2) ----------------------------------
# edgartools clamps get_ttm to the latest window a tag can build, so an
# abandoned tag returns a years-stale value with only a prose warning. 185
# days is edgartools' own staleness threshold. The window end is parsed from
# the warning text and compared to the period's own period_end (the warning's
# stated day-count uses the requested calendar quarter, which can inflate the
# lag by up to two quarters).
STALE_WINDOW_DAYS = 185
_WINDOW_END_RE = re.compile(r"TTM window ends (\d{4}-\d{2}-\d{2})")

# --- fundamentals staleness vs the price (truth-in-scoring) -------------------
# The market cap is near-live (Cboe delayed close); the fundamentals are as of
# periods[0].period_end. Beyond ~a quarter of drift the diagnosis is pricing
# fresh markets against old books, and must say so.
FUNDAMENTALS_STALENESS_DAYS = 100

# --- split-aware share renormalization (check 3) ---------------------------
# An adjacent-period share-count ratio at or beyond SPLIT_DETECT_RATIO is a
# candidate split. The observed ratio is snapped to the nearest plausible
# split factor (n:1 up to 50:1; observed ratios sit slightly off the exact
# factor because buybacks continue between filings — GOOGL's 20:1 shows as
# x19.6). Snapped jumps renormalize every older period onto the current share
# basis; unsnappable jumps (CAVA's x80.7 pre-IPO unit conversion) are not
# splits, so the older segment is excluded and flagged WARN.
# The detect threshold sits at 1.8, not lower: heavy crisis dilution reaches
# 1.5x within a year (AAL 2020 x1.45) and must stay in the history as a real
# capital change — a 3:2 split is indistinguishable from it, so sub-2:1 moves
# are never treated as splits.
SPLIT_DETECT_RATIO = 1.8
SPLIT_SNAP_TOLERANCE = 0.10  # relative distance to the nearest candidate
SPLIT_MAX_FACTOR = 50
_SPLIT_CANDIDATES = [float(n) for n in range(2, SPLIT_MAX_FACTOR + 1)]

# --- invariants (check 6) --------------------------------------------------
# Balance-sheet identity tolerance. Tag-definition drift is real: parent-only
# StockholdersEquity vs NCI-inclusive Liabilities leaves a gap up to ~6% in
# the committed set (MSFT FY2016 5.7%). Beyond that the period is suspect.
BALANCE_IDENTITY_TOLERANCE = 0.08
# Isolated old-period violations (CAVA pre-IPO: mezzanine preferred units sit
# in neither Liabilities nor StockholdersEquity, gap 113%) degrade rather than
# invalidate the snapshot -> WARN. The violation escalates to ERROR when the
# most recent period violates or a majority of checked periods do.
_SIGN_RULES = [
    # (section, field, predicate description, predicate)
    ("ttm", "capital_expenditure", "<= 0 (negative = cash out)", lambda v: v <= 0),
    (
        "ttm",
        "dividends_and_other_cash_distributions",
        "<= 0 (negative = paid)",
        lambda v: v <= 0,
    ),
    ("ttm", "revenue", ">= 0", lambda v: v >= 0),
    ("balance", "outstanding_shares", "> 0", lambda v: v > 0),
    ("balance", "total_assets", "> 0", lambda v: v > 0),
    ("balance", "current_assets", ">= 0", lambda v: v >= 0),
    ("balance", "current_liabilities", ">= 0", lambda v: v >= 0),
    ("balance", "cash_and_equivalents", ">= 0", lambda v: v >= 0),
    ("balance", "short_term_debt", ">= 0", lambda v: v >= 0),
    ("balance", "long_term_debt", ">= 0", lambda v: v >= 0),
]

# --- sector applicability (check 4) ----------------------------------------
# Financial-sector filers (banks, insurers) file no capex and no classified
# balance sheet: capital_expenditure, current_assets and current_liabilities
# are structurally absent from every period (JPM pattern, audit b-3). That is
# not missing data — the rubric does not apply.
_SECTOR_MARKERS = [("ttm", "capital_expenditure"), ("balance", "current_assets"),
                   ("balance", "current_liabilities")]

# --- zero-vs-missing marker (check 5b) -------------------------------------
# EDGAR cannot say "zero": an untagged fact and a true zero are identical.
# These fields are zero-if-absent in the rubrics; the marker records the
# ambiguity so an auditor can see it was noticed, not lost.
_OPTIONAL_ZERO_FIELDS = [
    ("ttm", "dividends_and_other_cash_distributions"),
    ("ttm", "issuance_or_purchase_of_equity_shares"),
]
# Debt is not zero-if-absent: dependent checks (D/E, ROIC) score 0 as a data
# gap. One resolved component keeps the sum usable (the other is treated as
# zero, INFO); both missing means real debt may be invisible (BLDR carried
# ~$3.7B under tags outside the fallback lists, truth-in-scoring) — WARN, so it
# reaches data_quality and must be narrated.
_DEBT_FIELDS = [("balance", "short_term_debt"), ("balance", "long_term_debt")]

# Findings only fetch time can produce; diagnose-time run_checks carries them
# forward from the snapshot's stored validation section.
FETCH_ONLY_CODES = {
    "restatement_402",
    "restatement_guard_unavailable",
    # Fetch-path findings from the filings sidecar, yfinance
    # cross-check and Form 4 insider fetch: only observable at
    # fetch time, so diagnoses must carry them forward from the snapshot.
    "filings_sidecar_extraction_failed",
    "yfinance-crosscheck-unavailable",
    "form4_fetch_failed",
    # Additive SIC fields from the submissions API: only observable at
    # fetch time, and the portfolio layer's sector check depends on them.
    "sic_unavailable",
}

DEFAULT_ARRAYS = ("periods", "annual_periods")


def finding(severity: str, code: str, message: str, **context) -> dict:
    return {"severity": severity, "code": code, "message": message, "context": context}


def stale_ttm_fields(period: dict, threshold_days: int = STALE_WINDOW_DAYS) -> dict:
    """TTM fields whose stitched window ends long before the period's own end.

    Parses the edgartools warning text stored in tags_used ("TTM window ends
    YYYY-MM-DD ...") and compares that window end to period_end. Returns
    {field: lag_days} for every field lagging beyond threshold_days.
    """
    out: dict[str, int] = {}
    period_end = period.get("period_end")
    if not period_end:
        return out
    end = date.fromisoformat(period_end)
    for key, msg in (period.get("tags_used") or {}).items():
        if not key.endswith("_warning"):
            continue
        m = _WINDOW_END_RE.search(str(msg))
        if m is None:
            continue
        lag = (end - date.fromisoformat(m.group(1))).days
        if lag > threshold_days:
            out[key[: -len("_warning")]] = lag
    return out


# ---------------------------------------------------------------------------
# check 3 helper, shared with the scorers


def _snap_split_factor(ratio: float) -> float | None:
    """Nearest plausible split factor for an observed ratio > 1, or None."""
    best = min(_SPLIT_CANDIDATES, key=lambda c: abs(ratio - c) / c)
    return best if abs(ratio - best) / best <= SPLIT_SNAP_TOLERANCE else None


def renormalize_share_series(entries: list[tuple[str, float]]):
    """Bring a share-count series onto the current (most recent) share basis.

    entries: (period_end, raw_share_count) pairs, most-recent-first, counts > 0.
    Returns (adjusted, events):
    - adjusted: per-entry share count on the current basis, aligned with the
      input; None for entries excluded by an unexplained jump.
    - events: list of dicts. {"type": "split", "newer_period_end",
      "older_period_end", "observed_ratio", "factor"} — factor is the
      multiplier applied to all older periods (>1 forward split, <1 reverse).
      {"type": "unexplained", ..., "excluded_period_ends": [...]} — jump that
      snaps to no plausible split factor; the older segment is excluded.
      {"type": "repair", "period_end", "factor", "observed_ratio"} — a single
      stale period (cover-page count lagging a split) bracketed by consistent
      counts, repaired onto the surrounding basis (a split event immediately
      undone by its exact inverse is folded into one repair event, so the flag
      text names the stale period, not a phantom pair of splits — audit b-2).
    """
    adjusted: list[float | None] = [None] * len(entries)
    events: list[dict] = []
    if not entries:
        return adjusted, events

    adjusted[0] = entries[0][1]
    factor = 1.0
    for i in range(len(entries) - 1):
        newer_end, newer = entries[i]
        older_end, older = entries[i + 1]
        r = newer / older  # raw adjacent ratio, unaffected by prior factors
        if r >= SPLIT_DETECT_RATIO or r <= 1 / SPLIT_DETECT_RATIO:
            snapped = _snap_split_factor(r if r > 1 else 1 / r)
            if snapped is None:
                events.append(
                    {
                        "type": "unexplained",
                        "newer_period_end": newer_end,
                        "older_period_end": older_end,
                        "observed_ratio": r,
                        "excluded_period_ends": [e for e, _ in entries[i + 1 :]],
                    }
                )
                return adjusted, events  # older segment stays None
            step = snapped if r > 1 else 1 / snapped
            factor *= step
            events.append(
                {
                    "type": "split",
                    "newer_period_end": newer_end,
                    "older_period_end": older_end,
                    "observed_ratio": r,
                    "factor": step,
                }
            )
        adjusted[i + 1] = older * factor
    return adjusted, _fold_repairs(events)


def _fold_repairs(events: list[dict]) -> list[dict]:
    """Fold split + exact-inverse-split at adjacent boundaries into a repair."""
    out: list[dict] = []
    i = 0
    while i < len(events):
        ev, nxt = events[i], events[i + 1] if i + 1 < len(events) else None
        if (
            nxt is not None
            and ev["type"] == "split"
            and nxt["type"] == "split"
            and ev["older_period_end"] == nxt["newer_period_end"]
            and abs(ev["factor"] * nxt["factor"] - 1.0) < 1e-9
        ):
            out.append(
                {
                    "type": "repair",
                    "period_end": ev["older_period_end"],
                    "factor": ev["factor"],
                    "observed_ratio": ev["observed_ratio"],
                }
            )
            i += 2
        else:
            out.append(ev)
            i += 1
    return out


# ---------------------------------------------------------------------------
# the pure checks


def _present_arrays(snapshot: dict, arrays) -> list[tuple[str, list]]:
    return [(name, snapshot[name]) for name in arrays if snapshot.get(name)]


def _check_ttm_warnings(snapshot: dict, arrays) -> list[dict]:
    """Check 1: edgartools stitched-TTM warnings, captured for all fields.

    Two escalations beyond the generic stitched WARN (truth-in-scoring):
    - ttm_stale_window: the stitched window ends > STALE_WINDOW_DAYS before
      the period's own end — the value describes a different era, and scorers
      must not let it earn points (A2).
    - stale_leg_dropped: fetch already dropped a stale leg from a multi-leg
      combine (A1); the drop note lives in tags_used under a *_dropped key.
    """
    grouped: dict[tuple[str, str, str], list[str]] = {}
    stale: dict[tuple[str, str], tuple[int, list[str]]] = {}
    dropped: dict[tuple[str, str, str], list[str]] = {}
    for name, periods in _present_arrays(snapshot, arrays):
        for p in periods:
            for key, msg in (p.get("tags_used") or {}).items():
                if key.endswith("_warning"):
                    field = key[: -len("_warning")]
                    grouped.setdefault((name, field, str(msg)), []).append(p["period_end"])
                elif key.endswith("_dropped"):
                    field = key[: -len("_dropped")]
                    dropped.setdefault((name, field, str(msg)), []).append(p["period_end"])
            for field, lag in stale_ttm_fields(p).items():
                worst, ends = stale.get((name, field), (0, []))
                stale[(name, field)] = (max(worst, lag), ends + [p["period_end"]])
    out = [
        finding(
            WARN,
            "ttm_stitched",
            f"{field} TTM values are edgartools-stitched, not directly filed: {msg}",
            array=name,
            field=field,
            warning=msg,
            period_ends=ends,
        )
        for (name, field, msg), ends in sorted(grouped.items())
    ]
    out += [
        finding(
            WARN,
            "ttm_stale_window",
            f"{field} TTM window ends up to {lag} days before the period end it "
            f"is stored under (threshold {STALE_WINDOW_DAYS}) — the value "
            "describes an older era and must not earn rubric points",
            array=name,
            field=field,
            lag_days=lag,
            period_ends=ends,
        )
        for (name, field), (lag, ends) in sorted(stale.items())
    ]
    out += [
        finding(
            WARN,
            "stale_leg_dropped",
            f"{field}: a stale leg was dropped from this multi-leg combine at "
            f"fetch time — {msg}",
            array=name,
            field=field,
            note=msg,
            period_ends=ends,
        )
        for (name, field, msg), ends in sorted(dropped.items())
    ]
    return out


def _check_market_cap(snapshot: dict, arrays) -> list[dict]:
    """Check 2: order-of-magnitude bounds on market_cap vs EDGAR share count."""
    mc = snapshot.get("market_cap")
    if mc is None or mc <= 0:
        return [
            finding(
                ERROR,
                "market_cap_bounds",
                f"market_cap {mc!r} is not a positive number",
                market_cap=mc,
            )
        ]
    shares = None
    for _name, periods in _present_arrays(snapshot, arrays):
        for p in periods:
            s = (p.get("balance") or {}).get("outstanding_shares")
            if s:
                shares = s
                break
        if shares:
            break
    if not shares:
        return [
            finding(
                WARN,
                "market_cap_unverifiable",
                "no outstanding share count in any period; market_cap cannot be "
                "cross-checked against EDGAR shares",
                market_cap=mc,
            )
        ]
    implied = mc / shares
    if not (IMPLIED_PRICE_MIN <= implied <= IMPLIED_PRICE_MAX):
        return [
            finding(
                ERROR,
                "market_cap_bounds",
                f"market_cap {mc:.4g} implies ${implied:.4g}/share against the "
                f"EDGAR count {shares:.4g} — outside the sanity bounds "
                f"[{IMPLIED_PRICE_MIN}, {IMPLIED_PRICE_MAX:g}]; the market cap or "
                "share basis is corrupt",
                market_cap=mc,
                shares=shares,
                implied_price=implied,
            )
        ]
    # Tightened cross-check (tightened later): when the snapshot pins its own
    # price_reference (Cboe close x filed shares), the stored market_cap must
    # re-derive to within MARKET_CAP_RELATIVE_TOLERANCE — anything wider means
    # the snapshot was edited or corrupted after fetch.
    ref = snapshot.get("price_reference") or {}
    ref_price, ref_shares = ref.get("price"), ref.get("shares")
    if ref_price and ref_shares:
        reference_cap = ref_price * ref_shares
        if reference_cap > 0 and abs(mc / reference_cap - 1) > MARKET_CAP_RELATIVE_TOLERANCE:
            return [
                finding(
                    ERROR,
                    "market_cap_reference_mismatch",
                    f"market_cap {mc:.4g} deviates "
                    f"{abs(mc / reference_cap - 1):.1%} from its own pinned "
                    f"price_reference derivation {reference_cap:.4g} "
                    f"(tolerance {MARKET_CAP_RELATIVE_TOLERANCE:.0%}); the "
                    "snapshot is internally inconsistent",
                    market_cap=mc,
                    reference_cap=reference_cap,
                )
            ]
    # Witness gate: the fetch records the yfinance cross-check when the
    # witness is reachable; a deviation past MARKET_CAP_WITNESS_TOLERANCE means
    # the derived cap's share basis is corrupt (stale pre-split dei fact, wrong
    # share class). ERROR — scorers must walk away, not price off it.
    check = snapshot.get("market_cap_check") or {}
    deviation_pct = check.get("deviation_pct")
    if deviation_pct is not None and abs(deviation_pct) / 100.0 > MARKET_CAP_WITNESS_TOLERANCE:
        return [
            finding(
                ERROR,
                "market_cap_witness_mismatch",
                f"market_cap {mc:.4g} deviates {deviation_pct:.1f}% from the "
                f"{check.get('reference_source', 'reference')} witness "
                f"{check.get('reference', 0):.4g} (tolerance "
                f"{MARKET_CAP_WITNESS_TOLERANCE:.0%}); the derived share basis "
                "is corrupt — refetch, or pass --market-cap to override",
                market_cap=mc,
                reference_cap=check.get("reference"),
                deviation_pct=deviation_pct,
            )
        ]
    return []


def _check_share_series(snapshot: dict, arrays) -> list[dict]:
    """Check 3: split-aware renormalization events on each share series."""
    out = []
    for name, periods in _present_arrays(snapshot, arrays):
        entries = [
            (p["period_end"], p["balance"]["outstanding_shares"])
            for p in periods
            if (p.get("balance") or {}).get("outstanding_shares")
        ]
        _adjusted, events = renormalize_share_series(entries)
        for ev in events:
            if ev["type"] == "repair":
                out.append(
                    finding(
                        INFO,
                        "share_count_repaired",
                        f"{name}: {ev['period_end']} share count is stale by "
                        f"x{ev['factor']:g} vs its neighbors (cover-page fact "
                        "lagging a split); repaired onto the surrounding basis",
                        array=name,
                        **{k: v for k, v in ev.items() if k != "type"},
                    )
                )
            elif ev["type"] == "split":
                out.append(
                    finding(
                        INFO,
                        "share_split_renormalized",
                        f"{name}: share counts at and before {ev['older_period_end']} "
                        "renormalized onto the current basis (split factor "
                        f"x{ev['factor']:g} at this boundary; observed jump "
                        f"x{ev['observed_ratio']:.3g} into {ev['newer_period_end']})",
                        array=name,
                        **{k: v for k, v in ev.items() if k != "type"},
                    )
                )
            else:
                out.append(
                    finding(
                        WARN,
                        "share_series_unexplained_jump",
                        f"{name}: share count jumps x{ev['observed_ratio']:.3g} into "
                        f"{ev['newer_period_end']} — no plausible split factor; "
                        f"periods {', '.join(ev['excluded_period_ends'])} excluded "
                        "from per-share history",
                        array=name,
                        **{k: v for k, v in ev.items() if k != "type"},
                    )
                )
    return out


def _check_sector(snapshot: dict, arrays) -> list[dict]:
    """Check 4: financial-sector applicability guard."""
    checked = 0
    for _name, periods in _present_arrays(snapshot, arrays):
        for p in periods:
            checked += 1
            for section, field in _SECTOR_MARKERS:
                if (p.get(section) or {}).get(field) is not None:
                    return []  # any marker present anywhere -> in-model
    if checked == 0:
        return []
    fields = ", ".join(f for _s, f in _SECTOR_MARKERS)
    return [
        finding(
            ERROR,
            "sector_applicability",
            f"{fields} are structurally absent from all {checked} periods — "
            "financial-sector filer (banks/insurers file no capex or classified "
            "balance sheet); rubric not applicable to financial-sector filers",
            marker_fields=[f for _s, f in _SECTOR_MARKERS],
            periods_checked=checked,
        )
    ]


def _check_tags_alignment(snapshot: dict, arrays) -> list[dict]:
    """Check 5a: every resolved value must have a tags_used provenance entry."""
    unattributed: dict[str, list[str]] = {}
    for name, periods in _present_arrays(snapshot, arrays):
        for p in periods:
            tags = p.get("tags_used") or {}
            for section in ("ttm", "balance"):
                for field, value in (p.get(section) or {}).items():
                    if value is not None and field not in tags:
                        unattributed.setdefault(field, []).append(
                            f"{name}:{p['period_end']}"
                        )
    return [
        finding(
            INFO,
            "tags_used_misaligned",
            f"{field} has a value but no tags_used provenance entry in "
            f"{len(where)} periods (pre-alignment snapshot: provenance stored "
            "under a pre-rename key)",
            field=field,
            periods=where,
        )
        for field, where in sorted(unattributed.items())
    ]


def _check_zero_vs_missing(snapshot: dict, arrays) -> list[dict]:
    """Check 5b: mark all-absent zero-if-absent fields — EDGAR cannot say 0.

    Debt fields escalate (truth-in-scoring): when *both* debt fields resolve
    nowhere, every debt-dependent check silently loses its input while real
    debt may simply live under tags outside the fallback lists — WARN, not
    INFO, so it reaches data_quality and gets narrated.
    """
    out: list[dict] = []
    present = _present_arrays(snapshot, arrays)
    if not present:
        return out

    def _all_absent(section: str, field: str) -> bool:
        return all(
            (p.get(section) or {}).get(field) is None
            for _name, periods in present
            for p in periods
        )

    for section, field in _OPTIONAL_ZERO_FIELDS:
        if _all_absent(section, field):
            out.append(
                finding(
                    INFO,
                    "absent_optional_field",
                    f"{field} has no XBRL tag in any period — an untagged fact and "
                    "a true zero are indistinguishable in EDGAR; the rubric treats "
                    "it as zero where zero-if-absent applies",
                    field=field,
                )
            )

    debt_absent = [f for s, f in _DEBT_FIELDS if _all_absent(s, f)]
    if len(debt_absent) == len(_DEBT_FIELDS):
        out.append(
            finding(
                WARN,
                "debt_unresolved",
                "no short- or long-term debt resolved under any known XBRL tag "
                "in any period — a debt-free filer and unresolved tags are "
                "indistinguishable, and real debt may be invisible; "
                "debt-dependent checks (debt/equity, ROIC) are scored 0 as a "
                "data gap, not treated as zero debt",
                fields=[f for _s, f in _DEBT_FIELDS],
            )
        )
    else:
        for field in debt_absent:
            out.append(
                finding(
                    INFO,
                    "absent_optional_field",
                    f"{field} has no XBRL tag in any period — an untagged fact "
                    "and a true zero are indistinguishable in EDGAR; the debt "
                    "sum treats this component as zero (the other component "
                    "resolved)",
                    field=field,
                )
            )
    return out


def _check_fundamentals_staleness(snapshot: dict, arrays) -> list[dict]:
    """Check 8 (truth-in-scoring): how stale is the diagnosis's own "present"?

    The market cap is near-live; the fundamentals are as of the latest
    quarterly period end. Beyond FUNDAMENTALS_STALENESS_DAYS of drift the
    output must state the lag rather than imply a synchronous read.
    """
    if "periods" not in arrays:
        return []
    periods = snapshot.get("periods") or []
    fetched_at = snapshot.get("fetched_at")
    if not periods or not fetched_at or not periods[0].get("period_end"):
        return []
    lag = (
        date.fromisoformat(fetched_at)
        - date.fromisoformat(periods[0]["period_end"])
    ).days
    if lag <= FUNDAMENTALS_STALENESS_DAYS:
        return []
    return [
        finding(
            WARN,
            "fundamentals_stale_vs_price",
            f"latest fundamentals period ends {periods[0]['period_end']}, "
            f"{lag} days before the snapshot date {fetched_at} — the price is "
            f"{lag} days fresher than the books it is being compared against",
            period_end=periods[0]["period_end"],
            fetched_at=fetched_at,
            lag_days=lag,
        )
    ]


def _check_manual_market_cap(snapshot: dict, arrays) -> list[dict]:
    """Check 9 (truth-in-scoring): a manual --market-cap has no price_reference,
    so the ±10% re-derivation cross-check can never fire on it. Say so."""
    if snapshot.get("market_cap_source") != _MANUAL_MARKET_CAP_SOURCE:
        return []
    return [
        finding(
            WARN,
            "market_cap_manual_unverified",
            f"market_cap {snapshot.get('market_cap'):.4g} was supplied manually "
            "(--market-cap) — it carries no pinned price_reference, so the "
            "cross-check against a quoted price never ran; the valuation rests "
            "on an unverified owner-supplied number",
            market_cap=snapshot.get("market_cap"),
        )
    ]


def _check_invariants(snapshot: dict, arrays) -> list[dict]:
    """Check 6: sign conventions (ERROR) and the balance-sheet identity."""
    out = []
    sign_violations = []
    for name, periods in _present_arrays(snapshot, arrays):
        for p in periods:
            for section, field, rule, ok in _SIGN_RULES:
                v = (p.get(section) or {}).get(field)
                if v is not None and not ok(v):
                    sign_violations.append(
                        f"{name}:{p['period_end']} {field}={v:.4g} violates {rule}"
                    )
    if sign_violations:
        out.append(
            finding(
                ERROR,
                "sign_convention",
                "sign-convention violations: " + "; ".join(sign_violations),
                violations=sign_violations,
            )
        )

    for name, periods in _present_arrays(snapshot, arrays):
        checked, violators = 0, []
        for p in periods:
            b = p.get("balance") or {}
            a = b.get("total_assets")
            liab = b.get("total_liabilities")
            e = b.get("shareholders_equity")
            if a is None or liab is None or e is None or a == 0:
                continue
            checked += 1
            gap = abs(a - (liab + e)) / abs(a)
            if gap > BALANCE_IDENTITY_TOLERANCE:
                violators.append((p["period_end"], gap))
        if not violators:
            continue
        latest_checked = next(
            (
                p["period_end"]
                for p in periods
                if all(
                    (p.get("balance") or {}).get(f) is not None
                    for f in ("total_assets", "total_liabilities", "shareholders_equity")
                )
            ),
            None,
        )
        latest_violates = violators[0][0] == latest_checked
        severity = ERROR if latest_violates or len(violators) * 2 > checked else WARN
        detail = ", ".join(f"{end} (gap {gap:.1%})" for end, gap in violators)
        out.append(
            finding(
                severity,
                "balance_identity",
                f"{name}: assets != liabilities + equity beyond "
                f"{BALANCE_IDENTITY_TOLERANCE:.0%} in {len(violators)}/{checked} "
                f"periods: {detail}"
                + (
                    ""
                    if severity == ERROR
                    else " — isolated historical periods (tag-definition drift, "
                    "e.g. pre-IPO mezzanine equity in neither tag); ratios for "
                    "those periods rest on an inconsistent balance sheet"
                ),
                array=name,
                period_ends=[end for end, _ in violators],
                gaps={end: gap for end, gap in violators},
            )
        )
    return out


# ---------------------------------------------------------------------------
# entry points


def run_checks(snapshot: dict, arrays=DEFAULT_ARRAYS) -> tuple[list[dict], list[str]]:
    """All pure checks + fetch-only findings carried from the snapshot.

    arrays limits which period arrays are inspected (Graham scores quarterly
    periods only and must stay invariant to annual_periods).
    Returns (findings, checks_run).
    """
    findings = []
    findings += _check_ttm_warnings(snapshot, arrays)
    findings += _check_market_cap(snapshot, arrays)
    findings += _check_share_series(snapshot, arrays)
    findings += _check_sector(snapshot, arrays)
    findings += _check_tags_alignment(snapshot, arrays)
    findings += _check_zero_vs_missing(snapshot, arrays)
    findings += _check_invariants(snapshot, arrays)
    findings += _check_fundamentals_staleness(snapshot, arrays)
    findings += _check_manual_market_cap(snapshot, arrays)
    checks_run = [
        "ttm_stitched_warnings",
        "market_cap_bounds",
        "share_renormalization",
        "sector_applicability",
        "tags_alignment_and_zero_marker",
        "invariants",
        "fundamentals_staleness",
        "manual_market_cap",
    ]

    stored = snapshot.get("validation") or {}
    carried = [
        f for f in stored.get("findings", []) if f.get("code") in FETCH_ONLY_CODES
    ]
    findings += carried
    if "restatement_402" in stored.get("checks_run", []):
        checks_run.append("restatement_402")
    return findings, checks_run


def data_quality(findings: list[dict], checks_run: list[str]) -> dict:
    """The diagnosis-level block: {errors, warnings, checks_run}.

    INFO findings stay snapshot-level by decision. A successful diagnosis has
    an empty errors list (scorers hard-fail on ERROR before emitting output);
    the key exists so downstream consumers/mergers see a stable shape.
    """
    return {
        "errors": [f for f in findings if f["severity"] == ERROR],
        "warnings": [f for f in findings if f["severity"] == WARN],
        "checks_run": checks_run,
    }


def restatement_excluded_years(findings: list[dict]) -> list[str]:
    """Fiscal-year period_ends the 4.02 guard says to exclude from history."""
    out = set()
    for f in findings:
        if f.get("code") == "restatement_402":
            out.update(f.get("context", {}).get("affected_period_ends", []))
    return sorted(out)
