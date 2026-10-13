"""Offline phase: pure function of one snapshot -> full-diagnostic dict.

Joel Greenblatt magic-formula rubric v1 (max 10 = return on capital 5 +
earnings yield 5), scoring ONE company on ABSOLUTE tests — not the book's
ranked universe. The anchor is Greenblatt's own single-company rule: compare
the earnings yield to a risk-free bond floor (The Little Book That Beats the
Market, pp.103–104, 142 fn — book quotes unverified against a copy; see the
research doc). Decisions locked on the rubric ticket:

- EBIT = quarterly TTM `operating_income`, no normalization in the score; an
  unscored `earnings_context` block compares TTM to the 5-year average of
  annual EBIT and flags `peak_earnings` when TTM > 1.5x (p.104 caveat,
  narrated, never scored)
- return on capital = EBIT / (net working capital + net fixed assets):
  all cash is excess (removed from capital), NWC excludes short-term debt,
  NFA is the additive `net_fixed_assets` snapshot field resolved
  freshest-across-tags at fetch time; goodwill excluded by construction
- earnings yield = after-tax EBIT / enterprise value, tax 21% flat (engine
  TAX_RATE precedent), EV = market cap + short-term debt + long-term debt
  - cash (preferred omitted: no snapshot field)
- hurdle = fixed 6% (the book's rule is max(6%, 10-year Treasury); no live
  rate source by charter); tiers at 1.0x / 0.75x / 0.5x of the hurdle
- 25% ROC is a declared repurpose of the p.136 ROA screener bar, the only
  number Greenblatt publishes; 15% is the common open-source bar and is
  owner judgment, unsourced
- capital <= 0 with EBIT > 0 is real data (asset-light), not a gap: 5 points
  flagged `asset_light`; negative EBIT scores 0 on both dimensions with a
  detail line; EV <= 0 scores earnings yield 0 (Lynch degenerate-but-real
  precedent). None of these walk away.
- signal: Graham thresholds (bullish >= 70%, bearish <= 30%), gated one way:
  bullish also needs after-tax EY >= the 6% hurdle; a qualifying score that
  fails it caps at neutral with a pinned detail line
- confidence: Graham distance rule (50–100, saturating at 0.30) minus 5 per
  WARN-affected dimension, floor 50 (Buffett v3 B2); a capped signal
  measures the same way (Lynch precedent)
- walk away (MissingDataError, reason string) on SIC 6000–6499, 6700–6799
  (banks, S&L, insurance, brokers, funds) and 4900–4999 (utilities) — EBIT
  and working capital mean nothing there. SIC 6199 (non-depository credit,
  where the bitcoin miners file) is NOT walked: real PP&E, real operating
  losses. No SIC on the snapshot -> WARN flag, score anyway.
- hard-fail (MissingDataError) on a missing market_cap, operating_income,
  current_assets, current_liabilities, cash_and_equivalents, net_fixed_assets
  (no charter tag resolved, or a pre-field snapshot -> refetch), and on BOTH
  debt fields None (captive-finance debt invisible: refuse rather than look
  cheap). Short-term debt alone None -> 0 with a WARN flag.
- validation layer runs over both period arrays; ERROR findings abort, WARN
  findings ride `data_quality` with a dimensions_affected mapping

Determinism contract: same snapshot dict -> identical output dict. No I/O,
no clocks, no randomness in this module.
"""

from __future__ import annotations

from .. import validation
from ..errors import MissingDataError

# Bumping this needs a signed judgment review, like the other rubrics: every
# diagnosis carries it so a narration can be traced to the exact rule set.
RUBRIC_VERSION = 1

MAX_SCORE = 10

BULLISH_SCORE = 0.70
BEARISH_SCORE = 0.30
MAX_BOUNDARY_DIST = 0.30
DATA_QUALITY_PENALTY = 5  # per WARN-affected dimension (Buffett v3 B2)

ROC_HIGH = 0.25  # declared repurpose of the p.136 ROA screener bar
ROC_MID = 0.15  # owner judgment, unsourced

TAX_RATE = 0.21  # engine precedent (Buffett ROIC); the book's example uses 40%
# Fixed floor by charter. Greenblatt's rule is max(6%, 10-year Treasury)
# (Little Book pp.103–104); there is no live rate source in this engine.
HURDLE = 0.06
EY_TIERS = ((1.0, 5), (0.75, 3), (0.5, 1))  # (fraction of hurdle, points)

PEAK_EARNINGS_RATIO = 1.5  # TTM EBIT vs 5-year annual average (p.104, unscored)
EBIT_HISTORY_YEARS = 5

# SIC ranges where EBIT and working capital say nothing: walk away, by charter.
# 6199 (non-depository credit) is deliberately inside none of these — the
# bitcoin miners file there with real PP&E and real operating losses.
WALK_AWAY_SIC_RANGES = (
    (6000, 6499, "banks, savings institutions, insurance, brokers"),
    (6700, 6799, "holding and investment offices, funds"),
    (4900, 4999, "utilities"),
)
WALK_AWAY_SIC_EXEMPT = {6199}

MANDATORY_TTM = ["operating_income"]
MANDATORY_BALANCE = ["current_assets", "current_liabilities", "cash_and_equivalents"]
DEBT_FIELDS = ["short_term_debt", "long_term_debt"]

# Which scored dimensions consume each snapshot field (truth-in-scoring
# parity): data_quality warnings gain a dimensions_affected list, and the
# confidence penalty counts the distinct dimensions touched.
_FIELD_DIMENSIONS = {
    "operating_income": ["return_on_capital", "earnings_yield"],
    "cash_and_equivalents": ["return_on_capital", "earnings_yield"],
    "current_assets": ["return_on_capital"],
    "current_liabilities": ["return_on_capital"],
    "net_fixed_assets": ["return_on_capital"],
    "short_term_debt": ["return_on_capital", "earnings_yield"],
    "long_term_debt": ["earnings_yield"],
}
_CODE_DIMENSIONS = {
    "market_cap_manual_unverified": ["earnings_yield"],
    "fundamentals_stale_vs_price": ["return_on_capital", "earnings_yield"],
    "restatement_402": ["return_on_capital", "earnings_yield"],
}


def _link_data_quality(dq: dict) -> dict:
    def dims(f: dict) -> list[str]:
        field = (f.get("context") or {}).get("field")
        if field is not None:
            return _FIELD_DIMENSIONS.get(field, [])
        return _CODE_DIMENSIONS.get(f.get("code") or "", [])

    return {
        **dq,
        "warnings": [{**f, "dimensions_affected": dims(f)} for f in dq["warnings"]],
    }


def _ratio(num, den):
    if num is None or den is None or den == 0:
        return None
    return num / den


# ---------------------------------------------------------------------------
# dimensions


def analyze_return_on_capital(ebit: float, capital: float) -> dict:
    score, details = 0, []
    asset_light = False
    roc = None
    if capital <= 0:
        # Degenerate-but-real: no ratio, no flag. Positive EBIT on zero or
        # negative tangible capital is the asset-light extreme of what the
        # formula rewards; non-positive EBIT on it is just a loss-maker.
        if ebit > 0:
            score = 5
            asset_light = True
            details.append(
                f"Capital {capital:,.0f} <= 0 with EBIT {ebit:,.0f} > 0: asset-light "
                "(return on capital unbounded) ✓ (+5)"
            )
        else:
            details.append(
                f"Capital {capital:,.0f} <= 0 and EBIT {ebit:,.0f} <= 0: no return "
                "on capital ✗ (+0)"
            )
        return {
            "score": score,
            "max": 5,
            "details": details,
            "return_on_capital": roc,
            "asset_light": asset_light,
        }

    roc = ebit / capital
    if roc >= ROC_HIGH:
        score = 5
        details.append(f"Return on capital {roc:.1%} >= {ROC_HIGH:.0%} ✓ (+5)")
    elif roc >= ROC_MID:
        score = 3
        details.append(f"Return on capital {roc:.1%} >= {ROC_MID:.0%} ✓ (+3)")
    elif roc > 0:
        score = 1
        details.append(f"Return on capital {roc:.1%} > 0% ✓ (+1)")
    else:
        details.append(f"Return on capital {roc:.1%} <= 0% ✗ (+0)")
    return {
        "score": score,
        "max": 5,
        "details": details,
        "return_on_capital": roc,
        "asset_light": asset_light,
    }


def analyze_earnings_yield(ebit: float, enterprise_value: float) -> dict:
    score, details = 0, []
    after_tax_ebit = ebit * (1 - TAX_RATE)
    ey = None
    if enterprise_value <= 0:
        # Degenerate-but-real (net cash exceeds the market cap): no yield to
        # compare with the hurdle. Detail line only, no flag.
        details.append(
            f"Earnings yield not meaningful (enterprise value {enterprise_value:,.0f} "
            "<= 0) (+0)"
        )
        return {"score": 0, "max": 5, "details": details, "earnings_yield_after_tax": ey}

    ey = after_tax_ebit / enterprise_value
    if ebit <= 0:
        details.append(
            f"EBIT {ebit:,.0f} <= 0: after-tax earnings yield {ey:.1%} has nothing "
            f"to clear the {HURDLE:.0%} hurdle with ✗ (+0)"
        )
        return {"score": 0, "max": 5, "details": details, "earnings_yield_after_tax": ey}

    for fraction, points in EY_TIERS:
        bar = HURDLE * fraction
        if ey >= bar:
            score = points
            details.append(
                f"After-tax earnings yield {ey:.1%} >= {bar:.1%} "
                f"({fraction:g}x the {HURDLE:.0%} bond hurdle) ✓ (+{points})"
            )
            break
    else:
        details.append(
            f"After-tax earnings yield {ey:.1%} < {HURDLE * EY_TIERS[-1][0]:.1%} "
            f"({EY_TIERS[-1][0]:g}x the {HURDLE:.0%} bond hurdle) ✗ (+0)"
        )
    return {"score": score, "max": 5, "details": details, "earnings_yield_after_tax": ey}


# ---------------------------------------------------------------------------
# signal, confidence


def compute_signal(score_pct: float, ey_after_tax: float | None) -> str:
    """Graham thresholds, gated one way: bullish also needs the after-tax
    earnings yield at or above the bond hurdle (Greenblatt's single-company
    rule). The gate caps, never lifts, never pushes to bearish."""
    if score_pct >= BULLISH_SCORE:
        if ey_after_tax is not None and ey_after_tax >= HURDLE:
            return "bullish"
        return "neutral"
    if score_pct <= BEARISH_SCORE:
        return "bearish"
    return "neutral"


def compute_confidence(score_pct: float, affected_dimensions: list[str]) -> int:
    """50–100 by distance from the nearest signal boundary (saturating at
    0.30), minus 5 per WARN-affected dimension, floor 50 (Buffett v3 B2).
    A capped signal measures the same way (Lynch precedent)."""
    dist = min(abs(score_pct - BULLISH_SCORE), abs(score_pct - BEARISH_SCORE))
    conf = round(50 + 50 * min(1.0, dist / MAX_BOUNDARY_DIST))
    return max(50, conf - DATA_QUALITY_PENALTY * len(affected_dimensions))


# ---------------------------------------------------------------------------
# universe and input gates


def walk_away_reason(sic) -> str | None:
    """Reason string when the SIC code puts the filer outside the formula's
    universe, else None. A missing SIC is the caller's WARN, not a walk."""
    if sic is None:
        return None
    code = int(sic)
    if code in WALK_AWAY_SIC_EXEMPT:
        return None
    for lo, hi, label in WALK_AWAY_SIC_RANGES:
        if lo <= code <= hi:
            return (
                f"SIC {code} is in {lo}–{hi} ({label}): EBIT and working capital "
                "do not describe the business — Greenblatt walks away"
            )
    return None


def _validate(ticker, snapshot: dict, latest: dict) -> None:
    """Hard-fail gate: missing/unresolved input aborts, never scores around."""
    if snapshot.get("market_cap") is None:
        raise MissingDataError(f"{ticker}: market_cap missing from snapshot")
    ttm, bal = latest["ttm"], latest["balance"]
    missing = [f for f in MANDATORY_TTM if ttm.get(f) is None] + [
        f for f in MANDATORY_BALANCE if bal.get(f) is None
    ]
    if "net_fixed_assets" not in bal:
        raise MissingDataError(
            f"{ticker}: snapshot predates the net_fixed_assets field; "
            "refetch before diagnosing"
        )
    if bal["net_fixed_assets"] is None:
        missing.append(
            "net_fixed_assets (no net PP&E tag resolved, filed or derived)"
        )
    if all(bal.get(f) is None for f in DEBT_FIELDS):
        missing.append(
            "short_term_debt+long_term_debt (neither resolved: real debt may "
            "be invisible, refusing to score enterprise value)"
        )
    if missing:
        raise MissingDataError(
            f"{ticker}: latest quarterly period {latest['period_end']} "
            "is missing rubric inputs -- " + ", ".join(missing)
        )


def earnings_context(ebit_ttm: float, annual: list) -> dict:
    """Unscored: TTM EBIT against the average of the last EBIT_HISTORY_YEARS
    filed fiscal years (Greenblatt's normal-earnings caveat, narrated only)."""
    history = [
        p["ttm"]["operating_income"]
        for p in annual
        if p.get("ttm", {}).get("operating_income") is not None
    ][:EBIT_HISTORY_YEARS]
    if not history:
        return {
            "ebit_ttm": ebit_ttm,
            "ebit_5y_average": None,
            "ttm_to_average": None,
            "peak_earnings": False,
            "annual_periods": [],
        }
    average = sum(history) / len(history)
    ratio = None if average <= 0 else ebit_ttm / average
    return {
        "ebit_ttm": ebit_ttm,
        "ebit_5y_average": average,
        "ttm_to_average": None if ratio is None else round(ratio, 4),
        "peak_earnings": ratio is not None and ratio > PEAK_EARNINGS_RATIO,
        "annual_periods": [
            p["period_end"]
            for p in annual
            if p.get("ttm", {}).get("operating_income") is not None
        ][:EBIT_HISTORY_YEARS],
    }


# ---------------------------------------------------------------------------
# diagnosis


def diagnose(snapshot: dict) -> dict:
    ticker = snapshot.get("ticker")
    flags: list[str] = []

    # Universe first: a bank's missing capex would otherwise surface as the
    # validation layer's sector ERROR, hiding the real reason.
    sic = snapshot.get("sic")
    reason = walk_away_reason(sic)
    if reason is not None:
        raise MissingDataError(f"{ticker}: {reason}")
    if sic is None:
        flags.append(
            "sic_unavailable: no SIC code on the snapshot; universe filter "
            "(financials, utilities) could not be applied, scored anyway"
        )

    # Validation layer over both arrays (the latest quarter is scored; the
    # annual EBIT history feeds the unscored context). ERROR aborts; WARN
    # rides data_quality.
    findings, checks_run = validation.run_checks(snapshot)
    errors = [f for f in findings if f["severity"] == validation.ERROR]
    if errors:
        raise MissingDataError(
            f"{ticker}: validation failed -- " + "; ".join(f["message"] for f in errors)
        )

    periods = snapshot.get("periods") or []
    annual = snapshot.get("annual_periods") or []
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
    if not periods:
        raise MissingDataError(f"{ticker}: no quarterly periods to score")
    latest = periods[0]
    _validate(ticker, snapshot, latest)
    ttm, bal = latest["ttm"], latest["balance"]
    market_cap = snapshot["market_cap"]

    ebit = ttm["operating_income"]
    cash = bal["cash_and_equivalents"]
    short_debt = bal.get("short_term_debt")
    long_debt = bal.get("long_term_debt")
    if short_debt is None:
        short_debt = 0.0
        flags.append(
            "short_term_debt: missing, treated as 0 in net working capital and "
            "enterprise value (long_term_debt resolved)"
        )
    if long_debt is None:
        long_debt = 0.0
        flags.append(
            "long_term_debt: missing, treated as 0 in enterprise value "
            "(short_term_debt resolved)"
        )

    # Capital: cash is all excess (out of current assets), short-term debt is
    # financing, not operations (out of current liabilities); goodwill never
    # enters because NFA is tangible net PP&E.
    nwc = (bal["current_assets"] - cash) - (bal["current_liabilities"] - short_debt)
    nfa = bal["net_fixed_assets"]
    capital = nwc + nfa
    ev = market_cap + short_debt + long_debt - cash

    roc = analyze_return_on_capital(ebit, capital)
    ey = analyze_earnings_yield(ebit, ev)
    dimensions = {
        "return_on_capital": {k: roc[k] for k in ("score", "max", "details")},
        "earnings_yield": {k: ey[k] for k in ("score", "max", "details")},
    }
    if roc["asset_light"]:
        flags.append(
            "asset_light: capital (NWC + NFA) <= 0 with positive EBIT; return on "
            "capital scored full marks without a ratio"
        )

    total = sum(d["score"] for d in dimensions.values())
    score_pct = total / MAX_SCORE
    ey_after_tax = ey["earnings_yield_after_tax"]
    signal = compute_signal(score_pct, ey_after_tax)
    if score_pct >= BULLISH_SCORE and signal != "bullish":
        # Pinned line: the persona copies it verbatim.
        dimensions["earnings_yield"]["details"].append(
            f"Capped at neutral: after-tax earnings yield {ey_after_tax:.1%} is "
            f"below the {HURDLE:.0%} bond hurdle."
        )

    data_quality = _link_data_quality(validation.data_quality(findings, checks_run))
    affected: set[str] = set()
    for w in data_quality["warnings"]:
        affected |= set(w["dimensions_affected"])
    for fl in flags:
        prefix, _, _rest = fl.partition(": ")
        affected |= set(_FIELD_DIMENSIONS.get(prefix, []))

    def _r(v):
        return None if v is None else round(v, 4)

    result = {
        "ticker": snapshot["ticker"],
        "rubric_version": RUBRIC_VERSION,
        "signal": signal,
        "confidence": compute_confidence(score_pct, sorted(affected)),
        "score": {
            "total": total,
            "max": MAX_SCORE,
            "max_possible": MAX_SCORE,
            "pct": round(score_pct, 4),
        },
        "dimensions": dimensions,
        "valuation": {
            "market_cap": market_cap,
            "ebit_ttm": ebit,
            "cash_and_equivalents": cash,
            "short_term_debt": short_debt,
            "long_term_debt": long_debt,
            "net_working_capital": nwc,
            "net_fixed_assets": nfa,
            "net_fixed_assets_tag": (latest.get("tags_used") or {}).get("net_fixed_assets"),
            "capital": capital,
            "enterprise_value": ev,
            "return_on_capital": _r(roc["return_on_capital"]),
            "asset_light": roc["asset_light"],
            "earnings_yield_after_tax": _r(ey_after_tax),
            "tax_rate": TAX_RATE,
            "hurdle": HURDLE,
        },
        "earnings_context": earnings_context(ebit, annual),
        "flags": flags,
        "data_quality": {
            **data_quality,
            "dimensions_affected": sorted(affected),
            "confidence_penalty": DATA_QUALITY_PENALTY * len(affected),
        },
        "provenance": {
            "snapshot_fetched_at": snapshot["fetched_at"],
            "market_cap_source": snapshot["market_cap_source"],
            "source": snapshot["source"],
            "sic": sic,
            "quarterly_period": latest["period_end"],
        },
    }
    # Unscored context: whale-agnostic pass-through so the persona can cite
    # Form 4 activity qualitatively. Never scored.
    if "insider_activity" in snapshot:
        result["insider_activity"] = snapshot["insider_activity"]
    return result
