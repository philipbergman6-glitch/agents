"""Networked phase: SEC EDGAR (edgartools) + yfinance -> snapshot JSON.

The snapshot is the only artifact `diagnose` ever reads. Everything fetched is
recorded verbatim with the XBRL tag it came from, so any number in a diagnosis
can be traced back to a filing.

Sign conventions follow the reference implementation (financialdatasets style):
- capital_expenditure: negative = cash out
- dividends_and_other_cash_distributions: negative = paid
- issuance_or_purchase_of_equity_shares: issuance proceeds minus repurchase
  payments; negative = net buyback
"""

from __future__ import annotations

import os
from datetime import date, timedelta

# TTM flow concepts: engine field -> ordered XBRL tag fallbacks.
FLOW_TAGS: dict[str, list[str]] = {
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
    ],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "capital_expenditure": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "PaymentsForCapitalImprovements",
    ],
    "depreciation_and_amortization": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization",
        "DepreciationAmortizationAndOther",
        "Depreciation",
    ],
    "dividends_paid": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
    "share_repurchase": ["PaymentsForRepurchaseOfCommonStock"],
    "share_issuance": [
        "ProceedsFromIssuanceOfCommonStock",
        "ProceedsFromIssuanceOrSaleOfEquity",
    ],
}

# Flow fields where EDGAR reports a positive cash outflow but the engine
# stores the financialdatasets-style signed value.
NEGATE_FLOWS = {"capital_expenditure", "dividends_paid", "share_repurchase"}

# Point-in-time balance concepts: engine field -> ordered XBRL tag fallbacks.
BALANCE_TAGS: dict[str, list[str]] = {
    "shareholders_equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "cash_and_equivalents": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "outstanding_shares": [
        "CommonStockSharesOutstanding",
        "EntityCommonStockSharesOutstanding",
        "CommonStockSharesIssued",
    ],
}

# Short-term debt is a sum-of-parts fallback: use DebtCurrent when filed,
# otherwise sum whichever components exist at that period end.
ST_DEBT_PRIMARY = "DebtCurrent"
ST_DEBT_COMPONENTS = ["ShortTermBorrowings", "CommercialPaper", "LongTermDebtCurrent"]

# Many filers (KO, AAL, CCL) never tag Liabilities directly; derive it from the
# balance-sheet identity when both sides are filed for the same period end.
LIABILITIES_TOTAL_TAG = "LiabilitiesAndStockholdersEquity"

# Some filers (F) expose no point-in-time common share count in the facts API;
# fall back to TTM-window weighted-average basic shares as a proxy.
SHARES_PROXY_TAG = "WeightedAverageNumberOfSharesOutstandingBasic"

# How far a balance-sheet instant may sit before the TTM window end and still
# count as "the balance for that period" (covers 13/14-week fiscal quarters).
BALANCE_STALENESS_DAYS = 135

N_PERIODS = 10


class FetchError(RuntimeError):
    pass


def _require_identity() -> str:
    identity = os.environ.get("EDGAR_IDENTITY", "").strip()
    if not identity:
        raise FetchError(
            "EDGAR_IDENTITY is not set. SEC EDGAR requires a declared identity, "
            'e.g. export EDGAR_IDENTITY="Jane Doe jane@example.com"'
        )
    return identity


def _candidate_quarters(today: date, count: int) -> list[str]:
    """Most-recent-first calendar quarters, starting from the current one."""
    year, quarter = today.year, (today.month - 1) // 3 + 1
    out = []
    for _ in range(count):
        out.append(f"{year}-Q{quarter}")
        quarter -= 1
        if quarter == 0:
            year, quarter = year - 1, 4
    return out


def _concept_history(company, tag: str):
    """All exactly-matching facts for one XBRL tag, or None.

    edgartools' by_concept() matches fuzzily (e.g. 'StockholdersEquity' also
    returns 'LiabilitiesAndStockholdersEquity'), so filter to the exact
    us-gaap:/dei: concept.
    """
    try:
        df = company.facts.query().by_concept(tag).to_dataframe()
    except Exception:
        return None
    if df is None or df.empty:
        return None
    exact = df[df["concept"].isin([f"us-gaap:{tag}", f"dei:{tag}"])]
    return exact if not exact.empty else None


def _balance_at(history, window_end: date) -> tuple[float, str] | None:
    """Latest instant value at or before window_end, within staleness bounds.

    Restatements file the same period_end again; the row from the latest
    filing_date wins.
    """
    inst = history[history["period_type"] == "instant"].copy()
    inst = inst[inst["period_end"].notna()]
    if inst.empty:
        return None

    def _to_date(v):
        if isinstance(v, date):
            return v
        if hasattr(v, "date"):  # pandas Timestamp / datetime
            return v.date()
        return date.fromisoformat(str(v)[:10])

    inst["_end"] = inst["period_end"].map(_to_date)
    floor = window_end - timedelta(days=BALANCE_STALENESS_DAYS)
    hits = inst[(inst["_end"] <= window_end) & (inst["_end"] >= floor)]
    if hits.empty:
        return None
    best_end = hits["_end"].max()
    at_end = hits[hits["_end"] == best_end].sort_values("filing_date")
    row = at_end.iloc[-1]
    return float(row["numeric_value"]), str(row["period_end"])


def _duration_at(history, window_end: date) -> tuple[float, str] | None:
    """Latest duration-typed value ending at or before window_end, within
    staleness bounds. Same restatement rule as _balance_at: latest filing wins.
    """
    dur = history[history["period_type"] == "duration"].copy()
    dur = dur[dur["period_end"].notna()]
    if dur.empty:
        return None

    def _to_date(v):
        if isinstance(v, date):
            return v
        if hasattr(v, "date"):
            return v.date()
        return date.fromisoformat(str(v)[:10])

    dur["_end"] = dur["period_end"].map(_to_date)
    floor = window_end - timedelta(days=BALANCE_STALENESS_DAYS)
    hits = dur[(dur["_end"] <= window_end) & (dur["_end"] >= floor)]
    if hits.empty:
        return None
    best_end = hits["_end"].max()
    at_end = hits[hits["_end"] == best_end].sort_values("filing_date")
    row = at_end.iloc[-1]
    return float(row["numeric_value"]), str(row["period_end"])


def _ttm_value(company, tags: list[str], quarter: str):
    """Freshest TTM window across the fallback tags; tag order breaks ties.

    get_ttm clamps to the latest window a tag can build, so a tag abandoned
    years ago (e.g. MA files NetIncomeLoss annually since 2014) still returns a
    value — a decade stale. Picking the freshest as_of_date across tags lets a
    later, still-current tag (ProfitLoss) win over a stale earlier one.
    """
    best, best_tag = None, None
    for tag in tags:
        try:
            m = company.get_ttm(tag, as_of=quarter)
        except Exception:
            continue
        if m is None or m.value is None or m.as_of_date is None:
            continue
        if best is None or m.as_of_date > best.as_of_date:
            best, best_tag = m, tag
    return best, best_tag


def _fetch_market_cap(ticker: str) -> tuple[float, str]:
    import yfinance as yf

    t = yf.Ticker(ticker)
    try:
        mc = t.fast_info["market_cap"]
        if mc:
            return float(mc), "yfinance:fast_info.market_cap"
    except Exception:
        pass
    try:
        mc = t.info.get("marketCap")
        if mc:
            return float(mc), "yfinance:info.marketCap"
    except Exception:
        pass
    raise FetchError(
        f"Could not fetch market cap for {ticker} from yfinance. "
        "Market cap is a hard-fail input; retry later or check the ticker symbol."
    )


def fetch_snapshot(ticker: str, today: date | None = None) -> dict:
    """Fetch N_PERIODS historical TTM periods + market cap into a snapshot dict."""
    import edgar

    identity = _require_identity()
    edgar.set_identity(identity)
    today = today or date.today()

    company = edgar.Company(ticker)

    # Anchor on net income. Asking edgartools for a not-yet-filed quarter
    # clamps to the latest available TTM window, so walking back through
    # calendar quarters can return the same window repeatedly — dedupe on the
    # actual window end and keep the first N_PERIODS distinct windows.
    quarters: list[str] = []
    seen_ends: set = set()
    for q in _candidate_quarters(today, N_PERIODS + 8):
        m, _ = _ttm_value(company, FLOW_TAGS["net_income"], q)
        if m is None or m.as_of_date in seen_ends:
            continue
        seen_ends.add(m.as_of_date)
        quarters.append(q)
        if len(quarters) == N_PERIODS:
            break
    if len(quarters) < N_PERIODS:
        raise FetchError(
            f"{ticker}: only {len(quarters)} distinct TTM windows found on EDGAR "
            f"(need {N_PERIODS})."
        )

    balance_histories = {
        field: [(tag, _concept_history(company, tag)) for tag in tags]
        for field, tags in BALANCE_TAGS.items()
    }
    st_debt_histories = [
        (tag, _concept_history(company, tag))
        for tag in [ST_DEBT_PRIMARY] + ST_DEBT_COMPONENTS
    ]
    liabilities_total_history = _concept_history(company, LIABILITIES_TOTAL_TAG)
    shares_proxy_history = _concept_history(company, SHARES_PROXY_TAG)

    periods = []
    for q in quarters:
        ttm: dict = {}
        tags_used: dict = {}
        window_end: date | None = None

        for field, tags in FLOW_TAGS.items():
            m, tag = _ttm_value(company, tags, q)
            if m is None:
                ttm[field] = None
                continue
            value = -float(m.value) if field in NEGATE_FLOWS else float(m.value)
            ttm[field] = value
            tags_used[field] = tag
            if field == "net_income":
                window_end = m.as_of_date
                if m.has_gaps or m.warning:
                    tags_used["net_income_warning"] = str(m.warning or "has_gaps")

        if window_end is None:
            raise FetchError(f"{ticker} {q}: net income TTM vanished mid-fetch.")

        # Net issuance/buyback per reference convention (negative = buyback).
        issuance = ttm.pop("share_issuance", None)
        repurchase = ttm.pop("share_repurchase", None)  # already negated
        if issuance is None and repurchase is None:
            ttm["issuance_or_purchase_of_equity_shares"] = None
        else:
            ttm["issuance_or_purchase_of_equity_shares"] = (issuance or 0.0) + (
                repurchase or 0.0
            )
        ttm["dividends_and_other_cash_distributions"] = ttm.pop("dividends_paid", None)

        balance: dict = {}
        for field, histories in balance_histories.items():
            balance[field] = None
            for tag, history in histories:
                if history is None:
                    continue
                hit = _balance_at(history, window_end)
                if hit is not None:
                    balance[field] = hit[0]
                    tags_used[field] = f"{tag}@{hit[1]}"
                    break

        # Filers without a Liabilities tag: derive from the balance-sheet
        # identity, but only when both sides are stated as of the same date —
        # otherwise leave it None and let validation hard-fail loudly.
        if balance["total_liabilities"] is None and liabilities_total_history is not None:
            lse_hit = _balance_at(liabilities_total_history, window_end)
            if lse_hit is not None:
                # LiabilitiesAndStockholdersEquity includes noncontrolling
                # interest, so prefer the NCI-inclusive equity tag (listed last).
                for eq_tag, eq_history in reversed(balance_histories["shareholders_equity"]):
                    if eq_history is None:
                        continue
                    eq_hit = _balance_at(eq_history, window_end)
                    if eq_hit is not None and eq_hit[1] == lse_hit[1]:
                        balance["total_liabilities"] = lse_hit[0] - eq_hit[0]
                        tags_used["total_liabilities"] = (
                            f"derived:{LIABILITIES_TOTAL_TAG}-{eq_tag}@{lse_hit[1]}"
                        )
                        break

        # Filers with no point-in-time share count: weighted-average basic
        # shares for the latest reported duration is the closest proxy.
        if balance["outstanding_shares"] is None and shares_proxy_history is not None:
            proxy_hit = _duration_at(shares_proxy_history, window_end)
            if proxy_hit is not None:
                balance["outstanding_shares"] = proxy_hit[0]
                tags_used["outstanding_shares"] = f"proxy:{SHARES_PROXY_TAG}@{proxy_hit[1]}"

        primary_tag, primary_hist = st_debt_histories[0]
        primary_hit = _balance_at(primary_hist, window_end) if primary_hist is not None else None
        if primary_hit is not None:
            balance["short_term_debt"] = primary_hit[0]
            tags_used["short_term_debt"] = f"{primary_tag}@{primary_hit[1]}"
        else:
            parts, part_tags = [], []
            for tag, history in st_debt_histories[1:]:
                if history is None:
                    continue
                hit = _balance_at(history, window_end)
                if hit is not None:
                    parts.append(hit[0])
                    part_tags.append(tag)
            balance["short_term_debt"] = sum(parts) if parts else None
            if parts:
                tags_used["short_term_debt"] = "+".join(part_tags)

        periods.append(
            {
                "as_of_quarter": q,
                "period_end": window_end.isoformat(),
                "ttm": ttm,
                "balance": balance,
                "tags_used": tags_used,
            }
        )

    market_cap, market_cap_source = _fetch_market_cap(ticker)

    import edgar as _edgar_mod

    return {
        "schema_version": 1,
        "ticker": ticker.upper(),
        "fetched_at": today.isoformat(),
        "market_cap": market_cap,
        "market_cap_source": market_cap_source,
        "source": {
            "fundamentals": f"SEC EDGAR via edgartools {getattr(_edgar_mod, '__version__', 'unknown')}",
            "market_data": market_cap_source.split(":")[0],
        },
        "periods": periods,  # most recent first
    }
