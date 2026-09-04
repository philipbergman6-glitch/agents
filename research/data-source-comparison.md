# Financial data source comparison

Financial data-source comparison, researched 2026-07-24 via three parallel research agents (web + live API/library tests). Full requirement, from the Buffett rubric: per ticker, **10 TTM periods** of ratios (ROE, ROIC, debt/equity, operating margin, gross margin, current ratio), ~12 raw line items (net income, revenue, FCF, capex, D&A, equity, assets/liabilities, shares, dividends, buybacks), and market cap as of a date.

## Verdict table

| Criterion | SEC EDGAR (+ edgartools) | financialdatasets.ai | yfinance |
|---|---|---|---|
| Cost | **Free** (User-Agent header, 10 req/s) | No free tier; 10-yr history requires **$200/mo** Build tier ($20 credits tier = 1 yr only) | Free (unofficial) |
| Trustworthiness | **Authoritative** — the primary source itself | High — parses EDGAR directly, prices via Databento | Medium — Yahoo-scraped, undocumented ratio definitions |
| 10 TTM periods | ✅ 15+ yrs structured (XBRL since 2009); edgartools computes TTM with historical `as_of` | ✅ native `period=ttm&limit=10` (Build tier) | ❌ **hard blocker: 5 annual / 6 quarterly periods max** (verified live, v1.5.2) |
| Pre-computed ratios | ❌ compute from line items (aligned with our deterministic-engine design) | ✅ all six, exact fields reference code reads | Current snapshot only, no history |
| Market cap as-of date | ❌ shares outstanding only — needs a price feed supplement | ✅ (via financial-metrics; field presence confirmed only via ai-hedge-fund usage, not docs) | ✅ ~2016+ via `get_shares_full` × price, with gap/split caveats |
| Reproducibility | **Strongest** — filings immutable; snapshot companyfacts for strict PIT | Undocumented revision policy; corrections can rewrite history → must cache | Poor — silent restatements, documented non-determinism (issues #995, #626) |
| Reliability | SEC infrastructure; 10 req/s or nightly bulk zip | Occasional 500s/429s (ai-hedge-fund issues #321, #295, #307) | 429 crackdowns since Nov 2024; ToS prohibits scraping |
| Coverage | US SEC registrants (incl. 20-F/40-F filers) | US only, 27k+ tickers incl. delisted | Global, but shallow |

## Key findings per source

### SEC EDGAR — free, authoritative, viable via edgartools
- Free JSON APIs (`companyconcept`, `companyfacts`, `frames`) + nightly bulk `companyfacts.zip`. No key; declared User-Agent required; 10 req/s limit.
- Raw parsing burden is substantial (tag fallbacks — e.g. 4 different Microsoft revenue tags over a few years; Q4 = FY − Q1..Q3 derivation; fiscal-year alignment), **but [edgartools](https://github.com/dgunning/edgartools) absorbs most of it**: v5.43.0 (2026-07-19), 2.5k stars, very active, TTM built in with automatic Q4 derivation, tag-fallback revenue helpers, split adjustment, and historical `as_of="2024-Q2"`-style TTM — exactly the 10-historical-TTM-periods shape we need. It does not compute ratios; we compute ROE/ROIC etc. ourselves, which our determinism requirement demands anyway.
- No prices/market cap — supplement with a price feed (yfinance or Stooq) + `dei:EntityCommonStockSharesOutstanding` (cross-check against balance-sheet share count; reconcile split adjustment).
- Point-in-time: filings themselves are immutable (amendments stack as new filings); the aggregated APIs return latest-filed values, so strict reproducibility still requires snapshotting fetched data — same mitigation as every other source.

### financialdatasets.ai — perfect fit, wrong price
- Exactly matches the upstream ai-hedge-fund API (`financial-metrics` with `period=ttm&limit=10`, `search/line-items` with the exact field names the Buffett agent requests). Zero adaptation work.
- **No free tier** (confirmed on official pricing page + one independent review). $20 one-time credits tier covers only **1 year** of financials — useless for 10 TTM periods. Effective cost: **$200/mo**.
- Revision/immutability policy undocumented; provenance page punts to support email. Local caching required for determinism regardless.
- ai-hedge-fund issue tracker shows recurring operational friction: 60 req/min throttling (#295), server 500s on the line-items endpoint (#321), credits consumed on failed calls (#139).

### yfinance — disqualified as primary, useful as price supplement
- **Verified live today (v1.5.2): annual statements return exactly 5 periods, quarterly 6.** The 10-period requirement is unreachable; no supported path to unlock more.
- TTM exists but current-period only; ratios are snapshot-only with undocumented definitions.
- Yahoo's ToS prohibits scraping; IP-based 429 blocking has recurred since late 2024. Non-point-in-time; documented same-query-different-result issues.
- Adequate for: daily price history and approximate market cap back to ~2016 (shares series has multi-month gaps needing forward-fill; beware splits inside gaps).

## Recommendation

**Primary: SEC EDGAR via the `edgartools` library. Price/market-cap supplement: yfinance (fallback: Stooq). Determinism: snapshot every fetched payload to a local pinned-data cache; tests run only against the cache.**

Reasoning:
1. Every source requires local caching for byte-identical replay anyway — so financialdatasets.ai's one real advantage (zero adaptation work) costs $200/mo and still doesn't buy reproducibility. EDGAR is free, primary-source, and its filing archive is the only genuinely immutable record.
2. yfinance's 5-period cap disqualifies it as the fundamentals backend outright; its legitimate role is the thin price/market-cap layer, where its weaknesses (restatements, ratio definitions) don't apply and its data is easy to pin.
3. Computing ratios ourselves from EDGAR line items is not extra work relative to the destination — the deterministic engine must own every formula anyway (numbers never come from an LLM, and now also never from a vendor's undocumented ratio definitions).

Cost of this choice, eyes open:
- **Adaptation work**: the upstream ai-hedge-fund heuristics consume pre-computed metric objects; our data layer must build an equivalent metrics object from EDGAR line items (ROIC needs an explicit invested-capital definition — no standard XBRL tag; the rubric should fix the formula).
- **Coverage**: US SEC registrants only — same limit as financialdatasets.ai, so nothing lost.
- **De-risking step for implementation**: pilot edgartools' historical `as_of` TTM on ~10 diverse tickers (non-calendar fiscal year like AAPL, a bank, a recent IPO) before building on it; fall back to `companyconcept` + own stitching only if the pilot fails.
