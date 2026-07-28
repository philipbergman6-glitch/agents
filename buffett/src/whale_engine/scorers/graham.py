"""Offline phase: pure function of one snapshot -> full-diagnostic dict.

Faithful port of the three dimensions in reference/ben_graham.py (max 16 =
earnings stability 4 + financial strength 5 + Graham valuation 7 — the true
sum; the reference hardcodes 15), with the decisions locked on the rubric
ticket:

- EPS is derived per period as net_income / outstanding_shares (snapshots
  carry no per-share fields); periods are most-recent-first and the endpoint
  growth check is explicit latest > oldest (the reference never pins ordering)
- signal: bullish if score >= 70%, bearish if <= 30%, else neutral; no
  separate MoS gate on the bullish side — bullish needs >= 11.2/16 and the
  non-valuation dimensions max at 9, so a real valuation discount is
  arithmetically required
- deep-overprice override (judgment-review tuning, ticket #31): MoS <= -0.50
  vs the Graham Number forces bearish regardless of quality points — bearish
  means "don't buy at today's price", and price alone must be able to say it;
  quality-driven neutral at 9x Graham Number is not a Graham read
- confidence 50-100: distance of score% from the nearest boundary, saturating
  at 0.30 (the max attainable distance); when the override fires, confidence
  is the greater of that and the overprice depth (-0.50 -> 50, -1.00 -> 100)
- missing data: mandatory inputs hard-fail unless present in >= 5 periods;
  dividends are optional (absent -> 0 + flag); per-ratio gaps score 0 with a
  flag; ratio checks gate on None, never truthiness — an exact zero is data,
  not a gap (the reference truthiness-gates, an intentional fix)
- Graham Number unavailable because EPS/BVPS <= 0 is a legitimate 0 (Graham
  walks away), detail line only — flags are reserved for missing inputs
- fixed denominator 16: the hard-fail gate keeps all three dimensions
  scorable, so there is no exclusion/renormalization machinery
- the shared split-aware share renormalization (ticket #48, replacing the
  3x-median outlier guard) protects the per-period EPS series: split-shaped
  jumps rebase older counts onto the current basis, unexplained jumps exclude
  the older segment with a flag
- validation layer (ticket #48): shared snapshot checks run first over the
  quarterly array only (Graham ignores annual_periods by contract); ERROR
  findings hard-fail, WARN findings ride the output in `data_quality`

Determinism contract: same snapshot dict -> identical output dict. No I/O,
no clocks, no randomness in this module.
"""

from __future__ import annotations

import math

from .. import validation
from ..errors import MissingDataError

MAX_SCORE = 16

BULLISH_SCORE = 0.70
BEARISH_SCORE = 0.30
MAX_BOUNDARY_DIST = 0.30
DEEP_OVERPRICE_MOS = -0.50

# Which scored dimensions consume each snapshot field (ticket #55 A2 parity
# with the Buffett scorer): data_quality warnings gain a dimensions_affected
# list. Graham reads the quarterly array only.
_FIELD_DIMENSIONS = {
    "net_income": ["earnings_stability", "valuation"],
    "outstanding_shares": ["earnings_stability", "valuation"],
    "shareholders_equity": ["valuation"],
    "current_assets": ["financial_strength", "valuation"],
    "current_liabilities": ["financial_strength"],
    "total_assets": ["financial_strength"],
    "total_liabilities": ["financial_strength", "valuation"],
    "dividends_and_other_cash_distributions": ["financial_strength"],
}
_CODE_DIMENSIONS = {
    "market_cap_manual_unverified": ["valuation"],
    "fundamentals_stale_vs_price": ["earnings_stability", "financial_strength", "valuation"],
    "restatement_402": ["earnings_stability", "financial_strength", "valuation"],
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


MANDATORY_TTM = ["net_income"]
MANDATORY_BALANCE = [
    "outstanding_shares",
    "shareholders_equity",
    "total_assets",
    "total_liabilities",
    "current_assets",
    "current_liabilities",
]
MIN_COMPLETE_PERIODS = 5


# ---------------------------------------------------------------------------
# validation & derived per-share values


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


def _ratio(num, den):
    if num is None or den is None or den == 0:
        return None
    return num / den


def eps_series(periods: list, flags: list) -> list[float]:
    """Per-period EPS, most-recent-first, on a split-renormalized share basis.

    Cover-page share facts lag one quarter, so a split between filings leaves
    one period on the pre-split count — off by the split ratio, not by drift.
    The shared renormalization (ticket #48) rebases split-shaped jumps onto
    the current share basis (repairing the lagged period instead of dropping
    it); jumps no split factor explains exclude the older segment with a flag.
    """
    usable = [
        p
        for p in periods
        if p["ttm"].get("net_income") is not None and p["balance"].get("outstanding_shares")
    ]
    adjusted, events = validation.renormalize_share_series(
        [(p["period_end"], p["balance"]["outstanding_shares"]) for p in usable]
    )
    for ev in events:
        if ev["type"] == "repair":
            flags.append(
                f"earnings_stability: {ev['period_end']} share count is stale by "
                f"x{ev['factor']:g} vs its neighbors (cover-page fact lagging a "
                "split); repaired onto the surrounding basis"
            )
        elif ev["type"] == "split":
            flags.append(
                f"earnings_stability: share counts at and before "
                f"{ev['older_period_end']} renormalized onto the current basis "
                f"(split factor x{ev['factor']:g} at this boundary; observed "
                f"jump x{ev['observed_ratio']:.3g})"
            )
        else:
            flags.append(
                f"earnings_stability: share count jumps x{ev['observed_ratio']:.3g} "
                f"into {ev['newer_period_end']} with no plausible split factor; "
                f"periods {', '.join(ev['excluded_period_ends'])} excluded"
            )
    return [
        p["ttm"]["net_income"] / adj
        for p, adj in zip(usable, adjusted)
        if adj is not None
    ]


# ---------------------------------------------------------------------------
# dimensions (periods and EPS lists are most-recent-first)


def analyze_earnings_stability(periods: list, flags: list) -> dict:
    score, details = 0, []
    eps_vals = eps_series(periods, flags)
    if len(eps_vals) < 2:
        flags.append("earnings_stability: fewer than 2 EPS periods, scored 0")
        return {"score": 0, "max": 4, "details": ["Not enough multi-period EPS data (+0)"]}

    positive = sum(1 for e in eps_vals if e > 0)
    total = len(eps_vals)
    if positive == total:
        score += 3
        details.append(f"EPS positive in all {total} periods ✓ (+3)")
    elif positive >= total * 0.8:
        score += 2
        details.append(f"EPS positive in {positive}/{total} periods (>= 80%) ✓ (+2)")
    else:
        details.append(f"EPS negative in multiple periods ({positive}/{total} positive) ✗ (+0)")

    latest, oldest = eps_vals[0], eps_vals[-1]
    if latest > oldest:
        score += 1
        details.append(f"EPS grew oldest-to-latest ({oldest:.2f} -> {latest:.2f}) ✓ (+1)")
    else:
        details.append(f"EPS did not grow oldest-to-latest ({oldest:.2f} -> {latest:.2f}) ✗ (+0)")

    return {"score": score, "max": 4, "details": details}


def analyze_financial_strength(periods: list, flags: list) -> dict:
    score, details = 0, []
    bal = periods[0]["balance"]

    cr = _ratio(bal.get("current_assets"), bal.get("current_liabilities"))
    if cr is None:
        details.append("Current ratio unavailable (+0)")
        flags.append("financial_strength: current_ratio missing, scored 0")
    elif cr >= 2.0:
        score += 2
        details.append(f"Current ratio {cr:.2f} >= 2.0 ✓ (+2)")
    elif cr >= 1.5:
        score += 1
        details.append(f"Current ratio {cr:.2f} >= 1.5 ✓ (+1)")
    else:
        details.append(f"Current ratio {cr:.2f} < 1.5 ✗ (+0)")

    dr = _ratio(bal.get("total_liabilities"), bal.get("total_assets"))
    if dr is None:
        details.append("Debt ratio unavailable (+0)")
        flags.append("financial_strength: debt_ratio missing, scored 0")
    elif dr < 0.5:
        score += 2
        details.append(f"Debt ratio {dr:.2f} < 0.50 ✓ (+2)")
    elif dr < 0.8:
        score += 1
        details.append(f"Debt ratio {dr:.2f} < 0.80 ✓ (+1)")
    else:
        details.append(f"Debt ratio {dr:.2f} >= 0.80 ✗ (+0)")

    div_periods = [
        p["ttm"]["dividends_and_other_cash_distributions"]
        for p in periods
        if p["ttm"].get("dividends_and_other_cash_distributions") is not None
    ]
    if not div_periods:
        details.append("No dividend data available ✗ (+0)")
        flags.append("financial_strength: dividends absent, scored 0")
    else:
        # Dividend outflow is negative in the filings; paid = strictly negative.
        paid = sum(1 for d in div_periods if d < 0)
        if paid >= len(div_periods) // 2 + 1:
            score += 1
            details.append(f"Dividends paid in {paid}/{len(div_periods)} reporting periods (majority) ✓ (+1)")
        else:
            details.append(f"Dividends paid in only {paid}/{len(div_periods)} reporting periods ✗ (+0)")

    return {"score": score, "max": 5, "details": details}


def analyze_valuation(periods: list, market_cap: float, flags: list) -> dict:
    score, details = 0, []
    latest = periods[0]
    ttm, bal = latest["ttm"], latest["balance"]
    shares = bal.get("outstanding_shares")

    price = _ratio(market_cap, shares)
    eps = _ratio(ttm.get("net_income"), shares)
    bvps = _ratio(bal.get("shareholders_equity"), shares)

    ncav = None
    if bal.get("current_assets") is not None and bal.get("total_liabilities") is not None:
        ncav = bal["current_assets"] - bal["total_liabilities"]
        details.append(f"NCAV ${ncav:,.0f} vs market cap ${market_cap:,.0f}")
        if ncav > market_cap:
            score += 4
            details.append("Net-net: NCAV > market cap (classic Graham deep value) ✓ (+4)")
        else:
            ncav_ps = _ratio(ncav, shares)
            if ncav_ps is None or price is None:
                details.append("Per-share net-net check unavailable (+0)")
                flags.append("valuation: outstanding_shares missing, per-share net-net check scored 0")
            elif ncav_ps >= price * (2 / 3):
                score += 2
                details.append(
                    f"NCAV/share ${ncav_ps:,.2f} >= 2/3 of price/share ${price:,.2f} ✓ (+2)"
                )
            else:
                details.append(
                    f"NCAV/share ${ncav_ps:,.2f} < 2/3 of price/share ${price:,.2f} ✗ (+0)"
                )
    else:
        details.append("NCAV unavailable (+0)")
        flags.append("valuation: current_assets or total_liabilities missing, net-net check scored 0")

    graham_number = None
    if eps is None or bvps is None:
        details.append("Graham Number unavailable (+0)")
        flags.append("valuation: EPS or BVPS inputs missing, Graham Number checks scored 0")
    elif eps > 0 and bvps > 0:
        graham_number = math.sqrt(22.5 * eps * bvps)
        details.append(f"Graham Number ${graham_number:,.2f}")
    else:
        # Legitimate 0, not a data gap: negative earnings or book value means
        # Graham walks away — no flag.
        details.append(f"Graham Number not meaningful (EPS {eps:.2f}, BVPS {bvps:.2f} — needs both > 0) (+0)")

    mos = None
    if graham_number is not None and price is not None and price > 0:
        mos = (graham_number - price) / price
        if mos > 0.5:
            score += 3
            details.append(f"Margin of safety {mos:.1%} > 50% vs Graham Number ✓ (+3)")
        elif mos > 0.2:
            score += 1
            details.append(f"Margin of safety {mos:.1%} > 20% vs Graham Number ✓ (+1)")
        else:
            details.append(f"Margin of safety {mos:.1%} vs Graham Number ✗ (+0)")

    return {
        "score": score,
        "max": 7,
        "details": details,
        "ncav": ncav,
        "price_per_share": price,
        "eps": eps,
        "book_value_per_share": bvps,
        "graham_number": graham_number,
        "margin_of_safety": None if mos is None else round(mos, 4),
    }


# ---------------------------------------------------------------------------
# signal, confidence, diagnosis


def compute_signal(score_pct: float, mos: float | None) -> str:
    if mos is not None and mos <= DEEP_OVERPRICE_MOS:
        return "bearish"
    if score_pct >= BULLISH_SCORE:
        return "bullish"
    if score_pct <= BEARISH_SCORE:
        return "bearish"
    return "neutral"


def compute_confidence(score_pct: float, mos: float | None) -> int:
    dist = min(abs(score_pct - BULLISH_SCORE), abs(score_pct - BEARISH_SCORE))
    conf = round(50 + 50 * min(1.0, dist / MAX_BOUNDARY_DIST))
    if mos is not None and mos <= DEEP_OVERPRICE_MOS:
        depth = round(50 + 100 * min(0.5, DEEP_OVERPRICE_MOS - mos))
        conf = max(conf, depth)
    return conf


def diagnose(snapshot: dict) -> dict:
    # Validation layer first (quarterly array only: Graham must stay invariant
    # to annual_periods). ERROR findings hard-fail with a better message than
    # the generic gap report; WARN findings surface in data_quality.
    findings, checks_run = validation.run_checks(snapshot, arrays=("periods",))
    errors = [f for f in findings if f["severity"] == validation.ERROR]
    if errors:
        raise MissingDataError(
            f"{snapshot.get('ticker')}: validation failed -- "
            + "; ".join(f["message"] for f in errors)
        )

    validate(snapshot)
    periods = snapshot["periods"]
    market_cap = snapshot["market_cap"]
    flags: list[str] = []

    # 8-K Item 4.02 restatement guard (ticket #55 A9, parity with the Buffett
    # scorer): the snapshot already carries the fetch-time finding; Graham
    # scores quarterly TTM windows, so every window ending inside or before
    # the latest restated fiscal year rests on non-reliable statements and is
    # excluded (Buffett's exact-membership rule, widened to the windows that
    # overlap those years).
    excluded_years = validation.restatement_excluded_years(findings)
    if excluded_years:
        cutoff = max(excluded_years)
        kept = [p for p in periods if p["period_end"] > cutoff]
        flags.append(
            "restatement: quarterly windows ending on or before "
            f"{cutoff} excluded (8-K Item 4.02 non-reliance on fiscal years "
            + ", ".join(excluded_years)
            + ")"
        )
        if len([p for p in kept if _is_complete(p)]) < MIN_COMPLETE_PERIODS:
            raise MissingDataError(
                f"{snapshot.get('ticker')}: fewer than {MIN_COMPLETE_PERIODS} "
                "complete quarterly periods remain after excluding windows "
                f"ending on or before the restated fiscal year {cutoff}"
            )
        periods = kept

    valuation = analyze_valuation(periods, market_cap, flags)
    dimensions = {
        "earnings_stability": analyze_earnings_stability(periods, flags),
        "financial_strength": analyze_financial_strength(periods, flags),
        "valuation": {"score": valuation["score"], "max": valuation["max"], "details": valuation["details"]},
    }

    total = sum(d["score"] for d in dimensions.values())
    score_pct = total / MAX_SCORE
    mos = valuation["margin_of_safety"]

    signal = compute_signal(score_pct, mos)
    if mos is not None and mos <= DEEP_OVERPRICE_MOS and score_pct > BEARISH_SCORE:
        dimensions["valuation"]["details"].append(
            f"Deep-overprice override: margin of safety {mos:.1%} <= {DEEP_OVERPRICE_MOS:.0%}"
            " vs Graham Number forces bearish — price alone rules the name out"
        )

    result = {
        "ticker": snapshot["ticker"],
        "signal": signal,
        "confidence": compute_confidence(score_pct, mos),
        "score": {"total": total, "max": MAX_SCORE, "max_possible": MAX_SCORE, "pct": round(score_pct, 4)},
        "dimensions": dimensions,
        "valuation": {
            "market_cap": market_cap,
            "ncav": valuation["ncav"],
            "price_per_share": valuation["price_per_share"],
            "eps": valuation["eps"],
            "book_value_per_share": valuation["book_value_per_share"],
            "graham_number": valuation["graham_number"],
            "margin_of_safety": valuation["margin_of_safety"],
        },
        "flags": flags,
        "data_quality": _link_data_quality(
            validation.data_quality(findings, checks_run)
        ),
        "provenance": {
            "snapshot_fetched_at": snapshot["fetched_at"],
            "market_cap_source": snapshot["market_cap_source"],
            "source": snapshot["source"],
            "periods": [p["period_end"] for p in periods],
        },
    }
    # Unscored context (ticket #52): the insider_activity snapshot section is
    # whale-agnostic; pass it through verbatim when present so any whale's
    # subagent can cite it. Never scored.
    if "insider_activity" in snapshot:
        result["insider_activity"] = snapshot["insider_activity"]
    return result
