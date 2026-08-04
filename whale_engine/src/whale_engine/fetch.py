"""Networked phase: SEC EDGAR (edgartools) + Cboe delayed quote -> snapshot JSON.

The snapshot is the only artifact `diagnose` ever reads. Everything fetched is
recorded verbatim with the XBRL tag it came from, so any number in a diagnosis
can be traced back to a filing.

Market cap (issue #45 decision): derived as Cboe delayed close x the freshest
*filed* EDGAR share count (freshest across dei cover page, filing cover sums,
us-gaap counts, and the weighted-average proxy — #77) — never sourced from
yfinance. A Cboe miss or a stale quote (last trade > QUOTE_STALENESS_DAYS
calendar days) is a hard FetchError; the only alternative path is the explicit
--market-cap manual override (provenance "manual:owner-supplied"). yfinance is
an optional cross-check witness: if importable it contributes a
market_cap_check block, if not the snapshot carries a WARN entry — its absence
is never load-bearing, but when it IS present and disagrees past
validation.MARKET_CAP_WITNESS_TOLERANCE the fetch hard-fails (#77): a
disagreement that wide means the derived share basis is corrupt. The fetched
price + quote timestamp are pinned in the snapshot (price_reference) like all
other raw data, so diagnose stays deterministic.

Sign conventions follow the reference implementation (financialdatasets style):
- capital_expenditure: negative = cash out
- dividends_and_other_cash_distributions: negative = paid
- issuance_or_purchase_of_equity_shares: issuance proceeds minus repurchase
  payments; negative = net buyback

Two period arrays, both most recent first:
- periods: N_PERIODS trailing-twelve-month windows stepped quarterly (~2.5y).
- annual_periods: up to N_ANNUAL_PERIODS directly-filed fiscal-year durations
  (~10y). Each entry keeps the same ttm/balance/tags_used shape — a fiscal-year
  duration is the TTM as of that fiscal year end — so scorers can consume
  either array with the same code. Fields a year never filed under any known
  tag stay None; completeness rules belong to the consuming scorer.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

from . import validation
from .errors import FetchError

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
    "dividends_paid": [
        "PaymentsOfDividends",
        "PaymentsOfDividendsCommonStock",
        "PaymentsOfOrdinaryDividends",
    ],
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
    # Ordered specific-first; the later entries carry filers that retired the
    # plain debt tags (BLDR files only LongTermDebtAndCapitalLeaseObligations
    # since 2016 — ticket #55 F3). A tag only wins when it has a value at the
    # period end, so era-appropriate tags resolve per fiscal year.
    "long_term_debt": [
        "LongTermDebtNoncurrent",
        "LongTermDebt",
        "LongTermDebtAndCapitalLeaseObligations",
        "NotesPayableNoncurrent",
        "FinanceLeaseLiabilityNoncurrent",
    ],
    "outstanding_shares": [
        "CommonStockSharesOutstanding",
        "EntityCommonStockSharesOutstanding",
        "CommonStockSharesIssued",
    ],
}

# Short-term debt is a sum-of-parts fallback: use DebtCurrent when filed,
# otherwise sum one resolved tag per slot. Tags within a slot are alternative
# spellings of the same component (summing both would double-count — BLDR
# files LongTermDebtAndCapitalLeaseObligationsCurrent where older filers used
# LongTermDebtCurrent); slots are disjoint components.
ST_DEBT_PRIMARY = "DebtCurrent"
ST_DEBT_COMPONENT_SLOTS = [
    ["ShortTermBorrowings"],
    ["CommercialPaper"],
    ["LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"],
]
ST_DEBT_COMPONENTS = [tag for slot in ST_DEBT_COMPONENT_SLOTS for tag in slot]

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

# Deep-history window: fiscal years of annual facts. EDGAR's companyfacts API
# carries XBRL back to ~2009, so most filers fill all 10; younger companies get
# however many fiscal years exist.
N_ANNUAL_PERIODS = 10

# --- per-filing XBRL fallback ---------------------------------------------
# The companyfacts API only carries us-gaap/dei facts and drops dimensioned
# ones, which loses (a) extension-tagged D&A lines (MSFT's
# msft:DepreciationAmortizationAndOther) and (b) per-class cover-page share
# counts (V's Class A/B-1/B-2/C). Both are present in each filing's own XBRL,
# so when the companyfacts path leaves those fields null we re-derive them by
# iterating 10-K/10-Q filings directly.
FALLBACK_FORMS = ["10-K", "10-Q"]
MAX_FALLBACK_FILINGS = 24
COVER_SHARES_TAG = "EntityCommonStockSharesOutstanding"
# A raw sum of per-class counts ignores conversion ratios (V's B/C convert to
# A at ~1.6x/1x), so it can sit ~5-10% off the market's as-converted count.
# Anything beyond this factor vs yfinance means classes were double-counted,
# missed, or include preferred — corrupt, so hard-fail.
SHARES_MISMATCH_FACTOR = 1.4
_ANNUAL_DAYS = (350, 380)
_END_MATCH_DAYS = 5

# --- market cap: Cboe delayed quote (issue #45) ----------------------------
# First-party keyless CDN endpoint backing Cboe's own quote pages. One JSON
# GET, ~4 fields used; unknown tickers return HTTP 403.
CBOE_QUOTE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/quotes/{ticker}.json"
# Last trade older than this many calendar days means halted/delisted/stale
# feed — hard-fail, never silently use the price.
QUOTE_STALENESS_DAYS = 5
MARKET_CAP_MANUAL_SOURCE = "manual:owner-supplied"

# --- 8-K Item 4.02 restatement guard (validation check 7, ticket #48) ------
# A 4.02 8-K declares previously issued financial statements non-reliable.
# Which fiscal years it covers is stated in prose, not metadata, so without
# parsing the filing text we conservatively treat the fiscal years ending in
# the RESTATEMENT_AFFECTED_YEARS before the 8-K filing date as affected;
# scorers exclude them from history dimensions (standard renormalization path).
RESTATEMENT_ITEM = "4.02"
RESTATEMENT_WINDOW_YEARS = 10
RESTATEMENT_AFFECTED_YEARS = 3

# --- sector-only snapshot (ticket #94) -------------------------------------
# A separate, deliberately tiny artifact carrying the one EDGAR field the
# portfolio layer needs. It is never a snapshot: `kind` marks it, it lives in
# its own directory, and no scorer may read it. See fetch_sector_snapshot.
SECTOR_SCHEMA_VERSION = 1
SECTOR_SNAPSHOT_KIND = "sector-only"


def _require_identity() -> str:
    identity = os.environ.get("EDGAR_IDENTITY", "").strip()
    if not identity:
        raise FetchError(
            "EDGAR_IDENTITY is not set. SEC EDGAR requires a declared identity, "
            'e.g. export EDGAR_IDENTITY="Jane Doe jane@example.com"'
        )
    return identity


def _edgar_company(ticker: str):
    """Identified EDGAR company lookup. Network seam for tests."""
    import edgar

    edgar.set_identity(_require_identity())
    return edgar.Company(ticker)


def _edgartools_version() -> str:
    import edgar

    return str(getattr(edgar, "__version__", "unknown"))


def _company_sic(company) -> tuple[str | None, str | None, dict | None]:
    """EDGAR submissions SIC code + description: (sic, sic_description, warning).

    Additive field for the portfolio layer's sector check (ticket #84, per
    methodology #82, which groups by 2-digit SIC major group). No scorer reads
    it, so an absent or unusable code is a WARN finding, never a failed fetch —
    the sector rule downstream decides what to do without one.
    """
    def _warn(reason: str) -> dict:
        return validation.finding(
            validation.WARN,
            "sic_unavailable",
            f"EDGAR submissions SIC unavailable ({reason}); sector grouping "
            "has no source for this snapshot.",
        )

    try:
        raw_sic = company.sic
        raw_desc = company.industry
    except Exception as e:
        return None, None, _warn(f"{type(e).__name__}: {e}")

    sic = str(raw_sic).strip() if raw_sic is not None else ""
    if not sic.isdigit():
        return None, None, _warn(f"code {raw_sic!r} is not numeric")
    desc = str(raw_desc).strip() if raw_desc is not None else ""
    return sic, (desc or None), None


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


def _annual_fiscal_year_ends(history) -> set:
    """End dates of all annual-length durations in a concept history.

    Companyfacts durations come straight from filings (FY, quarter, YTD), so
    annual-length ones only ever end at fiscal year ends.
    """
    if history is None or "period_start" not in history.columns:
        return set()
    dur = history[history["period_type"] == "duration"]
    ends = set()
    for s, e in zip(dur["period_start"], dur["period_end"]):
        sd, ed = _to_plain_date(s), _to_plain_date(e)
        if sd and ed and _ANNUAL_DAYS[0] <= (ed - sd).days <= _ANNUAL_DAYS[1]:
            ends.add(ed)
    return ends


def _annual_at(history, fy_end: date) -> tuple[float, date, date] | None:
    """Annual-length duration ending at fy_end (within _END_MATCH_DAYS).

    Restatements file the same fiscal year again; the row from the latest
    filing_date wins. Returns (value, period_start, period_end) or None.
    """
    if history is None or "period_start" not in history.columns:
        return None
    dur = history[history["period_type"] == "duration"].copy()
    dur = dur[dur["period_start"].notna() & dur["period_end"].notna()]
    if dur.empty:
        return None
    dur["_start"] = dur["period_start"].map(_to_plain_date)
    dur["_end"] = dur["period_end"].map(_to_plain_date)
    keep = [
        s is not None
        and e is not None
        and _ANNUAL_DAYS[0] <= (e - s).days <= _ANNUAL_DAYS[1]
        and abs((e - fy_end).days) <= _END_MATCH_DAYS
        for s, e in zip(dur["_start"], dur["_end"])
    ]
    hits = dur[keep]
    if hits.empty:
        return None
    row = hits.sort_values("filing_date").iloc[-1]
    return float(row["numeric_value"]), row["_start"], row["_end"]


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


def _cboe_get_json(ticker: str) -> dict:
    """One keyless GET against the Cboe delayed-quote CDN. Network seam for tests."""
    import json as _json
    import urllib.request

    url = CBOE_QUOTE_URL.format(ticker=ticker.upper())
    req = urllib.request.Request(url, headers={"User-Agent": "whale-engine snapshot fetch"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return _json.loads(resp.read().decode("utf-8"))


def _fetch_cboe_close(ticker: str, today: date) -> tuple[float, str, str]:
    """Cboe delayed close for ticker: (price, price_field, last_trade_time).

    Hard-fails (FetchError) on any miss — unknown ticker (Cboe answers 403),
    network failure, missing/non-positive price, or a last trade older than
    QUOTE_STALENESS_DAYS calendar days. No silent fallback; the error names
    the --market-cap manual override.
    """
    try:
        payload = _cboe_get_json(ticker)
    except Exception as e:
        raise FetchError(
            f"{ticker}: Cboe delayed-quote fetch failed "
            f"({type(e).__name__}: {e}). Check the ticker symbol, retry, or "
            "pass --market-cap VALUE to override manually."
        ) from e

    data = payload.get("data") or {}
    price, price_field = None, None
    for field in ("close", "prev_day_close"):
        value = data.get(field)
        if value:
            price, price_field = float(value), field
            break
    if price is None or price <= 0:
        raise FetchError(
            f"{ticker}: Cboe quote carries no usable close price "
            f"(close={data.get('close')!r}, prev_day_close={data.get('prev_day_close')!r}). "
            "Pass --market-cap VALUE to override manually."
        )

    last_trade = data.get("last_trade_time")
    try:
        trade_date = date.fromisoformat(str(last_trade)[:10])
    except (TypeError, ValueError):
        raise FetchError(
            f"{ticker}: Cboe quote has no parseable last_trade_time "
            f"({last_trade!r}) — cannot verify quote freshness. "
            "Pass --market-cap VALUE to override manually."
        ) from None
    age_days = (today - trade_date).days
    if age_days > QUOTE_STALENESS_DAYS:
        raise FetchError(
            f"{ticker}: Cboe last trade {last_trade} is {age_days} calendar "
            f"days old (limit {QUOTE_STALENESS_DAYS}) — halted, delisted, or a "
            "stale feed. Refusing the price; pass --market-cap VALUE to "
            "override manually."
        )
    return price, price_field, str(last_trade)


def _manual_market_cap(value) -> tuple[float, str]:
    """Validate the --market-cap override. Hard-fail on non-positive input."""
    try:
        cap = float(value)
    except (TypeError, ValueError):
        raise FetchError(f"--market-cap must be a number, got {value!r}") from None
    if not cap > 0:
        raise FetchError(f"--market-cap must be positive, got {value!r}")
    return cap, MARKET_CAP_MANUAL_SOURCE


def _yfinance_reference_cap(ticker: str) -> tuple[float, str]:
    """Optional yfinance witness for the cross-check. Raises if unavailable."""
    import yfinance as yf

    t = yf.Ticker(ticker)
    try:
        mc = t.fast_info["market_cap"]
        if mc:
            return float(mc), "yfinance:fast_info.market_cap"
    except Exception:
        pass
    mc = t.info.get("marketCap")
    if mc:
        return float(mc), "yfinance:info.marketCap"
    raise FetchError(f"{ticker}: yfinance returned no market cap")


def _yfinance_crosscheck(ticker: str, derived_cap: float, warnings: list) -> dict | None:
    """Compare the derived cap to yfinance if it happens to work.

    Witness absence is never load-bearing: any failure appends a WARN entry
    and returns None. When the witness IS available, the caller gates on the
    recorded deviation (#77), and validation re-checks it offline on every
    stored snapshot.
    """
    try:
        reference, source = _yfinance_reference_cap(ticker)
    except Exception as e:
        warnings.append(
            {
                "severity": "WARN",
                "code": "yfinance-crosscheck-unavailable",
                "message": (
                    f"{ticker}: optional yfinance market-cap cross-check "
                    f"unavailable ({type(e).__name__}: {e}); derived market "
                    "cap stands uncorroborated."
                ),
            }
        )
        return None
    return {
        "derived": derived_cap,
        "reference": reference,
        "reference_source": source,
        "deviation_pct": (derived_cap - reference) / reference * 100.0,
    }


def _gate_market_cap_witness(
    ticker: str, market_cap: float, market_cap_source: str, check: dict | None
) -> None:
    """Witness gate (#77): refuse a derived cap the yfinance witness contradicts.

    A deviation past MARKET_CAP_WITNESS_TOLERANCE means the filed share basis
    is corrupt (e.g. a pre-split dei fact). No check (witness unreachable) is
    not gated — absence stays WARN-only.
    """
    if check is None:
        return
    if abs(check["deviation_pct"]) / 100.0 <= validation.MARKET_CAP_WITNESS_TOLERANCE:
        return
    raise FetchError(
        f"{ticker}: derived market cap {market_cap:.4g} ({market_cap_source}) "
        f"deviates {check['deviation_pct']:.1f}% from the "
        f"{check['reference_source']} witness {check['reference']:.4g} "
        f"(tolerance {validation.MARKET_CAP_WITNESS_TOLERANCE:.0%}) — the "
        "filed share basis looks corrupt. Pass --market-cap VALUE to "
        "override manually."
    )


def _to_plain_date(v) -> date | None:
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


def _collect_filing_facts(company, dna_tags: list[str], need_shares: bool):
    """One pass over recent 10-K/10-Q XBRL documents.

    Returns (dna_by_localname, cover_share_rows):
    - dna_by_localname: {local tag name: {(start, end): (value, full_concept)}},
      consolidated duration facts only; the most recent filing wins a (start,
      end) key, so restated values shadow originals.
    - cover_share_rows: [(instant, summed value, n class rows, filing_date)],
      one row per filing cover page, most recent filing first per instant.
    """
    dna_by_localname: dict[str, dict] = {tag: {} for tag in dna_tags}
    cover_rows: list[tuple] = []
    seen_instants: set = set()

    filings = company.get_filings(form=FALLBACK_FORMS).head(MAX_FALLBACK_FILINGS)
    for filing in filings:
        try:
            xbrl = filing.xbrl()
        except Exception:
            continue
        if xbrl is None:
            continue

        for tag in dna_tags:
            try:
                df = xbrl.query().by_concept(tag).to_dataframe()
            except Exception:
                continue
            if df is None or df.empty:
                continue
            # by_concept matches fuzzily and ignores namespace prefixes, which
            # is what lets it find extension tags — but require an exact local
            # name so e.g. 'Depreciation' does not absorb 'DepreciationAnd...'.
            df = df[df["concept"].str.split(":").str[-1] == tag]
            if "is_dimensioned" in df.columns:
                df = df[~df["is_dimensioned"].astype(bool)]
            for row in df.itertuples():
                start = _to_plain_date(getattr(row, "period_start", None))
                end = _to_plain_date(getattr(row, "period_end", None))
                value = getattr(row, "numeric_value", None)
                if start is None or end is None or value is None:
                    continue
                dna_by_localname[tag].setdefault((start, end), (float(value), row.concept))

        if need_shares:
            try:
                df = xbrl.query().by_concept(COVER_SHARES_TAG).to_dataframe()
            except Exception:
                df = None
            if df is not None and not df.empty:
                df = df[df["concept"] == f"dei:{COVER_SHARES_TAG}"]
                if not df.empty and "numeric_value" in df.columns:
                    by_instant: dict = {}
                    for row in df.itertuples():
                        instant = _to_plain_date(getattr(row, "period_instant", None))
                        value = getattr(row, "numeric_value", None)
                        if instant is None or value is None:
                            continue
                        by_instant.setdefault(instant, []).append(float(value))
                    for instant, values in by_instant.items():
                        if instant not in seen_instants:
                            seen_instants.add(instant)
                            cover_rows.append(
                                (instant, sum(values), len(values), str(filing.filing_date))
                            )

    return dna_by_localname, cover_rows


def _ttm_from_filing_durations(dna_by_localname: dict, window_end: date):
    """TTM value ending at window_end from per-filing duration facts.

    Per concept (never mixing concepts): a direct ~12-month fact wins;
    otherwise stitch annual(prior FY) + YTD(current) - YTD(prior year), all
    three sharing fiscal-year boundaries. Returns (value, provenance) or None.
    """
    for tag, facts in dna_by_localname.items():
        # Direct 12-month duration ending at the window end.
        for (start, end), (value, concept) in sorted(facts.items()):
            if (
                abs((end - window_end).days) <= _END_MATCH_DAYS
                and _ANNUAL_DAYS[0] <= (end - start).days <= _ANNUAL_DAYS[1]
            ):
                return value, f"filing-fallback:{concept}@{start}..{end}"

        # Stitch: prefer the longest YTD ending at the window end.
        ytds = [
            (start, end, value, concept)
            for (start, end), (value, concept) in facts.items()
            if abs((end - window_end).days) <= _END_MATCH_DAYS
            and (end - start).days < _ANNUAL_DAYS[0]
        ]
        for y_start, y_end, y_value, y_concept in sorted(
            ytds, key=lambda t: (t[1] - t[0]).days, reverse=True
        ):
            for (a_start, a_end), (a_value, _) in sorted(facts.items()):
                if not (
                    _ANNUAL_DAYS[0] <= (a_end - a_start).days <= _ANNUAL_DAYS[1]
                    and 0 <= (y_start - a_end).days <= _END_MATCH_DAYS
                ):
                    continue
                ytd_days = (y_end - y_start).days
                for (p_start, p_end), (p_value, _) in sorted(facts.items()):
                    if (
                        abs((p_start - a_start).days) <= _END_MATCH_DAYS
                        and abs((p_end - p_start).days - ytd_days) <= 10
                    ):
                        return (
                            a_value + y_value - p_value,
                            f"filing-fallback:{y_concept}"
                            f"@FY{a_end}+YTD{y_end}-YTD{p_end}",
                        )
    return None


# Value keys are renamed before the snapshot is written (reference naming);
# tags_used provenance must follow, or a field->provenance join silently
# reports the renamed fields as unattributed (audit b-6, validation check 5a).
_TAG_RENAMES = {"dividends_paid": "dividends_and_other_cash_distributions"}
_TAG_COMBINES = {
    "issuance_or_purchase_of_equity_shares": ["share_issuance", "share_repurchase"]
}
_COMBINE_LEG_FIELDS = {leg for legs in _TAG_COMBINES.values() for leg in legs}


def _realign_tags(tags_used: dict) -> None:
    """Rename provenance (and *_warning) keys to match the stored value keys."""
    for old, new in _TAG_RENAMES.items():
        if old in tags_used:
            tags_used[new] = tags_used.pop(old)
        if f"{old}_warning" in tags_used:
            tags_used[f"{new}_warning"] = tags_used.pop(f"{old}_warning")
    for new, olds in _TAG_COMBINES.items():
        tags = [tags_used.pop(old) for old in olds if old in tags_used]
        if tags:
            tags_used[new] = "+".join(tags)
        warnings = [
            tags_used.pop(f"{old}_warning")
            for old in olds
            if f"{old}_warning" in tags_used
        ]
        if warnings:
            tags_used[f"{new}_warning"] = " | ".join(dict.fromkeys(warnings))
        dropped = [
            tags_used.pop(f"{old}_dropped")
            for old in olds
            if f"{old}_dropped" in tags_used
        ]
        if dropped:
            tags_used[f"{new}_dropped"] = " | ".join(dict.fromkeys(dropped))


def _check_restatements(company, annual_periods: list, today: date) -> list[dict]:
    """8-K Item 4.02 non-reliance filings in the lookback window -> findings.

    Networked and fetch-time only. Failure to read the item metadata is
    reported as an explicit WARN finding, never swallowed.
    """
    from . import validation

    try:
        filings = company.get_filings(form="8-K")
        hits = []
        for filing in filings or []:
            filed = _to_plain_date(getattr(filing, "filing_date", None))
            if filed is None or (today - filed).days > RESTATEMENT_WINDOW_YEARS * 365.25:
                continue
            items = getattr(filing, "items", None)
            if items is None:
                continue
            item_list = items if isinstance(items, (list, tuple)) else [
                s.strip() for s in str(items).replace(";", ",").split(",")
            ]
            if any(RESTATEMENT_ITEM in str(item) for item in item_list):
                hits.append(filed)
    except Exception as e:  # explicit degradation, not a silent skip
        return [
            validation.finding(
                validation.WARN,
                "restatement_guard_unavailable",
                f"could not read 8-K item metadata ({type(e).__name__}: {e}); "
                "the Item 4.02 restatement guard did not run",
            )
        ]

    findings = []
    for filed in sorted(hits):
        affected = [
            p["period_end"]
            for p in annual_periods
            if p.get("period_end")
            and 0
            <= (filed - date.fromisoformat(p["period_end"])).days
            <= RESTATEMENT_AFFECTED_YEARS * 365.25
        ]
        findings.append(
            validation.finding(
                validation.WARN,
                "restatement_402",
                f"8-K Item {RESTATEMENT_ITEM} (non-reliance on previously issued "
                f"financial statements) filed {filed.isoformat()}; fiscal years "
                f"{', '.join(affected) if affected else '(none in window)'} are "
                "excluded from history dimensions",
                filing_date=filed.isoformat(),
                affected_period_ends=affected,
            )
        )
    return findings


def _freshest_instant(history) -> tuple[float, str] | None:
    """Latest instant fact in a concept history, regardless of period matching.

    Used for market cap, where the freshest *filed* count beats the count
    matched to the latest fiscal period end (cuts NVDA-style staleness).
    Restatements: latest filing_date wins the instant.
    """
    inst = history[history["period_type"] == "instant"].copy()
    inst = inst[inst["period_end"].notna()]
    if inst.empty:
        return None
    inst["_end"] = inst["period_end"].map(_to_plain_date)
    inst = inst[inst["_end"].notna()]
    if inst.empty:
        return None
    best_end = inst["_end"].max()
    at_end = inst[inst["_end"] == best_end].sort_values("filing_date")
    row = at_end.iloc[-1]
    return float(row["numeric_value"]), str(row["period_end"])[:10]


def _freshest_share_count(
    ticker: str,
    share_histories: list,
    cover_rows: list,
    shares_proxy_history,
    latest_window_end: date,
) -> tuple[float, str]:
    """Freshest filed share count for market cap, across every source.

    Candidates: (1) undimensioned dei EntityCommonStockSharesOutstanding from
    companyfacts; (2) per-filing multi-class cover sums (V-type filers, where
    companyfacts drops the dimensioned counts); (3) freshest us-gaap
    point-in-time count; (4) weighted-average-basic proxy. The freshest
    instant wins; source order above breaks date ties, so the dei cover page
    still leads whenever it is current. Strict source priority is what let a
    2010 dei fact (pre-split) outrank a current proxy count and poison MA's
    market cap by −86% (#77). Hard-fail if no source exists — market cap
    needs a share count.
    """
    candidates: list[tuple[date, int, float, str]] = []
    for tag, history in share_histories:
        if tag != COVER_SHARES_TAG or history is None:
            continue
        hit = _freshest_instant(history)
        if hit is not None:
            candidates.append(
                (date.fromisoformat(hit[1]), 0, hit[0], f"dei:{COVER_SHARES_TAG}@{hit[1]}")
            )
    if cover_rows:
        latest = max(cover_rows, key=lambda r: r[0])
        candidates.append(
            (
                latest[0],
                1,
                latest[1],
                f"filing-cover-sum:dei:{COVER_SHARES_TAG}@{latest[0].isoformat()}"
                f"(sum of {latest[2]} classes)",
            )
        )
    for tag, history in share_histories:
        if tag == COVER_SHARES_TAG or history is None:
            continue
        hit = _freshest_instant(history)
        if hit is not None:
            candidates.append((date.fromisoformat(hit[1]), 2, hit[0], f"{tag}@{hit[1]}"))
    if shares_proxy_history is not None:
        hit = _duration_at(shares_proxy_history, latest_window_end)
        if hit is not None:
            candidates.append(
                (
                    date.fromisoformat(str(hit[1])[:10]),
                    3,
                    hit[0],
                    f"proxy:{SHARES_PROXY_TAG}@{str(hit[1])[:10]}",
                )
            )
    if candidates:
        best = min(candidates, key=lambda c: (-c[0].toordinal(), c[1]))
        return best[2], best[3]
    raise FetchError(
        f"{ticker}: no share count on EDGAR under any known tag — cannot "
        "derive market cap. Pass --market-cap VALUE to override manually."
    )


def _build_balance(
    window_end: date,
    balance_histories: dict,
    st_debt_histories: list,
    liabilities_total_history,
    shares_proxy_history,
) -> tuple[dict, dict]:
    """Point-in-time balance sheet at window_end, with per-field tag provenance.

    Shared by the quarterly and annual paths; returns (balance, tags_used).
    """
    balance: dict = {}
    tags_used: dict = {}
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
        # One resolved tag per slot: tags within a slot are alternative
        # spellings of the same component and must never be summed together.
        by_tag = dict(st_debt_histories[1:])
        parts, part_tags = [], []
        for slot in ST_DEBT_COMPONENT_SLOTS:
            for tag in slot:
                history = by_tag.get(tag)
                if history is None:
                    continue
                hit = _balance_at(history, window_end)
                if hit is not None:
                    parts.append(hit[0])
                    part_tags.append(tag)
                    break
        balance["short_term_debt"] = sum(parts) if parts else None
        if parts:
            tags_used["short_term_debt"] = "+".join(part_tags)

    return balance, tags_used


def _fetch_annual_periods(
    ticker: str,
    flow_histories: dict,
    balance_histories: dict,
    st_debt_histories: list,
    liabilities_total_history,
    shares_proxy_history,
) -> list[dict]:
    """Up to N_ANNUAL_PERIODS fiscal years of directly-filed annual facts.

    Anchored on net-income FY durations; each field walks its fallback-tag
    list per fiscal year, so years filed under retired tags (e.g.
    SalesRevenueNet before 2018) still resolve.
    """
    ends: set = set()
    for _tag, history in flow_histories["net_income"]:
        ends |= _annual_fiscal_year_ends(history)
    fy_ends = sorted(ends, reverse=True)[:N_ANNUAL_PERIODS]
    if not fy_ends:
        raise FetchError(
            f"{ticker}: no annual net-income durations on EDGAR — cannot build "
            "deep-history annual periods."
        )

    annual_periods = []
    for fy_end in fy_ends:
        ttm: dict = {}
        tags_used: dict = {}
        period_start: date | None = None

        for field, histories in flow_histories.items():
            ttm[field] = None
            for tag, history in histories:
                hit = _annual_at(history, fy_end)
                if hit is None:
                    continue
                value, start, end = hit
                ttm[field] = -value if field in NEGATE_FLOWS else value
                tags_used[field] = f"{tag}@{start}..{end}"
                if field == "net_income":
                    period_start = start
                break

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
        _realign_tags(tags_used)

        balance, balance_tags = _build_balance(
            fy_end,
            balance_histories,
            st_debt_histories,
            liabilities_total_history,
            shares_proxy_history,
        )
        tags_used.update(balance_tags)

        annual_periods.append(
            {
                "period_start": period_start.isoformat() if period_start else None,
                "period_end": fy_end.isoformat(),
                "ttm": ttm,
                "balance": balance,
                "tags_used": tags_used,
            }
        )
    return annual_periods


def fetch_snapshot(
    ticker: str, today: date | None = None, market_cap_override: float | None = None
) -> dict:
    """Fetch N_PERIODS historical TTM periods + market cap into a snapshot dict."""
    import edgar

    # Validate the override before any network work: hard-fail on bad input.
    manual_cap: tuple[float, str] | None = None
    if market_cap_override is not None:
        manual_cap = _manual_market_cap(market_cap_override)

    warnings: list[dict] = []

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

    flow_histories = {
        field: [(tag, _concept_history(company, tag)) for tag in tags]
        for field, tags in FLOW_TAGS.items()
    }
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
            # Freshness gate on multi-leg combines (ticket #55 A1): a combine
            # sums legs fetched independently, so one abandoned tag (BLDR's
            # share-issuance, last window 2015) silently pollutes the sum with
            # a decade-stale value. net_income anchors window_end and is first
            # in FLOW_TAGS, so it is always set before any combine leg.
            if (
                field in _COMBINE_LEG_FIELDS
                and window_end is not None
                and m.as_of_date is not None
                and (window_end - m.as_of_date).days > validation.STALE_WINDOW_DAYS
            ):
                lag = (window_end - m.as_of_date).days
                ttm[field] = None
                tags_used[f"{field}_dropped"] = (
                    f"{tag}: TTM window ends {m.as_of_date.isoformat()}, lagging "
                    f"the period end {window_end.isoformat()} by {lag} days "
                    f"(> {validation.STALE_WINDOW_DAYS}); stale leg dropped from "
                    "the combine"
                )
                continue
            value = -float(m.value) if field in NEGATE_FLOWS else float(m.value)
            ttm[field] = value
            tags_used[field] = tag
            # Stitched-TTM warnings for every field, not just net_income
            # (audit a-3/b-1, validation check 1): the diagnosis must be able
            # to surface that these are edgartools arithmetic, not filed data.
            if m.has_gaps or m.warning:
                tags_used[f"{field}_warning"] = str(m.warning or "has_gaps")
            if field == "net_income":
                window_end = m.as_of_date

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
        _realign_tags(tags_used)

        balance, balance_tags = _build_balance(
            window_end,
            balance_histories,
            st_debt_histories,
            liabilities_total_history,
            shares_proxy_history,
        )
        tags_used.update(balance_tags)

        periods.append(
            {
                # Labeled from the actual window end, not the requested
                # calendar quarter: edgartools clamps a not-yet-filed quarter
                # to the latest available window, so the requested q can run
                # up to two quarters ahead of the data it returns (ticket #55
                # F4 — BLDR's 2026-03-31 window labeled "2026-Q3").
                "as_of_quarter": f"{window_end.year}-Q{(window_end.month - 1) // 3 + 1}",
                "period_end": window_end.isoformat(),
                "ttm": ttm,
                "balance": balance,
                "tags_used": tags_used,
            }
        )

    annual_periods = _fetch_annual_periods(
        ticker,
        flow_histories,
        balance_histories,
        st_debt_histories,
        liabilities_total_history,
        shares_proxy_history,
    )

    # Per-filing XBRL fallback for fields companyfacts drops (see constants).
    missing_dna = [
        p for p in periods if p["ttm"]["depreciation_and_amortization"] is None
    ]
    missing_shares = [p for p in periods if p["balance"]["outstanding_shares"] is None]
    missing_shares_annual = [
        p for p in annual_periods if p["balance"]["outstanding_shares"] is None
    ]
    share_count_check = None
    cover_rows: list = []
    if missing_dna or missing_shares or missing_shares_annual:
        dna_facts, cover_rows = _collect_filing_facts(
            company,
            dna_tags=FLOW_TAGS["depreciation_and_amortization"] if missing_dna else [],
            need_shares=bool(missing_shares or missing_shares_annual),
        )
        for p in missing_dna:
            hit = _ttm_from_filing_durations(dna_facts, date.fromisoformat(p["period_end"]))
            if hit is not None:
                p["ttm"]["depreciation_and_amortization"] = hit[0]
                p["tags_used"]["depreciation_and_amortization"] = hit[1]

        # Opportunistic: the collected filings only reach ~6 years back, but
        # the direct-annual branch of the stitcher fills whatever they cover.
        if missing_dna:
            for p in annual_periods:
                if p["ttm"]["depreciation_and_amortization"] is not None:
                    continue
                hit = _ttm_from_filing_durations(
                    dna_facts, date.fromisoformat(p["period_end"])
                )
                if hit is not None:
                    p["ttm"]["depreciation_and_amortization"] = hit[0]
                    p["tags_used"]["depreciation_and_amortization"] = hit[1]

        if (missing_shares or missing_shares_annual) and cover_rows:
            # Sanity-check the raw multi-class sum against EDGAR's own
            # weighted-average-basic count (as-converted, so ~1x for sane
            # sums) — yfinance is retired from this path (#45).
            latest = max(cover_rows, key=lambda r: r[0])
            reference = reference_source = ratio = None
            if shares_proxy_history is not None:
                proxy_hit = _duration_at(shares_proxy_history, latest[0])
                if proxy_hit is not None:
                    reference = proxy_hit[0]
                    reference_source = f"edgar:{SHARES_PROXY_TAG}@{proxy_hit[1]}"
            if reference:
                ratio = latest[1] / reference
                if not (1 / SHARES_MISMATCH_FACTOR <= ratio <= SHARES_MISMATCH_FACTOR):
                    raise FetchError(
                        f"{ticker}: cover-page share sum {latest[1]:.4g} "
                        f"({latest[2]} classes @ {latest[0]}) is {ratio:.2f}x the "
                        f"{reference_source} count {reference:.4g} — class "
                        "conversion or preferred-stock mis-summation; refusing to "
                        "snapshot a corrupt share count."
                    )
            else:
                warnings.append(
                    {
                        "severity": "WARN",
                        "code": "share-sum-reference-unavailable",
                        "message": (
                            f"{ticker}: no weighted-average share count on "
                            "EDGAR to sanity-check the multi-class cover-page "
                            "sum; the 1.4x mismatch guard did not run."
                        ),
                    }
                )
            share_count_check = {
                "cover_page_sum": latest[1],
                "cover_page_instant": latest[0].isoformat(),
                "share_classes": latest[2],
                "reference": reference,
                "reference_source": reference_source,
                "ratio": ratio,
            }
            import pandas as pd

            cover_history = pd.DataFrame(
                {
                    "period_type": "instant",
                    "period_end": [r[0].isoformat() for r in cover_rows],
                    "numeric_value": [r[1] for r in cover_rows],
                    "filing_date": [r[3] for r in cover_rows],
                }
            )
            classes_by_instant = {r[0].isoformat(): r[2] for r in cover_rows}
            # Annual periods too: collected filings only reach ~6 years back,
            # so old fiscal years may stay None — validation handles that.
            for p in missing_shares + missing_shares_annual:
                hit = _balance_at(cover_history, date.fromisoformat(p["period_end"]))
                if hit is not None:
                    p["balance"]["outstanding_shares"] = hit[0]
                    p["tags_used"]["outstanding_shares"] = (
                        f"filing-fallback:dei:{COVER_SHARES_TAG}@{hit[1]}"
                        f"(sum of {classes_by_instant[hit[1]]} classes)"
                    )

    # Market cap (#45): manual override, else Cboe delayed close x freshest
    # filed EDGAR share count. Cboe miss / stale quote = hard FetchError.
    price_reference = None
    market_cap_check = None
    if manual_cap is not None:
        market_cap, market_cap_source = manual_cap
        market_data_source = "manual override (--market-cap)"
    else:
        shares, shares_source = _freshest_share_count(
            ticker,
            balance_histories["outstanding_shares"],
            cover_rows,
            shares_proxy_history,
            date.fromisoformat(periods[0]["period_end"]),
        )
        price, price_field, last_trade_time = _fetch_cboe_close(ticker, today)
        market_cap = price * shares
        market_cap_source = (
            f"derived:cboe.{price_field}@{last_trade_time}x{shares_source}"
        )
        market_data_source = "cboe:delayed_quotes (keyless CDN, delayed close)"
        # Pin the raw price like every other fetched number, so the derived
        # cap is fully re-derivable and validation (#48) can bound-check it.
        price_reference = {
            "source": "cboe:delayed_quotes",
            "price": price,
            "price_field": price_field,
            "last_trade_time": last_trade_time,
            "shares": shares,
            "shares_source": shares_source,
        }
        market_cap_check = _yfinance_crosscheck(ticker, market_cap, warnings)
        _gate_market_cap_witness(ticker, market_cap, market_cap_source, market_cap_check)

    # Filings-text moat sidecar (ticket #49): cited narration evidence, never
    # a scoring input. Extraction failure must not fail the fetch — it lands
    # as a WARN finding on the snapshot instead.
    from .filings_text import extract_filings_text

    filings_sidecar, filings_warnings = extract_filings_text(company, ticker)

    import edgar as _edgar_mod

    # Additive sector fields (#84): EDGAR submissions SIC, for the portfolio
    # layer's 2-digit major-group concentration check. Never scored, so no
    # schema_version bump — a pre-#84 snapshot is still a valid v2 and is
    # distinguishable by the keys being absent entirely, where a post-#84
    # snapshot with no SIC carries them as null plus a sic_unavailable WARN.
    sic, sic_description, sic_warning = _company_sic(company)
    if sic_warning is not None:
        warnings.append(sic_warning)

    snapshot = {
        "schema_version": 2,
        "ticker": ticker.upper(),
        "fetched_at": today.isoformat(),
        "sic": sic,
        "sic_description": sic_description,
        "market_cap": market_cap,
        "market_cap_source": market_cap_source,
        "source": {
            "fundamentals": f"SEC EDGAR via edgartools {getattr(_edgar_mod, '__version__', 'unknown')}",
            "market_data": market_data_source,
        },
        "periods": periods,  # most recent first
        "annual_periods": annual_periods,  # most recent fiscal year first
    }
    if price_reference is not None:
        snapshot["price_reference"] = price_reference
    if market_cap_check is not None:
        snapshot["market_cap_check"] = market_cap_check
    if share_count_check is not None:
        snapshot["share_count_check"] = share_count_check
    if filings_sidecar is not None:
        # Carries a transient "markdown" key; the CLI pops it, writes the
        # sidecar file next to the snapshot, and records "path".
        snapshot["filings_sidecar"] = filings_sidecar

    # Form 4 insider buy-cluster context (ticket #52, per #47): whale-agnostic
    # unscored section. Fetch failure = WARN in the validation findings, never
    # a failed fetch; section omitted on failure so "no cluster" stays
    # distinguishable from "not checked".
    from .insider import collect_insider_activity

    insider_section, insider_warning = collect_insider_activity(company, today)
    if insider_section is not None:
        snapshot["insider_activity"] = insider_section

    # Fetch-only findings from the sidecar (#49), market-cap cross-check (#50)
    # and Form 4 (#52) paths merge into the validation section (#48); their
    # codes are registered in validation.FETCH_ONLY_CODES so diagnoses carry
    # them forward from stored snapshots.
    extra_findings = list(filings_warnings) + list(warnings)
    if insider_warning is not None:
        extra_findings.append(insider_warning)
    _attach_validation(snapshot, company, today, extra_findings)
    return snapshot


def fetch_sector_snapshot(ticker: str, today: date | None = None) -> dict:
    """EDGAR submissions -> a sector-only snapshot: the SIC code, nothing else.

    Ticket #94. The portfolio layer reads exactly one EDGAR field — the SIC
    code, for the 2-digit major-group concentration check (#82 §3) — but the
    only route to a snapshot was `fetch`, which hard-fails any company without
    N_PERIODS distinct TTM windows. A recent IPO in a client's basket
    therefore killed the entire report with an error about fundamentals depth
    (a whale-scoring concern the portfolio layer never asked about), and the
    insufficient-history path designed in #82/#83 could not fire on any real
    young name.

    This is a separate artifact, not a degraded snapshot: it carries `kind`
    SECTOR_SNAPSHOT_KIND, is written to its own directory (snapshots/sectors/,
    beside snapshots/prices/), and no scorer ever reads it. Whale scoring, the
    fetch depth requirement, and the 10-TTM-window rule are untouched (#40).

    An absent or unusable SIC stays a WARN rather than a failure, exactly as
    on a full fetch, so the portfolio layer's `sector_unavailable` path
    behaves identically whichever route produced the file.
    """
    ticker = ticker.upper()
    _require_identity()
    today = today or date.today()

    try:
        company = _edgar_company(ticker)
    except Exception as e:
        raise FetchError(
            f"{ticker}: EDGAR company lookup failed ({type(e).__name__}: {e}). "
            "Check the ticker symbol."
        ) from e
    cik = getattr(company, "cik", None)
    if not cik:
        raise FetchError(
            f"{ticker}: EDGAR knows no company under this ticker — nothing to "
            "look a sector up from."
        )

    sic, sic_description, sic_warning = _company_sic(company)

    return {
        "schema_version": SECTOR_SCHEMA_VERSION,
        "kind": SECTOR_SNAPSHOT_KIND,
        "ticker": ticker,
        "fetched_at": today.isoformat(),
        "cik": str(cik),
        "company_name": str(getattr(company, "name", "") or "") or None,
        "sic": sic,
        "sic_description": sic_description,
        "source": {"sector": f"SEC EDGAR submissions via edgartools {_edgartools_version()}"},
        "warnings": [sic_warning] if sic_warning is not None else [],
    }


def _attach_validation(
    snapshot: dict, company, today: date, extra_findings: list[dict] | None = None
) -> None:
    """Write the snapshot's validation section (ticket #48).

    The pure checks over the snapshot, plus the fetch-only 8-K 4.02
    restatement guard. INFO findings live here only; diagnose recomputes the
    pure checks and carries the fetch-only findings forward.
    """
    from . import validation

    findings, checks_run = validation.run_checks(snapshot)
    restatement_findings = _check_restatements(
        company, snapshot["annual_periods"], today
    )
    guard_ran = not any(
        f["code"] == "restatement_guard_unavailable" for f in restatement_findings
    )
    snapshot["validation"] = {
        "findings": (extra_findings or []) + findings + restatement_findings,
        "checks_run": checks_run + (["restatement_402"] if guard_ran else []),
    }
