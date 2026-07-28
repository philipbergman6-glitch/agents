"""Offline phase: pure function of one snapshot -> full-diagnostic dict.

Peter Lynch GARP rubric v1 (max 15 = growth 6 + valuation 5 + fundamentals 4),
ported from reference/peter_lynch.py with the decisions locked on the rubric
ticket (#64, from the #63 owner grilling):

- sentiment and insider factors dropped (no snapshot data source); the three
  remaining dimensions reweighted to the whole score (40/33/27 -> 6/5/4)
- growth is 5-year CAGR everywhere (the reference scores growth as total
  first-vs-last change while PEG uses CAGR — the same bug upstream half-fixed):
  revenue and EPS CAGR over the 5 most recent complete annual periods, tiers
  >=20% / >=10% / >=3%; EPS derived per period as net_income /
  outstanding_shares on the shared split-renormalized basis (Graham machinery,
  applied to the annual series)
- CAGR undefined because an endpoint is <= 0 is real data, not a gap: that
  sub-check scores 0 with a detail line, no flag, no hard-fail
  (Graham-walks-away precedent)
- P/E = market_cap / quarterly TTM periods[0] net income (freshest earnings to
  match the near-live market cap; Buffett/Graham parity); PEG = P/E /
  (annual 5y EPS CAGR x 100), reference-verbatim, canonical Lynch
- bullish is GARP-gated: score >= 0.70 AND PEG defined & < 2 (mirrors
  Buffett's MoS-gated bullish); failing the gate caps at neutral with a
  detail line. Bearish <= 0.45. Confidence is the Graham rule: 50-100 by
  distance from the nearest boundary, saturating at 0.30.
- growth-band label (unscored context, #63): from the 5y EPS CAGR, same edges
  as the scoring tiers; the persona narrates cyclical/turnaround/asset-play
  angles qualitatively
- hard-fail all rubric inputs (#63: the reference's zeros-and-continue and
  1e-9 equity fallback are bugs, not behavior to port): market_cap; >= 5
  complete annual periods (revenue, net_income, outstanding_shares); complete
  periods[0] (net_income, revenue > 0, operating_income, capital_expenditure,
  D&A, outstanding_shares, shareholders_equity, and at least one resolved
  debt component — both debt fields unresolved means real debt may be
  invisible, so Lynch refuses to diagnose rather than score D/E on nothing).
  Degenerate-but-real values (negative equity, negative CAGR endpoints) score
  0 instead: Lynch walks away, he doesn't crash.
- an unexplained share-count jump inside the growth window is degenerate
  input for the EPS series -> hard-fail (no plausible split factor means the
  per-share history cannot be trusted)
- validation layer runs over BOTH periods and annual_periods (Lynch reads
  both by contract); ERROR findings abort, WARN findings ride the output in
  `data_quality` with a dimensions_affected mapping

Determinism contract: same snapshot dict -> identical output dict. No I/O,
no clocks, no randomness in this module.
"""

from __future__ import annotations

from .. import validation
from ..errors import MissingDataError

RUBRIC_VERSION = 1
MAX_SCORE = 15

BULLISH_SCORE = 0.70
BEARISH_SCORE = 0.45
MAX_BOUNDARY_DIST = 0.30
PEG_BULLISH_GATE = 2.0

GROWTH_WINDOW = 5  # most recent complete annual periods (4 year-gaps)

# Which scored dimensions consume each snapshot field (ticket #55 A2 parity):
# data_quality warnings gain a dimensions_affected list.
_FIELD_DIMENSIONS = {
    "revenue": ["growth", "fundamentals"],
    "net_income": ["growth", "valuation", "fundamentals"],
    "outstanding_shares": ["growth"],
    "shareholders_equity": ["fundamentals"],
    "short_term_debt": ["fundamentals"],
    "long_term_debt": ["fundamentals"],
    "operating_income": ["fundamentals"],
    "capital_expenditure": ["fundamentals"],
    "depreciation_and_amortization": ["fundamentals"],
}
_CODE_DIMENSIONS = {
    "market_cap_manual_unverified": ["valuation"],
    "fundamentals_stale_vs_price": ["valuation", "fundamentals"],
    "restatement_402": ["growth", "valuation", "fundamentals"],
}


def _link_data_quality(dq: dict) -> dict:
    def dims(f: dict) -> list[str]:
        field = (f.get("context") or {}).get("field")
        if field is not None:
            return _FIELD_DIMENSIONS.get(field, [])
        return _CODE_DIMENSIONS.get(f.get("code"), [])

    return {
        **dq,
        "warnings": [{**f, "dimensions_affected": dims(f)} for f in dq["warnings"]],
    }


MANDATORY_ANNUAL_TTM = ["revenue", "net_income"]
MANDATORY_ANNUAL_BALANCE = ["outstanding_shares"]
MANDATORY_QUARTER_TTM = [
    "net_income",
    "revenue",
    "operating_income",
    "capital_expenditure",
    "depreciation_and_amortization",
]
MANDATORY_QUARTER_BALANCE = ["outstanding_shares", "shareholders_equity"]
DEBT_FIELDS = ["short_term_debt", "long_term_debt"]


# ---------------------------------------------------------------------------
# validation & derived series


def _annual_complete(period: dict) -> bool:
    ttm, bal = period["ttm"], period["balance"]
    return all(ttm.get(f) is not None for f in MANDATORY_ANNUAL_TTM) and all(
        bal.get(f) is not None for f in MANDATORY_ANNUAL_BALANCE
    )


def _validate(ticker, market_cap, annual: list, periods: list) -> list:
    """Hard-fail gate (#63: missing/degenerate input aborts, never scores
    around). Returns the growth window: the GROWTH_WINDOW most recent complete
    annual periods."""
    if market_cap is None:
        raise MissingDataError(f"{ticker}: market_cap missing from snapshot")

    complete = [p for p in annual if _annual_complete(p)]
    if len(complete) < GROWTH_WINDOW:
        gaps = []
        for p in annual:
            missing = [f for f in MANDATORY_ANNUAL_TTM if p["ttm"].get(f) is None] + [
                f for f in MANDATORY_ANNUAL_BALANCE if p["balance"].get(f) is None
            ]
            if missing:
                gaps.append(f"{p['period_end']}: {', '.join(missing)}")
        raise MissingDataError(
            f"{ticker}: only {len(complete)} complete annual periods "
            f"(need >= {GROWTH_WINDOW}). Gaps -- " + "; ".join(gaps)
        )

    if not periods:
        raise MissingDataError(f"{ticker}: no quarterly periods in snapshot")
    ttm, bal = periods[0]["ttm"], periods[0]["balance"]
    missing = [f for f in MANDATORY_QUARTER_TTM if ttm.get(f) is None] + [
        f for f in MANDATORY_QUARTER_BALANCE if bal.get(f) is None
    ]
    if all(bal.get(f) is None for f in DEBT_FIELDS):
        missing.append(
            "short_term_debt+long_term_debt (neither resolved: real debt may "
            "be invisible, refusing to score D/E)"
        )
    if ttm.get("revenue") == 0:
        missing.append("revenue (zero: operating margin degenerate)")
    if missing:
        raise MissingDataError(
            f"{ticker}: latest quarterly period {periods[0]['period_end']} "
            "is missing rubric inputs -- " + ", ".join(missing)
        )
    return complete[:GROWTH_WINDOW]


def eps_series(window: list, flags: list) -> list[float]:
    """Per-period annual EPS, most-recent-first, split-renormalized (shared
    #48 machinery). An unexplained jump inside the window hard-fails: the
    per-share growth history cannot be trusted (#63 degenerate-input rule)."""
    adjusted, events = validation.renormalize_share_series(
        [(p["period_end"], p["balance"]["outstanding_shares"]) for p in window]
    )
    for ev in events:
        if ev["type"] == "repair":
            flags.append(
                f"growth: {ev['period_end']} annual share count is stale by "
                f"x{ev['factor']:g} vs its neighbors (cover-page fact lagging a "
                "split); repaired onto the surrounding basis"
            )
        elif ev["type"] == "split":
            flags.append(
                f"growth: annual share counts at and before "
                f"{ev['older_period_end']} renormalized onto the current basis "
                f"(split factor x{ev['factor']:g} at this boundary; observed "
                f"jump x{ev['observed_ratio']:.3g})"
            )
        else:
            raise MissingDataError(
                f"annual share count jumps x{ev['observed_ratio']:.3g} into "
                f"{ev['newer_period_end']} with no plausible split factor; the "
                "EPS growth history is untrustworthy"
            )
    return [p["ttm"]["net_income"] / adj for p, adj in zip(window, adjusted)]


def _cagr(latest: float, oldest: float, gaps: int) -> float | None:
    """Annualized growth; None when an endpoint is <= 0 (real data — Lynch
    walks away from the growth story, no gap, no flag)."""
    if latest <= 0 or oldest <= 0:
        return None
    return (latest / oldest) ** (1 / gaps) - 1


def _growth_points(cagr: float) -> int:
    if cagr >= 0.20:
        return 3
    if cagr >= 0.10:
        return 2
    if cagr >= 0.03:
        return 1
    return 0


# ---------------------------------------------------------------------------
# dimensions (window and EPS lists are most-recent-first)


def analyze_growth(window: list, flags: list) -> dict:
    score, details = 0, []
    gaps = len(window) - 1

    revenues = [p["ttm"]["revenue"] for p in window]
    rev_cagr = _cagr(revenues[0], revenues[-1], gaps)
    if rev_cagr is None:
        details.append(
            f"Revenue CAGR not meaningful (endpoint <= 0: oldest "
            f"{revenues[-1]:,.0f}, latest {revenues[0]:,.0f}) (+0)"
        )
    else:
        pts = _growth_points(rev_cagr)
        score += pts
        mark = "✓" if pts else "✗"
        details.append(f"Revenue 5y CAGR {rev_cagr:.1%} {mark} (+{pts})")

    eps_vals = eps_series(window, flags)
    eps_cagr = _cagr(eps_vals[0], eps_vals[-1], gaps)
    if eps_cagr is None:
        details.append(
            f"EPS CAGR not meaningful (endpoint <= 0: oldest "
            f"{eps_vals[-1]:.2f}, latest {eps_vals[0]:.2f}) (+0)"
        )
    else:
        pts = _growth_points(eps_cagr)
        score += pts
        mark = "✓" if pts else "✗"
        details.append(f"EPS 5y CAGR {eps_cagr:.1%} {mark} (+{pts})")

    return {
        "score": score,
        "max": 6,
        "details": details,
        "revenue_cagr_5y": rev_cagr,
        "eps_cagr_5y": eps_cagr,
    }


def analyze_valuation(latest: dict, market_cap: float, eps_cagr: float | None) -> dict:
    score, details = 0, []
    ttm_net_income = latest["ttm"]["net_income"]

    pe = None
    if ttm_net_income > 0:
        pe = market_cap / ttm_net_income
        if pe < 15:
            score += 2
            details.append(f"P/E {pe:.2f} < 15 ✓ (+2)")
        elif pe < 25:
            score += 1
            details.append(f"P/E {pe:.2f} < 25 ✓ (+1)")
        else:
            details.append(f"P/E {pe:.2f} >= 25 ✗ (+0)")
    else:
        details.append(
            f"P/E not meaningful (TTM net income {ttm_net_income:,.0f} <= 0) (+0)"
        )

    peg = None
    if pe is None:
        details.append("PEG unavailable: no positive TTM earnings for a P/E (+0)")
    elif eps_cagr is None or eps_cagr <= 0:
        details.append("PEG unavailable: 5y EPS CAGR not positive (+0)")
    else:
        peg = pe / (eps_cagr * 100)
        if peg < 1:
            score += 3
            details.append(f"PEG {peg:.2f} < 1 (growth outruns the multiple) ✓ (+3)")
        elif peg < 2:
            score += 2
            details.append(f"PEG {peg:.2f} < 2 ✓ (+2)")
        elif peg < 3:
            score += 1
            details.append(f"PEG {peg:.2f} < 3 ✓ (+1)")
        else:
            details.append(f"PEG {peg:.2f} >= 3 ✗ (+0)")

    return {"score": score, "max": 5, "details": details, "pe_ttm": pe, "peg": peg}


def analyze_fundamentals(latest: dict) -> dict:
    score, details = 0, []
    ttm, bal = latest["ttm"], latest["balance"]

    # Debt sum: at least one component resolved (validated); the missing one
    # follows the shared zero-if-one-resolved policy (validation check 5b).
    debt = sum(bal[f] for f in DEBT_FIELDS if bal.get(f) is not None)
    equity = bal["shareholders_equity"]
    de = None
    if equity <= 0:
        details.append(
            f"D/E not meaningful (shareholders' equity {equity:,.0f} <= 0) (+0)"
        )
    else:
        de = debt / equity
        if de < 0.5:
            score += 2
            details.append(f"Debt/equity {de:.2f} < 0.50 ✓ (+2)")
        elif de < 1.0:
            score += 1
            details.append(f"Debt/equity {de:.2f} < 1.00 ✓ (+1)")
        else:
            details.append(f"Debt/equity {de:.2f} >= 1.00 ✗ (+0)")

    margin = ttm["operating_income"] / ttm["revenue"]
    if margin >= 0.10:
        score += 1
        details.append(f"TTM operating margin {margin:.1%} >= 10% ✓ (+1)")
    else:
        details.append(f"TTM operating margin {margin:.1%} < 10% ✗ (+0)")

    # Snapshots carry no FCF field; derive it (capex is stored negative).
    fcf = ttm["net_income"] + ttm["depreciation_and_amortization"] - abs(
        ttm["capital_expenditure"]
    )
    if fcf > 0:
        score += 1
        details.append(f"Derived TTM FCF ${fcf:,.0f} > 0 ✓ (+1)")
    else:
        details.append(f"Derived TTM FCF ${fcf:,.0f} <= 0 ✗ (+0)")

    return {
        "score": score,
        "max": 4,
        "details": details,
        "debt_to_equity": de,
        "operating_margin_ttm": margin,
        "fcf_ttm": fcf,
    }


# ---------------------------------------------------------------------------
# signal, confidence, band, diagnosis


def compute_signal(score_pct: float, peg: float | None) -> str:
    if score_pct >= BULLISH_SCORE and peg is not None and peg < PEG_BULLISH_GATE:
        return "bullish"
    if score_pct <= BEARISH_SCORE:
        return "bearish"
    return "neutral"


def compute_confidence(score_pct: float) -> int:
    dist = min(abs(score_pct - BULLISH_SCORE), abs(score_pct - BEARISH_SCORE))
    return round(50 + 50 * min(1.0, dist / MAX_BOUNDARY_DIST))


def growth_band(eps_cagr: float | None) -> str:
    """Unscored context (#63): band edges match the scoring tiers; the persona
    narrates cyclical/turnaround/asset-play angles qualitatively."""
    if eps_cagr is None:
        return "not_meaningful"
    if eps_cagr >= 0.20:
        return "fast_grower"
    if eps_cagr >= 0.10:
        return "stalwart"
    return "slow_grower"


def diagnose(snapshot: dict) -> dict:
    # Validation layer first, over both arrays (Lynch reads annual history and
    # the latest quarter). ERROR findings hard-fail; WARN rides data_quality.
    findings, checks_run = validation.run_checks(snapshot)
    errors = [f for f in findings if f["severity"] == validation.ERROR]
    if errors:
        raise MissingDataError(
            f"{snapshot.get('ticker')}: validation failed -- "
            + "; ".join(f["message"] for f in errors)
        )

    ticker = snapshot.get("ticker")
    annual = snapshot.get("annual_periods")
    if annual is None:
        raise MissingDataError(
            f"{ticker}: snapshot has no annual_periods (schema v1); "
            "refetch before diagnosing"
        )
    periods = snapshot.get("periods", [])
    market_cap = snapshot.get("market_cap")
    flags: list[str] = []

    # 8-K Item 4.02 restatement guard (parity with both siblings): annual
    # fiscal years declared non-reliable are excluded exactly (Buffett rule);
    # quarterly TTM windows ending inside or before the latest restated year
    # rest on non-reliable statements and are excluded (Graham rule).
    excluded_years = validation.restatement_excluded_years(findings)
    if excluded_years:
        cutoff = max(excluded_years)
        annual = [p for p in annual if p["period_end"] not in excluded_years]
        periods = [p for p in periods if p["period_end"] > cutoff]
        flags.append(
            "restatement: fiscal years "
            + ", ".join(excluded_years)
            + " and quarterly windows ending on or before "
            f"{cutoff} excluded (8-K Item 4.02 non-reliance)"
        )

    try:
        window = _validate(ticker, market_cap, annual, periods)
        growth = analyze_growth(window, flags)
    except MissingDataError as e:
        raise MissingDataError(
            str(e) if str(e).startswith(f"{ticker}:") else f"{ticker}: {e}"
        ) from None
    valuation_dim = analyze_valuation(periods[0], market_cap, growth["eps_cagr_5y"])
    fundamentals = analyze_fundamentals(periods[0])

    dimensions = {
        "growth": {k: growth[k] for k in ("score", "max", "details")},
        "valuation": {k: valuation_dim[k] for k in ("score", "max", "details")},
        "fundamentals": {k: fundamentals[k] for k in ("score", "max", "details")},
    }
    total = sum(d["score"] for d in dimensions.values())
    score_pct = total / MAX_SCORE
    peg = valuation_dim["peg"]

    signal = compute_signal(score_pct, peg)
    if score_pct >= BULLISH_SCORE and signal != "bullish":
        dimensions["valuation"]["details"].append(
            f"GARP gate: score {score_pct:.0%} clears the bullish bar but PEG "
            + (f"{peg:.2f} >= {PEG_BULLISH_GATE:g}" if peg is not None else "is undefined")
            + " — growth is not reasonably priced; capped at neutral"
        )

    def _r(v):
        return None if v is None else round(v, 4)

    result = {
        "ticker": snapshot["ticker"],
        "rubric_version": RUBRIC_VERSION,
        "signal": signal,
        "confidence": compute_confidence(score_pct),
        "score": {"total": total, "max": MAX_SCORE, "max_possible": MAX_SCORE, "pct": round(score_pct, 4)},
        "growth_band": {
            "label": growth_band(growth["eps_cagr_5y"]),
            "eps_cagr_5y": _r(growth["eps_cagr_5y"]),
        },
        "dimensions": dimensions,
        "valuation": {
            "market_cap": market_cap,
            "pe_ttm": _r(valuation_dim["pe_ttm"]),
            "peg": _r(peg),
            "revenue_cagr_5y": _r(growth["revenue_cagr_5y"]),
            "eps_cagr_5y": _r(growth["eps_cagr_5y"]),
            "debt_to_equity": _r(fundamentals["debt_to_equity"]),
            "operating_margin_ttm": _r(fundamentals["operating_margin_ttm"]),
            "fcf_ttm": fundamentals["fcf_ttm"],
        },
        "flags": flags,
        "data_quality": _link_data_quality(
            validation.data_quality(findings, checks_run)
        ),
        "provenance": {
            "snapshot_fetched_at": snapshot["fetched_at"],
            "market_cap_source": snapshot["market_cap_source"],
            "source": snapshot["source"],
            "annual_periods": [p["period_end"] for p in window],
            "quarterly_period": periods[0]["period_end"],
        },
    }
    # Unscored context (ticket #52): whale-agnostic pass-through so the
    # persona can cite Form 4 activity qualitatively. Never scored (#63).
    if "insider_activity" in snapshot:
        result["insider_activity"] = snapshot["insider_activity"]
    return result
