"""Snapshot validation layer (ticket #48, implementing the #44 decision).

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

ERROR = "ERROR"
WARN = "WARN"
INFO = "INFO"

# --- market-cap bounds (check 2) -------------------------------------------
# Loose order-of-magnitude bounds on market_cap / outstanding_shares: with no
# independent price source yet, this only catches unit-scale corruption (cap
# reported in thousands, share-count basis mismatch, ...). Ticket #50 replaces
# the price source; once a snapshot carries an independent share price, tighten
# this to |market_cap / (shares * price) - 1| <= MARKET_CAP_RELATIVE_TOLERANCE.
IMPLIED_PRICE_MIN = 0.10  # USD per share
IMPLIED_PRICE_MAX = 1_000_000.0  # BRK.A trades ~$7e5; anything above is corrupt
MARKET_CAP_RELATIVE_TOLERANCE = 0.10  # for the future shares*price cross-check

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
    ("balance", "short_term_debt"),
    ("balance", "long_term_debt"),
]

# Findings only fetch time can produce; diagnose-time run_checks carries them
# forward from the snapshot's stored validation section.
FETCH_ONLY_CODES = {
    "restatement_402",
    "restatement_guard_unavailable",
    # Fetch-path findings from the filings sidecar (#49), yfinance
    # cross-check (#50) and Form 4 insider fetch (#52): only observable at
    # fetch time, so diagnoses must carry them forward from the snapshot.
    "filings_sidecar_extraction_failed",
    "yfinance-crosscheck-unavailable",
    "form4_fetch_failed",
}

DEFAULT_ARRAYS = ("periods", "annual_periods")


def finding(severity: str, code: str, message: str, **context) -> dict:
    return {"severity": severity, "code": code, "message": message, "context": context}


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
    """Check 1: edgartools stitched-TTM warnings, captured for all fields."""
    grouped: dict[tuple[str, str, str], list[str]] = {}
    for name, periods in _present_arrays(snapshot, arrays):
        for p in periods:
            for key, msg in (p.get("tags_used") or {}).items():
                if key.endswith("_warning"):
                    field = key[: -len("_warning")]
                    grouped.setdefault((name, field, str(msg)), []).append(p["period_end"])
    return [
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
    """Check 5b: mark all-absent zero-if-absent fields — EDGAR cannot say 0."""
    out = []
    present = _present_arrays(snapshot, arrays)
    if not present:
        return out
    for section, field in _OPTIONAL_ZERO_FIELDS:
        if all(
            (p.get(section) or {}).get(field) is None
            for _name, periods in present
            for p in periods
        ):
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
    return out


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
            a, l, e = b.get("total_assets"), b.get("total_liabilities"), b.get(
                "shareholders_equity"
            )
            if a is None or l is None or e is None or a == 0:
                continue
            checked += 1
            gap = abs(a - (l + e)) / abs(a)
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
    checks_run = [
        "ttm_stitched_warnings",
        "market_cap_bounds",
        "share_renormalization",
        "sector_applicability",
        "tags_alignment_and_zero_marker",
        "invariants",
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
    """The diagnosis-level block (#44): {errors, warnings, checks_run}.

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
