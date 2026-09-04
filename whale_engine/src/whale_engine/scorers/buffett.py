"""Offline phase: pure function of one snapshot -> full-diagnostic dict.

Six dimensions, adapted from the upstream Buffett heuristics (see README "Provenance") (max 27 =
fundamentals 7 + consistency 3 + moat 5 + management 2 + pricing power 5 +
book value 5), with the decisions locked on the rubric ticket:

- signal: bullish if score >= 70% and MoS > 0; bearish if score < 45% or
  MoS <= -0.30; else neutral
- confidence 50-100: distance from the nearest decision boundary
- missing data: mandatory inputs hard-fail unless present in >= 5 periods;
  dividends/buybacks are zero-if-absent; per-ratio gaps score 0 and are flagged;
  dimensions with insufficient history are excluded from the denominator
  (judgment-review tuning, ticket #8), as is consistency's graduated credit
- ratios from period-end EDGAR balances; ROIC = NOPAT(21% flat) / invested cap
- ratio checks gate on None, not reference truthiness: an exact zero is data,
  not a gap — a debt-free filer (D/E 0.0) passes the debt check instead of
  scoring 0 as "unavailable" like the upstream ai-hedge-fund heuristics (intentional deviation)

Rubric v2: the history-judging dimensions — consistency, moat,
pricing power, book value, and the DCF growth derivation — read the snapshot's
annual_periods (up to 10 fiscal years) so they measure the decade
they were designed for instead of 2.5 years of seasonal quarterly steps.
Present-state inputs — fundamentals, management, owner earnings — stay on the
latest quarterly TTM, which is fresher than any fiscal-year figure. Snapshots
without annual_periods (schema v1) hard-fail: refetch rather than silently
diagnose from the shallow window. Every diagnosis carries rubric_version.

Validation layer (validation layer): diagnose runs the shared
snapshot checks first — any ERROR finding hard-fails with its message (sector
guard, market-cap bounds, sign/identity invariants); WARN findings ride the
output in a top-level `data_quality` block the subagent must narrate. Share
histories are split-aware renormalized (replacing the majority-cohort outlier
filter — the NVDA bug); fiscal years an 8-K Item 4.02 declared non-reliable
are excluded from the history dimensions. Rides rubric v2 by owner decision —
no separate rubric_version bump.

Rubric v3 (owner-signed): four judgment changes from the truth-in-scoring
BLDR audit. B1 — trend checks (moat margin trend, pricing-power gross-margin
trend) compare adjacent recent-vs-prior windows (3y each when history allows)
instead of decade endpoints, and any trend award is capped at +1 when the
last two annual steps decline monotonically (window averages can hide a
fresh peak-and-decline), so recent down years read as contraction. B2 —
confidence subtracts 5 per scored dimension fed by WARN-flagged or absent
data (floor 50); threshold-distance alone overstated certainty on dirty
snapshots. B3 — when no debt tag resolves, debt/equity falls back to
total_liabilities/equity with a looser bar (+2 below 1.0), labeled as a
fallback; the debt_unresolved WARN stays. B4 — a negative stage-1 growth
carries through stage 2 unhalved: the old cap formula was designed for
positive growth and turned decline into implied mean-reversion.

Determinism contract: same snapshot dict -> identical output dict. No I/O,
no clocks, no randomness in this module.
"""

from __future__ import annotations

from datetime import date

from .. import validation
from ..errors import MissingDataError

MAX_SCORE = 27
RUBRIC_VERSION = 3
TAX_RATE = 0.21

BULLISH_SCORE = 0.70
BEARISH_SCORE = 0.45
BEARISH_MOS = -0.30

MANDATORY_TTM = [
    "net_income",
    "depreciation_and_amortization",
    "capital_expenditure",
    "revenue",
]
MANDATORY_BALANCE = [
    "shareholders_equity",
    "outstanding_shares",
    "total_assets",
    "total_liabilities",
]
MIN_COMPLETE_PERIODS = 5
# Below 3 complete fiscal years, every history dimension is excluded and the
# DCF growth falls back — the result would be quarterly-quality wearing a v2
# stamp. Young-IPO filers with 3-4 years still diagnose; dimensions that need
# more history exclude themselves from the denominator as usual.
MIN_COMPLETE_ANNUAL = 3

# Which scored dimensions consume each snapshot field (truth-in-scoring): every
# data_quality warning that names a field gains a dimensions_affected list so
# a reader can see exactly which scores rest on degraded data. Split by the
# array the dimension reads (rubric v2): present-state dimensions and the
# owner-earnings side of valuation read periods[0]; history dimensions and the
# DCF growth window read annual_periods.
_PRESENT_FIELD_DIMENSIONS = {
    "net_income": ["fundamentals", "valuation"],
    "revenue": ["fundamentals", "valuation"],
    "operating_income": ["fundamentals"],
    "gross_profit": [],
    "capital_expenditure": ["valuation"],
    "depreciation_and_amortization": ["valuation"],
    "dividends_and_other_cash_distributions": ["management"],
    "issuance_or_purchase_of_equity_shares": ["management"],
    "shareholders_equity": ["fundamentals"],
    "short_term_debt": ["fundamentals"],
    "long_term_debt": ["fundamentals"],
    "current_assets": ["fundamentals", "valuation"],
    "current_liabilities": ["fundamentals", "valuation"],
}
_ANNUAL_FIELD_DIMENSIONS = {
    "net_income": ["consistency", "valuation"],
    "revenue": ["moat", "pricing_power"],
    "operating_income": ["moat"],
    "gross_profit": ["pricing_power"],
    "shareholders_equity": ["moat", "book_value"],
    "outstanding_shares": ["book_value"],
    "total_assets": ["moat"],
}
# Warnings that name no single field but still touch scores.
_CODE_DIMENSIONS = {
    "debt_unresolved": ["fundamentals"],
    "market_cap_manual_unverified": ["valuation"],
    "fundamentals_stale_vs_price": ["fundamentals", "management", "valuation"],
    "restatement_402": ["consistency", "moat", "pricing_power", "book_value", "valuation"],
}


def _dimensions_affected(finding: dict) -> list[str]:
    ctx = finding.get("context") or {}
    field, array = ctx.get("field"), ctx.get("array")
    if field is not None:
        if array == "annual_periods":
            return _ANNUAL_FIELD_DIMENSIONS.get(field, [])
        if array == "periods":
            return _PRESENT_FIELD_DIMENSIONS.get(field, [])
        return sorted(
            set(_PRESENT_FIELD_DIMENSIONS.get(field, []))
            | set(_ANNUAL_FIELD_DIMENSIONS.get(field, []))
        )
    return _CODE_DIMENSIONS.get(finding.get("code") or "", [])


def _link_data_quality(dq: dict) -> dict:
    """Add dimensions_affected to every warning (copies — carried snapshot
    findings are never mutated)."""
    return {
        **dq,
        "warnings": [
            {**f, "dimensions_affected": _dimensions_affected(f)}
            for f in dq["warnings"]
        ],
    }


# ---------------------------------------------------------------------------
# validation & metrics


def _is_complete(period: dict) -> bool:
    ttm, bal = period["ttm"], period["balance"]
    return all(ttm.get(f) is not None for f in MANDATORY_TTM) and all(
        bal.get(f) is not None for f in MANDATORY_BALANCE
    )


def validate(snapshot: dict) -> None:
    if snapshot.get("market_cap") is None:
        raise MissingDataError(f"{snapshot.get('ticker')}: market_cap missing from snapshot")
    periods = snapshot.get("periods", [])
    complete = [p for p in periods if _is_complete(p)]
    if len(complete) < MIN_COMPLETE_PERIODS:
        gaps = []
        for p in periods:
            missing = [f for f in MANDATORY_TTM if p["ttm"].get(f) is None] + [
                f for f in MANDATORY_BALANCE if p["balance"].get(f) is None
            ]
            if missing:
                gaps.append(f"{p['as_of_quarter']}: {', '.join(missing)}")
        raise MissingDataError(
            f"{snapshot.get('ticker')}: only {len(complete)} complete periods "
            f"(need >= {MIN_COMPLETE_PERIODS}). Gaps -- " + "; ".join(gaps)
        )
    annual = snapshot.get("annual_periods")
    if annual is None:
        raise MissingDataError(
            f"{snapshot.get('ticker')}: snapshot has no annual_periods (schema v1); "
            "rubric v2 scores history from fiscal years -- refetch the snapshot"
        )
    complete_annual = [p for p in annual if _is_complete(p)]
    if len(complete_annual) < MIN_COMPLETE_ANNUAL:
        raise MissingDataError(
            f"{snapshot.get('ticker')}: only {len(complete_annual)} complete annual periods "
            f"(need >= {MIN_COMPLETE_ANNUAL})"
        )


def _ratio(num, den):
    if num is None or den is None or den == 0:
        return None
    return num / den


def _trend_windows(values: list) -> tuple[float, float, int]:
    """Adjacent recent-vs-prior window averages (rubric v3).

    Values are most-recent-first. Window width is 3 years when history allows,
    shrinking to len//2 for short histories so the windows never overlap —
    the trend always measures the current business against the years just
    before it, never against the decade-ago baseline."""
    w = min(3, len(values) // 2)
    recent = sum(values[:w]) / w
    prior = sum(values[w : 2 * w]) / w
    return recent, prior, w


def _rolling_over(values: list) -> bool:
    """Window averages can hide a fresh peak-and-decline (rubric v3
    guard): true when the last two annual steps decline monotonically, which
    caps any trend award at +1 (values are most-recent-first)."""
    return len(values) >= 3 and values[0] < values[1] < values[2]


def _gate_stale_present(periods: list, annual: list, flags: list) -> list:
    """No point from a stale-flagged value (truth-in-scoring).

    A TTM field in the present-state period whose stitched window ends beyond
    validation.STALE_WINDOW_DAYS before the period's own end describes an
    older era. Policy, in order: (a) fall back to the same field's clean
    latest-fiscal-year value when one exists; (b) discard it so the consuming
    check scores 0 with the standard missing-input flag; (c) mandatory inputs
    with no clean fallback are retained but flagged loudly — zeroing net
    income or capex would corrupt the valuation worse than the staleness does.
    Returns a new periods list; the snapshot is never mutated.
    """
    stale = validation.stale_ttm_fields(periods[0])
    if not stale:
        return periods
    patched = {**periods[0], "ttm": dict(periods[0]["ttm"])}
    annual_stale = validation.stale_ttm_fields(annual[0]) if annual else {}
    for field, lag in sorted(stale.items()):
        annual_value = annual[0]["ttm"].get(field) if annual else None
        fy = annual[0]["period_end"][:4] if annual else "?"
        if annual_value is not None and field not in annual_stale:
            patched["ttm"][field] = annual_value
            flags.append(
                f"stale_data: {field} TTM window ends {lag} days before the "
                f"period end; using the clean FY{fy} annual value instead"
            )
        elif field in MANDATORY_TTM:
            flags.append(
                f"stale_data: {field} TTM window ends {lag} days before the "
                "period end and no clean annual fallback exists; stale value "
                "retained (mandatory input) — treat dependent scores with care"
            )
        else:
            patched["ttm"][field] = None
            flags.append(
                f"stale_data: {field} TTM window ends {lag} days before the "
                "period end and no clean annual fallback exists; value "
                "discarded, dependent checks score 0"
            )
    return [patched] + periods[1:]


def recent_trajectory(periods: list) -> dict:
    """Unscored recent-direction context (truth-in-scoring, per the unscored-context
    cited-evidence pattern): the last four quarterly points, engine-computed,
    so narration can state when the present contradicts a decade-earned score.
    Every flow in the snapshot is a 12-month window, so ttm_net_income is a
    smoothed trajectory, not single-quarter earnings."""
    points = []
    for p in periods[:4]:
        eq = p["balance"].get("shareholders_equity")
        sh = p["balance"].get("outstanding_shares")
        points.append(
            {
                "period_end": p["period_end"],
                "ttm_net_income": p["ttm"].get("net_income"),
                "shareholders_equity": eq,
                "bvps": eq / sh if eq is not None and sh else None,
            }
        )
    return {
        "note": (
            "unscored context: last four quarterly TTM windows, most recent "
            "first; narration must state the direction when it contradicts a "
            "high history score"
        ),
        "points": points,
    }


def compute_metrics(period: dict) -> dict:
    """Locked ratio formulas, period-end balances."""
    ttm, bal = period["ttm"], period["balance"]
    st_debt = bal.get("short_term_debt")
    lt_debt = bal.get("long_term_debt")
    debt = None if st_debt is None and lt_debt is None else (st_debt or 0.0) + (lt_debt or 0.0)

    roic = None
    op = ttm.get("operating_income")
    if op is not None and debt is not None and bal.get("shareholders_equity") is not None:
        cash = bal.get("cash_and_equivalents")
        if cash is not None:
            invested = debt + bal["shareholders_equity"] - cash
            if invested > 0:
                roic = op * (1 - TAX_RATE) / invested

    return {
        "return_on_equity": _ratio(ttm.get("net_income"), bal.get("shareholders_equity")),
        "debt_to_equity": _ratio(debt, bal.get("shareholders_equity")),
        "liabilities_to_equity": _ratio(
            bal.get("total_liabilities"), bal.get("shareholders_equity")
        ),
        "operating_margin": _ratio(op, ttm.get("revenue")),
        "current_ratio": _ratio(bal.get("current_assets"), bal.get("current_liabilities")),
        "gross_margin": _ratio(ttm.get("gross_profit"), ttm.get("revenue")),
        "asset_turnover": _ratio(ttm.get("revenue"), bal.get("total_assets")),
        "return_on_invested_capital": roic,
    }


# ---------------------------------------------------------------------------
# dimensions (periods and metrics lists are most-recent-first, as in reference)


def analyze_fundamentals(m: dict, flags: list) -> dict:
    score, details = 0, []
    roe = m["return_on_equity"]
    if roe is not None and roe > 0.15:
        score += 2
        details.append(f"ROE {roe:.1%} > 15% ✓ (+2)")
    elif roe is not None:
        details.append(f"ROE {roe:.1%} <= 15% ✗ (+0)")
    else:
        details.append("ROE unavailable (+0)")
        flags.append("fundamentals: return_on_equity missing, scored 0")

    dte = m["debt_to_equity"]
    lte = m.get("liabilities_to_equity")
    if dte is not None and dte < 0.5:
        score += 2
        details.append(f"Debt/equity {dte:.2f} < 0.5 ✓ (+2)")
    elif dte is not None:
        details.append(f"Debt/equity {dte:.2f} >= 0.5 ✗ (+0)")
    elif lte is not None:
        # Rubric v3: when no debt tag resolves, score total
        # liabilities/equity against a ~2x looser bar — liabilities include
        # payables and deferred revenue, so 1.0 here approximates the 0.5 D/E
        # standard. The debt_unresolved WARN still rides data_quality.
        if lte < 1.0:
            score += 2
            details.append(
                f"Liabilities/equity {lte:.2f} < 1.0 ✓ (+2, fallback: no debt tag resolved)"
            )
        else:
            details.append(
                f"Liabilities/equity {lte:.2f} >= 1.0 ✗ (+0, fallback: no debt tag resolved)"
            )
        flags.append(
            "fundamentals: debt_to_equity unresolved; scored total_liabilities/equity "
            "fallback at the 1.0 bar"
        )
    else:
        details.append("Debt/equity unavailable (+0)")
        flags.append("fundamentals: debt_to_equity missing, scored 0")

    om = m["operating_margin"]
    if om is not None and om > 0.15:
        score += 2
        details.append(f"Operating margin {om:.1%} > 15% ✓ (+2)")
    elif om is not None:
        details.append(f"Operating margin {om:.1%} <= 15% ✗ (+0)")
    else:
        details.append("Operating margin unavailable (+0)")
        flags.append("fundamentals: operating_margin missing, scored 0")

    cr = m["current_ratio"]
    if cr is not None and cr > 1.5:
        score += 1
        details.append(f"Current ratio {cr:.2f} > 1.5 ✓ (+1)")
    elif cr is not None:
        details.append(f"Current ratio {cr:.2f} <= 1.5 ✗ (+0)")
    else:
        details.append("Current ratio unavailable (+0)")
        flags.append("fundamentals: current_ratio missing, scored 0")

    return {"score": score, "max": 7, "details": details}


def analyze_consistency(periods: list, flags: list) -> dict:
    details = []
    # None-gated, not truthiness (truth-in-scoring): a true-zero year is data.
    earnings = [
        p["ttm"]["net_income"] for p in periods if p["ttm"].get("net_income") is not None
    ]
    n_missing = len(periods) - len(earnings)
    if n_missing:
        flags.append(
            f"consistency: {n_missing} fiscal years missing net_income excluded "
            "from the streak"
        )
    if len(earnings) < 4:
        flags.append("consistency: fewer than 4 earnings periods, excluded from denominator")
        return {
            "score": 0,
            "max": 3,
            "excluded": True,
            "details": ["Insufficient earnings history (excluded)"],
        }
    # Graduated credit (judgment-review tuning): monotonic = 3, at most one
    # down-step = 2, positive overall trend = 1.
    steps = len(earnings) - 1
    grew_steps = sum(1 for i in range(steps) if earnings[i] > earnings[i + 1])
    if grew_steps == steps:
        score = 3
        details.append(f"Earnings grew every period across {len(earnings)} TTM windows ✓ (+3)")
    elif grew_steps >= steps - 1:
        score = 2
        details.append(
            f"Earnings grew in {grew_steps}/{steps} steps across {len(earnings)} TTM windows ✓ (+2)"
        )
    elif earnings[0] > earnings[-1]:
        score = 1
        details.append(
            f"Earnings up oldest-to-latest but grew in only {grew_steps}/{steps} steps ✓ (+1)"
        )
    else:
        score = 0
        details.append(f"Earnings flat or declining: grew in {grew_steps}/{steps} steps ✗ (+0)")
    if earnings[-1] != 0:
        total_growth = (earnings[0] - earnings[-1]) / abs(earnings[-1])
        details.append(f"Total earnings growth {total_growth:.1%} oldest-to-latest")
    return {"score": score, "max": 3, "details": details}


def analyze_moat(metrics: list, flags: list) -> dict:
    if len(metrics) < 5:
        flags.append("moat: fewer than 5 metric periods, excluded from denominator")
        return {
            "score": 0,
            "max": 5,
            "excluded": True,
            "details": ["Insufficient history for moat analysis (excluded)"],
        }
    score, details = 0, []

    roes = [m["return_on_equity"] for m in metrics if m["return_on_equity"] is not None]
    if len(roes) >= 5:
        high = sum(1 for r in roes if r > 0.15)
        consistency = high / len(roes)
        avg_roe = sum(roes) / len(roes)
        if consistency >= 0.8:
            score += 2
            details.append(f"ROE > 15% in {high}/{len(roes)} periods (avg {avg_roe:.1%}) ✓ (+2)")
        elif consistency >= 0.6:
            score += 1
            details.append(f"ROE > 15% in {high}/{len(roes)} periods ✓ (+1)")
        else:
            details.append(f"ROE > 15% in only {high}/{len(roes)} periods ✗ (+0)")
    else:
        details.append("Insufficient ROE history (+0)")
        flags.append("moat: insufficient ROE history for consistency check")

    margins = [m["operating_margin"] for m in metrics if m["operating_margin"] is not None]
    if len(margins) >= 5:
        avg = sum(margins) / len(margins)
        recent, older, w = _trend_windows(margins)
        if avg > 0.2 and recent >= older and not _rolling_over(margins):
            score += 1
            details.append(
                f"Operating margins avg {avg:.1%} > 20% and stable/improving "
                f"(recent {w}y {recent:.1%} >= prior {w}y {older:.1%}) ✓ (+1)"
            )
        elif avg > 0.2 and recent >= older:
            details.append(
                f"Operating margins avg {avg:.1%} > 20% and recent {w}y "
                f"{recent:.1%} >= prior {w}y {older:.1%}, but the last 2 annual "
                "steps decline — rolling over ✗ (+0)"
            )
        else:
            details.append(
                f"Operating margins avg {avg:.1%} "
                f"(recent {w}y {recent:.1%} vs prior {w}y {older:.1%}) ✗ (+0)"
            )
    else:
        details.append("Insufficient operating-margin history (+0)")
        flags.append("moat: fewer than 5 operating-margin periods, margin check scored 0")

    turnovers = [m["asset_turnover"] for m in metrics if m["asset_turnover"] is not None]
    if len(turnovers) >= 3:
        if any(t > 1.0 for t in turnovers):
            score += 1
            details.append("Asset turnover > 1.0 observed ✓ (+1)")
        else:
            details.append("Asset turnover never above 1.0 ✗ (+0)")
    else:
        details.append("Insufficient asset-turnover history (+0)")
        flags.append("moat: fewer than 3 asset-turnover periods, turnover check scored 0")

    if len(roes) >= 5 and len(margins) >= 5:
        roe_avg = sum(roes) / len(roes)
        roe_var = sum((r - roe_avg) ** 2 for r in roes) / len(roes)
        roe_stab = 1 - (roe_var**0.5) / roe_avg if roe_avg > 0 else 0
        m_avg = sum(margins) / len(margins)
        m_var = sum((x - m_avg) ** 2 for x in margins) / len(margins)
        m_stab = 1 - (m_var**0.5) / m_avg if m_avg > 0 else 0
        stability = (roe_stab + m_stab) / 2
        if stability > 0.7:
            score += 1
            details.append(f"Performance stability {stability:.1%} > 70% ✓ (+1)")
        else:
            details.append(f"Performance stability {stability:.1%} <= 70% ✗ (+0)")
    else:
        details.append("Insufficient history for the stability check (+0)")
        flags.append("moat: fewer than 5 ROE or margin periods, stability check scored 0")

    return {"score": min(score, 5), "max": 5, "details": details}


def analyze_management(periods: list, flags: list) -> dict:
    score, details = 0, []
    latest = periods[0]["ttm"]
    net_equity = latest.get("issuance_or_purchase_of_equity_shares")
    if net_equity is None:
        details.append("Buyback/issuance data absent, treated as zero (+0)")
        flags.append("management: issuance_or_purchase_of_equity_shares absent, treated as 0")
    elif net_equity < 0:
        score += 1
        details.append(f"Net share repurchases of ${-net_equity:,.0f} TTM ✓ (+1)")
    elif net_equity > 0:
        details.append(f"Net share issuance of ${net_equity:,.0f} TTM (dilution) ✗ (+0)")
    else:
        details.append("No net issuance or buyback (+0)")

    dividends = latest.get("dividends_and_other_cash_distributions")
    if dividends is not None and dividends < 0:
        score += 1
        details.append(f"Dividends paid: ${-dividends:,.0f} TTM ✓ (+1)")
    else:
        details.append("No or minimal dividends ✗ (+0)")
        if dividends is None:
            flags.append("management: dividends absent, treated as 0")

    return {"score": score, "max": 2, "details": details}


def analyze_pricing_power(periods: list, flags: list) -> dict:
    score, details = 0, []
    margins = []
    for p in periods:
        gm = _ratio(p["ttm"].get("gross_profit"), p["ttm"].get("revenue"))
        if gm is not None:
            margins.append(gm)
    if len(margins) < 3:
        flags.append("pricing_power: fewer than 3 gross-margin periods, excluded from denominator")
        return {
            "score": 0,
            "max": 5,
            "excluded": True,
            "details": ["Insufficient gross margin history (excluded)"],
        }

    recent, older, w = _trend_windows(margins)
    if recent > older + 0.02 and not _rolling_over(margins):
        score += 3
        details.append(
            f"Gross margin expanding (prior {w}y -> recent {w}y): "
            f"{older:.1%} -> {recent:.1%} ✓ (+3)"
        )
    elif recent > older and not _rolling_over(margins):
        score += 2
        details.append(
            f"Gross margin improving (prior {w}y -> recent {w}y): "
            f"{older:.1%} -> {recent:.1%} ✓ (+2)"
        )
    elif recent > older:
        score += 1
        details.append(
            f"Gross margin recent {w}y {recent:.1%} above prior {w}y {older:.1%}, "
            "but the last 2 annual steps decline — rolling over, capped ✓ (+1)"
        )
    elif abs(recent - older) < 0.01:
        score += 1
        details.append(f"Gross margin stable near {recent:.1%} (recent {w}y vs prior {w}y) ✓ (+1)")
    else:
        details.append(
            f"Gross margin declining (prior {w}y -> recent {w}y): "
            f"{older:.1%} -> {recent:.1%} ✗ (+0)"
        )

    avg = sum(margins) / len(margins)
    if avg > 0.5:
        score += 2
        details.append(f"Average gross margin {avg:.1%} > 50% ✓ (+2)")
    elif avg > 0.3:
        score += 1
        details.append(f"Average gross margin {avg:.1%} > 30% ✓ (+1)")
    else:
        details.append(f"Average gross margin {avg:.1%} <= 30% (+0)")

    return {"score": min(score, 5), "max": 5, "details": details}


def analyze_book_value(periods: list, flags: list) -> dict:
    # None-gated equity (truth-in-scoring): a true-zero book value is data, not a
    # gap. Shares stay truthiness-gated — zero shares cannot denominate.
    usable, dropped = [], []
    for p in periods:
        if (
            p["balance"].get("shareholders_equity") is not None
            and p["balance"].get("outstanding_shares")
        ):
            usable.append(p)
        else:
            dropped.append(p["period_end"])
    if dropped:
        flags.append(
            f"book_value: {len(dropped)} periods missing equity or share count "
            f"excluded ({', '.join(dropped)})"
        )
    # Split-aware renormalization (replacing the majority-cohort
    # outlier filter that excluded NVDA's *correct* post-split years): jumps
    # consistent with a split rebase older counts onto the current share basis,
    # so BVPS is comparable across the whole decade; jumps no split explains
    # exclude the older segment with a flag.
    adjusted, events = validation.renormalize_share_series(
        [(p["period_end"], p["balance"]["outstanding_shares"]) for p in usable]
    )
    for ev in events:
        if ev["type"] == "repair":
            flags.append(
                f"book_value: {ev['period_end']} share count is stale by "
                f"x{ev['factor']:g} vs its neighbors (cover-page fact lagging a "
                "split); repaired onto the surrounding basis"
            )
        elif ev["type"] == "split":
            flags.append(
                f"book_value: share counts at and before {ev['older_period_end']} "
                "renormalized onto the current basis (split factor "
                f"x{ev['factor']:g} at this boundary; observed jump "
                f"x{ev['observed_ratio']:.3g})"
            )
        else:
            flags.append(
                f"book_value: share count jumps x{ev['observed_ratio']:.3g} into "
                f"{ev['newer_period_end']} with no plausible split factor; periods "
                f"{', '.join(ev['excluded_period_ends'])} excluded"
            )
    pairs = [(p, adj) for p, adj in zip(usable, adjusted, strict=True) if adj is not None]
    usable = [p for p, _ in pairs]
    book_values = [p["balance"]["shareholders_equity"] / adj for p, adj in pairs]
    if len(book_values) < 3:
        flags.append("book_value: fewer than 3 BVPS periods, excluded from denominator")
        return {
            "score": 0,
            "max": 5,
            "excluded": True,
            "details": ["Insufficient book value history (excluded)"],
        }

    score, details = 0, []
    grew = sum(1 for i in range(len(book_values) - 1) if book_values[i] > book_values[i + 1])
    rate = grew / (len(book_values) - 1)
    if rate >= 0.8:
        score += 3
        details.append(f"BVPS grew in {grew}/{len(book_values) - 1} periods ✓ (+3)")
    elif rate >= 0.6:
        score += 2
        details.append(f"BVPS grew in {grew}/{len(book_values) - 1} periods ✓ (+2)")
    elif rate >= 0.4:
        score += 1
        details.append(f"BVPS grew in {grew}/{len(book_values) - 1} periods ✓ (+1)")
    else:
        details.append(f"BVPS grew in only {grew}/{len(book_values) - 1} periods ✗ (+0)")

    oldest, latest = book_values[-1], book_values[0]
    # Span the actual period_end dates: counting entries would mis-annualize
    # whenever the cadence isn't exactly yearly (quarterly lists, gap years).
    years = (
        date.fromisoformat(usable[0]["period_end"]) - date.fromisoformat(usable[-1]["period_end"])
    ).days / 365.25
    if years <= 0:
        details.append("BVPS CAGR not meaningful over a zero-length span (+0)")
    elif oldest > 0 and latest > 0:
        cagr = (latest / oldest) ** (1 / years) - 1
        if cagr > 0.15:
            score += 2
            details.append(f"BVPS CAGR {cagr:.1%} > 15% ✓ (+2)")
        elif cagr > 0.1:
            score += 1
            details.append(f"BVPS CAGR {cagr:.1%} > 10% ✓ (+1)")
        else:
            details.append(f"BVPS CAGR {cagr:.1%} (+0)")
    elif oldest < 0 < latest:
        score += 3
        details.append("BVPS improved from negative to positive ✓ (+3)")
    else:
        details.append("BVPS CAGR not meaningful with negative book value (+0)")

    return {"score": min(score, 5), "max": 5, "details": details}


# ---------------------------------------------------------------------------
# valuation (faithful port of owner earnings + three-stage DCF)


def estimate_maintenance_capex(periods: list) -> float:
    capex_ratios = []
    for p in periods[:5]:
        capex, revenue = p["ttm"].get("capital_expenditure"), p["ttm"].get("revenue")
        if capex and revenue and revenue > 0:
            capex_ratios.append(abs(capex) / revenue)

    latest = periods[0]["ttm"]
    latest_capex = abs(latest.get("capital_expenditure") or 0)
    latest_dep = latest.get("depreciation_and_amortization") or 0

    method_1 = latest_capex * 0.85
    method_2 = latest_dep
    if len(capex_ratios) >= 3:
        avg_ratio = sum(capex_ratios) / len(capex_ratios)
        latest_revenue = latest.get("revenue") or 0
        method_3 = avg_ratio * latest_revenue
        return sorted([method_1, method_2, method_3])[1]
    return max(method_1, method_2)


def calculate_owner_earnings(periods: list) -> dict:
    latest = periods[0]["ttm"]
    net_income = latest.get("net_income")
    depreciation = latest.get("depreciation_and_amortization")
    capex = latest.get("capital_expenditure")
    if net_income is None or depreciation is None or capex is None:
        raise MissingDataError("owner earnings: net income, D&A, or capex missing in latest period")

    maintenance_capex = estimate_maintenance_capex(periods)

    # Faithful to reference: truthiness (not None-ness) gates the adjustment.
    working_capital_change = 0.0
    if len(periods) >= 2:
        ca0 = periods[0]["balance"].get("current_assets")
        cl0 = periods[0]["balance"].get("current_liabilities")
        ca1 = periods[1]["balance"].get("current_assets")
        cl1 = periods[1]["balance"].get("current_liabilities")
        if all([ca0, cl0, ca1, cl1]):
            working_capital_change = (ca0 - cl0) - (ca1 - cl1)

    return {
        "owner_earnings": net_income + depreciation - maintenance_capex - working_capital_change,
        "net_income": net_income,
        "depreciation": depreciation,
        "maintenance_capex": maintenance_capex,
        "working_capital_change": working_capital_change,
        "total_capex": abs(capex),
    }


def calculate_intrinsic_value(periods: list, annual_periods: list) -> dict:
    if len(periods) < 3:
        raise MissingDataError("intrinsic value: fewer than 3 periods")
    earnings_data = calculate_owner_earnings(periods)
    owner_earnings = earnings_data["owner_earnings"]

    # Growth from the 5 most recent fiscal years. Deliberate deviation from
    # the upstream ai-hedge-fund heuristics, which fed 5 quarterly-spaced TTM
    # windows (~1 year of real span) into a formula that divides by len-1 "years" — understating any
    # steady grower's rate ~4x and amplifying seasonality into the sign.
    historical = [p["ttm"]["net_income"] for p in annual_periods[:5] if p["ttm"].get("net_income")]
    # Both endpoints must be positive: a negative ratio raised to 1/years is
    # complex (reference bug — it only guarded the oldest value).
    # raw_growth_cagr rides the output (truth-in-scoring): the clamp to
    # [-5%, +15%] can sit far from reality (BLDR's actual 5y CAGR is -29%),
    # and calling the result "conservative" without stating the clamp misleads.
    raw_growth = None
    if len(historical) >= 3 and historical[-1] > 0 and historical[0] > 0:
        years = len(historical) - 1
        raw_growth = (historical[0] / historical[-1]) ** (1 / years) - 1
        growth = max(-0.05, min(raw_growth, 0.15)) * 0.7
    else:
        growth = 0.03

    stage1_growth = min(growth, 0.08)
    # Rubric v3: the half-and-cap was designed for positive
    # growth; halving a decline modeled unearned mean reversion. A declining
    # stage 1 carries its full rate through stage 2.
    stage2_growth = growth if growth < 0 else min(growth * 0.5, 0.04)
    terminal_growth = 0.025
    discount = 0.10
    stage1_years = stage2_years = 5

    stage1_pv = sum(
        owner_earnings * (1 + stage1_growth) ** y / (1 + discount) ** y
        for y in range(1, stage1_years + 1)
    )
    stage1_final = owner_earnings * (1 + stage1_growth) ** stage1_years
    stage2_pv = sum(
        stage1_final * (1 + stage2_growth) ** y / (1 + discount) ** (stage1_years + y)
        for y in range(1, stage2_years + 1)
    )
    final = stage1_final * (1 + stage2_growth) ** stage2_years
    terminal_value = final * (1 + terminal_growth) / (discount - terminal_growth)
    terminal_pv = terminal_value / (1 + discount) ** (stage1_years + stage2_years)

    intrinsic = stage1_pv + stage2_pv + terminal_pv
    return {
        "intrinsic_value": intrinsic * 0.85,  # upstream ai-hedge-fund 15% conservatism haircut
        "raw_intrinsic_value": intrinsic,
        "owner_earnings": owner_earnings,
        "owner_earnings_components": earnings_data,
        "dcf_stages": {
            "raw_growth_cagr": raw_growth,
            "growth_clamped": raw_growth is not None
            and not (-0.05 <= raw_growth <= 0.15),
            "growth_fallback": raw_growth is None,
            "stage1_growth": stage1_growth,
            "stage2_growth": stage2_growth,
            "terminal_growth": terminal_growth,
            "discount_rate": discount,
            "stage1_years": stage1_years,
            "stage2_years": stage2_years,
            "stage1_pv": stage1_pv,
            "stage2_pv": stage2_pv,
            "terminal_pv": terminal_pv,
        },
    }


# ---------------------------------------------------------------------------
# signal, confidence, diagnosis


def compute_signal(score_pct: float, mos: float) -> str:
    if score_pct >= BULLISH_SCORE and mos > 0:
        return "bullish"
    if score_pct < BEARISH_SCORE or mos <= BEARISH_MOS:
        return "bearish"
    return "neutral"


def compute_confidence(score_pct: float, mos: float) -> int:
    score_dist = min(abs(score_pct - BULLISH_SCORE), abs(score_pct - BEARISH_SCORE))
    mos_dist = min(abs(mos - 0.0), abs(mos - BEARISH_MOS))
    mos_dist = min(mos_dist, 0.50)
    return round(50 + 50 * min(1.0, 0.6 * score_dist / 0.25 + 0.4 * mos_dist / 0.50))


def _affected_dimensions(dimensions: dict, dq_warnings: list, flags: list) -> list[str]:
    """Scored dimensions (plus valuation) fed by WARN-flagged or absent data
    (rubric v3). Sources: dimensions_affected on data_quality
    warnings, and engine flags that mark a missing/absent input or a stale
    value. Bookkeeping flags (split renormalization, denominator exclusions)
    are not data degradation and do not count."""
    scored = {n for n, d in dimensions.items() if not d.get("excluded")}
    scored.add("valuation")
    affected: set[str] = set()
    for w in dq_warnings:
        affected |= set(w.get("dimensions_affected", [])) & scored
    for fl in flags:
        prefix, _, rest = fl.partition(": ")
        if prefix in scored and ("missing" in rest or "absent" in rest):
            affected.add(prefix)
        elif prefix == "stale_data":
            field = rest.split(" ", 1)[0]
            affected |= set(_PRESENT_FIELD_DIMENSIONS.get(field, [])) & scored
    return sorted(affected)


def diagnose(snapshot: dict) -> dict:
    # Validation layer first: an ERROR finding (sector inapplicability,
    # market-cap out of bounds, invariant violations) is a better message than
    # the generic missing-data gap report, and hard-fails by standing rule.
    findings, checks_run = validation.run_checks(snapshot)
    errors = [f for f in findings if f["severity"] == validation.ERROR]
    if errors:
        raise MissingDataError(
            f"{snapshot.get('ticker')}: validation failed -- "
            + "; ".join(f["message"] for f in errors)
        )

    validate(snapshot)
    periods = snapshot["periods"]
    annual = snapshot["annual_periods"]
    flags: list[str] = []

    # 8-K Item 4.02 restatement guard (fetch-time finding): fiscal years
    # declared non-reliable are excluded from every annual consumer — history
    # dimensions and the DCF growth window (standard renormalization path).
    excluded_years = validation.restatement_excluded_years(findings)
    if excluded_years:
        annual = [p for p in annual if p["period_end"] not in excluded_years]
        flags.append(
            "restatement: fiscal years "
            + ", ".join(excluded_years)
            + " excluded from history dimensions (8-K Item 4.02 non-reliance)"
        )
        if len([p for p in annual if _is_complete(p)]) < MIN_COMPLETE_ANNUAL:
            raise MissingDataError(
                f"{snapshot.get('ticker')}: fewer than {MIN_COMPLETE_ANNUAL} "
                "complete annual periods remain after excluding restated fiscal "
                "years " + ", ".join(excluded_years)
            )

    # No point from a stale-flagged value (truth-in-scoring): gate the
    # present-state period before any dimension reads it. The raw snapshot
    # periods stay untouched for the trajectory block below.
    raw_periods = periods
    periods = _gate_stale_present(periods, annual, flags)

    metrics = [compute_metrics(p) for p in periods]
    annual_metrics = [compute_metrics(p) for p in annual]

    # Present-state dimensions read the latest quarterly TTM; history-judging
    # dimensions read fiscal years (rubric v2).
    dimensions = {
        "fundamentals": analyze_fundamentals(metrics[0], flags),
        "consistency": analyze_consistency(annual, flags),
        "moat": analyze_moat(annual_metrics, flags),
        "management": analyze_management(periods, flags),
        "pricing_power": analyze_pricing_power(annual, flags),
        "book_value": analyze_book_value(annual, flags),
    }

    # Renormalize (judgment-review tuning): dimensions with insufficient data
    # are excluded from the denominator rather than counted as zeros.
    total = sum(d["score"] for d in dimensions.values())
    max_effective = sum(d["max"] for d in dimensions.values() if not d.get("excluded"))
    if max_effective == 0:
        raise MissingDataError(f"{snapshot['ticker']}: no scorable dimensions")
    score_pct = total / max_effective

    valuation = calculate_intrinsic_value(periods, annual)
    market_cap = snapshot["market_cap"]
    mos = (valuation["intrinsic_value"] - market_cap) / market_cap

    # Quality-aware confidence (rubric v3): -5 per scored
    # dimension fed by WARN-flagged or absent data, floor 50.
    data_quality = _link_data_quality(validation.data_quality(findings, checks_run))
    affected = _affected_dimensions(dimensions, data_quality["warnings"], flags)
    base_confidence = compute_confidence(score_pct, mos)
    confidence = max(50, base_confidence - 5 * len(affected))

    result = {
        "ticker": snapshot["ticker"],
        "rubric_version": RUBRIC_VERSION,
        "signal": compute_signal(score_pct, mos),
        "confidence": confidence,
        "confidence_detail": {
            "base": base_confidence,
            "data_quality_penalty": 5 * len(affected),
            "affected_dimensions": affected,
        },
        "score": {
            "total": total,
            "max": max_effective,
            "max_possible": MAX_SCORE,
            "pct": round(score_pct, 4),
        },
        "dimensions": dimensions,
        "valuation": {
            "intrinsic_value": valuation["intrinsic_value"],
            "raw_intrinsic_value": valuation["raw_intrinsic_value"],
            "owner_earnings": valuation["owner_earnings"],
            "owner_earnings_components": valuation["owner_earnings_components"],
            "market_cap": market_cap,
            "margin_of_safety": round(mos, 4),
            "dcf_stages": valuation["dcf_stages"],
        },
        "recent_trajectory": recent_trajectory(raw_periods),
        "flags": flags,
        "data_quality": data_quality,
        "provenance": {
            "snapshot_fetched_at": snapshot["fetched_at"],
            "market_cap_source": snapshot["market_cap_source"],
            "source": snapshot["source"],
            "periods": [p["period_end"] for p in periods],
            "annual_periods": [p["period_end"] for p in annual],
        },
    }
    # Unscored context: pass the whale-agnostic insider_activity
    # section through verbatim so the subagent can cite it. Never scored;
    # absent from snapshots fetched before the section existed.
    if "insider_activity" in snapshot:
        result["insider_activity"] = snapshot["insider_activity"]
    return result
