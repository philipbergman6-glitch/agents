"""Offline phase: pure function of one snapshot -> full-diagnostic dict.

Faithful port of the six dimensions in reference/warren_buffett.py (max 27 =
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
  scoring 0 as "unavailable" like the reference (intentional deviation)

Determinism contract: same snapshot dict -> identical output dict. No I/O,
no clocks, no randomness in this module.
"""

from __future__ import annotations

from datetime import date

from ..errors import MissingDataError

MAX_SCORE = 27
TAX_RATE = 0.21
SHARES_OUTLIER_RATIO = 3.0

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


def _ratio(num, den):
    if num is None or den is None or den == 0:
        return None
    return num / den


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
    if dte is not None and dte < 0.5:
        score += 2
        details.append(f"Debt/equity {dte:.2f} < 0.5 ✓ (+2)")
    elif dte is not None:
        details.append(f"Debt/equity {dte:.2f} >= 0.5 ✗ (+0)")
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
    earnings = [p["ttm"]["net_income"] for p in periods if p["ttm"].get("net_income")]
    if len(earnings) < 4:
        flags.append("consistency: fewer than 4 earnings periods, excluded from denominator")
        return {"score": 0, "max": 3, "excluded": True, "details": ["Insufficient earnings history (excluded)"]}
    # Graduated credit (judgment-review tuning): monotonic = 3, at most one
    # down-step = 2, positive overall trend = 1.
    steps = len(earnings) - 1
    grew_steps = sum(1 for i in range(steps) if earnings[i] > earnings[i + 1])
    if grew_steps == steps:
        score = 3
        details.append(f"Earnings grew every period across {len(earnings)} TTM windows ✓ (+3)")
    elif grew_steps >= steps - 1:
        score = 2
        details.append(f"Earnings grew in {grew_steps}/{steps} steps across {len(earnings)} TTM windows ✓ (+2)")
    elif earnings[0] > earnings[-1]:
        score = 1
        details.append(f"Earnings up oldest-to-latest but grew in only {grew_steps}/{steps} steps ✓ (+1)")
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
        return {"score": 0, "max": 5, "excluded": True, "details": ["Insufficient history for moat analysis (excluded)"]}
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
        recent = sum(margins[:3]) / 3
        older = sum(margins[-3:]) / 3
        if avg > 0.2 and recent >= older:
            score += 1
            details.append(f"Operating margins avg {avg:.1%} > 20% and stable/improving ✓ (+1)")
        else:
            details.append(f"Operating margins avg {avg:.1%} (recent {recent:.1%} vs older {older:.1%}) ✗ (+0)")

    turnovers = [m["asset_turnover"] for m in metrics if m["asset_turnover"] is not None]
    if len(turnovers) >= 3 and any(t > 1.0 for t in turnovers):
        score += 1
        details.append("Asset turnover > 1.0 observed ✓ (+1)")

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
        return {"score": 0, "max": 5, "excluded": True, "details": ["Insufficient gross margin history (excluded)"]}

    recent = sum(margins[:2]) / 2
    older = sum(margins[-2:]) / 2
    if recent > older + 0.02:
        score += 3
        details.append(f"Gross margin expanding: {older:.1%} -> {recent:.1%} ✓ (+3)")
    elif recent > older:
        score += 2
        details.append(f"Gross margin improving: {older:.1%} -> {recent:.1%} ✓ (+2)")
    elif abs(recent - older) < 0.01:
        score += 1
        details.append(f"Gross margin stable near {recent:.1%} ✓ (+1)")
    else:
        details.append(f"Gross margin declining: {older:.1%} -> {recent:.1%} ✗ (+0)")

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
    usable = [
        p
        for p in periods
        if p["balance"].get("shareholders_equity") and p["balance"].get("outstanding_shares")
    ]
    # Cover-page share facts lag one quarter, so a split between filings leaves
    # one period on the pre-split count — off by the split ratio, not by drift.
    # Buybacks move counts a few percent a year; >3x off the median is a split
    # artifact or a mis-tagged fact, never a real capital change.
    if usable:
        counts = sorted(p["balance"]["outstanding_shares"] for p in usable)
        median = counts[len(counts) // 2]
        kept = []
        for p in usable:
            shares = p["balance"]["outstanding_shares"]
            if shares > median * SHARES_OUTLIER_RATIO or shares < median / SHARES_OUTLIER_RATIO:
                flags.append(
                    f"book_value: {p['period_end']} share count {shares:.4g} is >"
                    f"{SHARES_OUTLIER_RATIO:g}x off the median {median:.4g} "
                    "(split artifact or mis-tagged fact), period excluded"
                )
            else:
                kept.append(p)
        usable = kept

    book_values = [
        p["balance"]["shareholders_equity"] / p["balance"]["outstanding_shares"] for p in usable
    ]
    if len(book_values) < 3:
        flags.append("book_value: fewer than 3 BVPS periods, excluded from denominator")
        return {"score": 0, "max": 5, "excluded": True, "details": ["Insufficient book value history (excluded)"]}

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
    # Periods are quarterly TTM windows, so counting them would treat quarters
    # as years; span the actual period_end dates instead.
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


def calculate_intrinsic_value(periods: list) -> dict:
    if len(periods) < 3:
        raise MissingDataError("intrinsic value: fewer than 3 periods")
    earnings_data = calculate_owner_earnings(periods)
    owner_earnings = earnings_data["owner_earnings"]

    historical = [p["ttm"]["net_income"] for p in periods[:5] if p["ttm"].get("net_income")]
    # Both endpoints must be positive: a negative ratio raised to 1/years is
    # complex (reference bug — it only guarded the oldest value).
    if len(historical) >= 3 and historical[-1] > 0 and historical[0] > 0:
        years = len(historical) - 1
        growth = (historical[0] / historical[-1]) ** (1 / years) - 1
        growth = max(-0.05, min(growth, 0.15)) * 0.7
    else:
        growth = 0.03

    stage1_growth = min(growth, 0.08)
    stage2_growth = min(growth * 0.5, 0.04)
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
        "intrinsic_value": intrinsic * 0.85,  # reference's 15% conservatism haircut
        "raw_intrinsic_value": intrinsic,
        "owner_earnings": owner_earnings,
        "owner_earnings_components": earnings_data,
        "dcf_stages": {
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


def diagnose(snapshot: dict) -> dict:
    validate(snapshot)
    periods = snapshot["periods"]
    flags: list[str] = []

    metrics = [compute_metrics(p) for p in periods]

    dimensions = {
        "fundamentals": analyze_fundamentals(metrics[0], flags),
        "consistency": analyze_consistency(periods, flags),
        "moat": analyze_moat(metrics, flags),
        "management": analyze_management(periods, flags),
        "pricing_power": analyze_pricing_power(periods, flags),
        "book_value": analyze_book_value(periods, flags),
    }

    # Renormalize (judgment-review tuning): dimensions with insufficient data
    # are excluded from the denominator rather than counted as zeros.
    total = sum(d["score"] for d in dimensions.values())
    max_effective = sum(d["max"] for d in dimensions.values() if not d.get("excluded"))
    if max_effective == 0:
        raise MissingDataError(f"{snapshot['ticker']}: no scorable dimensions")
    score_pct = total / max_effective

    valuation = calculate_intrinsic_value(periods)
    market_cap = snapshot["market_cap"]
    mos = (valuation["intrinsic_value"] - market_cap) / market_cap

    return {
        "ticker": snapshot["ticker"],
        "signal": compute_signal(score_pct, mos),
        "confidence": compute_confidence(score_pct, mos),
        "score": {"total": total, "max": max_effective, "max_possible": MAX_SCORE, "pct": round(score_pct, 4)},
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
        "flags": flags,
        "provenance": {
            "snapshot_fetched_at": snapshot["fetched_at"],
            "market_cap_source": snapshot["market_cap_source"],
            "source": snapshot["source"],
            "periods": [p["period_end"] for p in periods],
        },
    }
