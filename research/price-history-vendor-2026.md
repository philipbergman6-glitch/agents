# Price-history vendor selection (map #80, ticket #81) — 2026-07-29

**Question:** which keyed API supplies the portfolio layer's correlation input — ~3 years of adjusted price history for 5–15 US tickers, fetched by each client with their own key, pinned as snapshot files on disk (possibly committed to a private repo)?

**Method:** three parallel research agents (Tiingo; Alpha Vantage; Polygon/Massive + EODHD + FMP + Marketstack), official docs/pricing/ToS fetched directly where possible, July 2026. Every claim below is sourced in the per-vendor sections; items the agents could not verify are marked UNVERIFIED there.

## Recommendation (pinned)

**Alpha Vantage, free tier, `TIME_SERIES_WEEKLY_ADJUSTED`.** Weekly — not daily — adjusted closes, because that is the only combination on the market that is simultaneously: free, ≥3 years deep, split+dividend adjusted, storable under the vendor's ToS as written, and provisioned with an email-only instant key.

- **Fetch cost:** 1 request per ticker (full history in one call); a 15-ticker basket uses 15 of the free tier's 25 requests/day.
- **Key setup:** instant web form, no credit card; key passed as `apikey=` query param → the engine must take it from an env var (proposed: `ALPHAVANTAGE_API_KEY`), same client-config pattern as `EDGAR_IDENTITY`, and never echo it.
- **Statistical adequacy:** 3y of weekly returns ≈ 156 observations per pairwise correlation — standard practice for this purpose (weekly returns also carry less microstructure/asynchronous-close noise than daily). Final window/frequency ratification belongs to methodology ticket #82, but **daily frequency is now effectively a paid feature** at every acceptable vendor.
- **Engine hard-fail trap (implementation note for #84):** Alpha Vantage returns **HTTP 200 with an `"Information"` JSON body** when a free key hits a premium endpoint or the daily cap — the fetcher must treat any response lacking the time-series key as a hard failure, never as empty data.

**Fallback (if the owner decides daily is non-negotiable): EODHD "All World" at $19.99/mo per client.** Only vendor whose ToS *expressly permits* local storage for non-professional users and whose endpoint returns true split+dividend `adjusted_close` with from/to ranges; but it is a per-client subscription, and its delete-within-1-month-of-termination clause sits awkwardly with git history.

## Why not the others

| Vendor | Killer flaw for this use case |
|---|---|
| **Tiingo** (charter shortlist) | Free-tier ToS §1.6(a) **forbids persisting fetched data to disk at all** ("may not write, save, archive… in any persistent or durable storage") — the snapshot-pinning pattern is non-compliant on free keys; paid tiers require deleting all data on cancellation. |
| **Alpha Vantage daily** | `TIME_SERIES_DAILY_ADJUSTED` is premium-only (≥$49.99/mo); free `TIME_SERIES_DAILY` is explicitly raw/unadjusted — a split shows as a price cliff and would fabricate correlation. |
| **Polygon → Massive** (rebranded Oct 2025) | Free tier is 2 years (short of 3); aggregates are split-adjusted but **not dividend-adjusted**; market-data terms say "strictly for display use only"; polygon.io endpoints sunset during 2026. |
| **EODHD free** | 20 calls/day is fine but history is **1 year** — cannot deliver a 3y window. |
| **FMP** | Most hostile ToS: "may not copy or download any content… except with prior written approval," explicit prohibition on software products "designed for utilization by multiple individuals" consuming its data, delete-all-cached-data-on-termination with audit rights. Wrong foundation for a sold CLI. |
| **Marketstack** | 1-year free history and a documented history of broken `adj_close` (nulls, unapplied splits); ToS text not even locatable (generic APILayer/Idera hub). |

## License posture (applies to the recommendation)

Alpha Vantage's ToS contains **no clause on local storage, caching, retention, or redistribution** — pinning snapshots is not prohibited text. The license grant is "personal, non-commercial"; the risk vector is a *firm* (rather than an individual) using the data, or sharing fetched data with others, which the ToS defines as commercial use requiring a written arrangement. Mitigations, to carry into the distro docs (#87): each client provisions **their own** key and accepts the ToS themselves at signup (the license relationship is theirs); the distro continues its **no-snapshots-shipped** policy (price snapshots gitignored in the distro, like EDGAR snapshots already are); docs state plainly that business/firm use of Alpha Vantage data needs the client's own commercial arrangement with the vendor. This paragraph is ToS reading, not legal advice.

## Per-vendor evidence

The three agent reports below are reproduced verbatim (sources inline per claim).

### Tiingo

- Free "Starter": 50 req/hr, 1,000 req/day, 500 unique symbols/month; adjusted EOD daily, 30+ years history — https://www.tiingo.com/about/pricing
- Endpoint: `GET https://api.tiingo.com/tiingo/daily/<ticker>/prices?startDate=…&endDate=…` with `adjClose`, `splitFactor`, `divCash` — https://www.tiingo.com/documentation/end-of-day
- **ToS §1.6(a) (free/trial plans): "you may not write, save, archive, back up, or otherwise retain Tiingo Data in any persistent or durable storage"** — https://app.tiingo.com/tos/
- Paid: $30/mo individual, $50/mo internal-commercial; on cancellation "you must promptly and permanently delete all Tiingo Data from every system" — https://www.tiingo.com/about/pricing ; https://app.tiingo.com/tos/
- Redistribution only by special request with fees — https://www.tiingo.com/about/pricing
- Derived Products (§1.6(c)): non-reversible transformed outputs (e.g. scores) may be retained; raw series may not.
- Signup: email-only, token via query param or `Authorization: Token` header — https://www.tiingo.com/documentation/general/connecting
- Reputation: high data quality (EOD Price Engine), mature clients (PyPI `tiingo`, riingo); 2026 buyer's guide slots it "prototypes or internal tools" — https://pypi.org/project/tiingo/ ; https://eodhd.medium.com/best-market-data-apis-for-product-teams-in-2026-a-practical-buyers-guide-14f60038584e

### Alpha Vantage

- Free tier: **25 requests/day** ("up to 25 requests per day") — https://www.alphavantage.co/support/ ; https://www.alphavantage.co/premium/ (history of cuts 500→100→25: https://www.macroption.com/alpha-vantage-api-limits/)
- `TIME_SERIES_DAILY_ADJUSTED` premium-only ("this is a premium API function"); free `TIME_SERIES_DAILY` is "raw (as-traded)" — https://www.alphavantage.co/documentation/
- **`TIME_SERIES_WEEKLY_ADJUSTED` and `TIME_SERIES_MONTHLY_ADJUSTED` carry no premium marker — free**, 20+ years via `outputsize` semantics/full history — https://www.alphavantage.co/documentation/
- Premium: $49.99/mo (75 req/min) … $249.99/mo (1,200 req/min), no daily caps — https://www.alphavantage.co/premium/
- ToS (PDF, full text): **no storage/caching/redistribution/retention clauses at all**; license grant §2a "personal, non-commercial use"; commercial-use definition includes providing data access to others "directly or indirectly" — https://www.alphavantage.co/terms_of_service/
- Signup: one web form, instant key, no card — https://www.alphavantage.co/support/
- Failure mode: premium endpoint on free key → HTTP 200 + `"Information"` message body, not an error status — https://github.com/TauricResearch/TradingAgents/issues/305
- Reputation: solid data/uptime, NASDAQ-listed vendor; complaints target free-tier shrinkage, not quality — https://tradingtoolshub.com/review/alpha-vantage/ ; https://alphalog.ai/blog/alphavantage-api-complete-guide

### Polygon.io → Massive.com

- Rebrand effective 2025-10-30; polygon.io/pricing 301s to massive.com/pricing; old endpoints phase out during 2026 — https://massive.com/blog/polygon-is-now-massive
- Free "Stocks Basic": 5 calls/min, **2 years history**, individual/non-pro only — https://massive.com/pricing ; Starter $29/mo (unlimited calls, 5y)
- `/v2/aggs/…/range/1/day/{from}/{to}` `adjusted=true` = **split-adjusted only**; dividend adjustment requires combining the dividends endpoint (long-standing behavior, 2026 docs UNVERIFIED)
- Market Data Terms: data "strictly for display use only," non-pro "personal, non-business use" — https://massive.com/terms/market_data_terms.pdf ; Individuals ToS: personal/non-commercial, no transfer of access — https://massive.com/legal/individuals-terms-of-service

### EODHD

- Free: 20 calls/day, **1 year history**, adjusted close included — https://eodhd.com/pricing
- Paid "All World": $19.99/mo, 30+ years, 100k calls/day — https://eodhd.com/pricing
- `/api/eod/{TICKER}?from=…&to=…&fmt=json` → `adjusted_close` "adjusted for both splits and dividends" — https://eodhd.com/financial-apis/api-for-historical-data-and-volumes
- ToS: non-professional users "permitted to store, manipulate, and analyze the data for private, non-commercial purposes"; no resale/redistribution/display; **delete all copies within 1 month of termination** — https://eodhd.com/financial-apis/terms-conditions

### FMP

- Free: 250 calls/day, no card; free-tier daily-price depth UNVERIFIED (site 403s bots); Starter price conflicting/UNVERIFIED — https://site.financialmodelingprep.com/faqs
- ToS: "may not copy or download any content… except with the prior written approval of FMP"; personal license bars company use; bars "software products, or applications designed for utilization by multiple individuals"; delete-on-termination + audit — https://site.financialmodelingprep.com/terms-of-service

### Marketstack

- Free: 100 req/month (pricing page; FAQ contradicts with 1,000), **1 year history**, no commercial use — https://marketstack.com/pricing
- Basic $9.99/mo (10y history) — cheapest paid of the field
- `adj_close` documented but repeatedly observed broken (equal to raw close, nulls, unapplied splits) — https://portfoliooptimizer.io/blog/selecting-a-stock-market-data-web-api-not-so-simple/ ; https://github.com/apilayer/marketstack/issues/10
- ToS: redirects to generic APILayer/Idera legal hub; Marketstack-specific caching/redistribution language not locatable (UNVERIFIED)

## Consequences wired into the map

1. **Methodology ticket #82** must ratify (or veto) weekly return frequency — the vendor pick makes weekly the free path; daily means EODHD at $19.99/mo per client.
2. **Snapshot module #84**: env var `ALPHAVANTAGE_API_KEY`; hard-fail on any 200-with-`Information` body; pin the full weekly-adjusted series per ticker.
3. **Distro sync #87**: client docs = key signup walkthrough, license-posture paragraph, price snapshots gitignored in distro.
